#!/usr/bin/env python3
"""
Routing / Recommendation Engine

Listens to msh/+/json/+/+ (same feed as the collector).
When a TEXT message arrives between two specific nodes, computes the
shortest path through the known mesh graph and publishes a routing
recommendation to routing/recommendation/<source_nodeId> per CONTRACT v0.3.

Recommendation payload:
  { "for_destination": "!...", "use_next_hop": "!...", "ttl_s": 60, "score": 0.85 }
"""
import json
import logging
import os
import signal
import sys
import time
from typing import List, Optional, Tuple

import networkx as nx
import paho.mqtt.client as mqtt
import requests

import services.shared.db as db
import services.graph_service.graph_api as graph_api

logger = logging.getLogger("recommendation_engine")

MQTT_BROKER     = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT       = int(os.getenv("MQTT_PORT", "1883"))
SUBSCRIBE_TOPIC = "msh/+/json/+/+"
BROADCAST_ADDR  = 4294967295   # 0xFFFFFFFF – mesh broadcast, skip
GRAPH_REFRESH_S = int(os.getenv("GRAPH_REFRESH_INTERVAL", "30"))

SERVER_NODE_ID  = "SERVER"

# ML model server — empty string disables ML and always uses Dijkstra
ML_SERVER  = os.getenv("ML_SERVER", "")
ML_TIMEOUT = float(os.getenv("ML_TIMEOUT", "2.0"))


# ---------------------------------------------------------------------------
# RoutingService – pure graph logic, no MQTT
# ---------------------------------------------------------------------------

class RoutingService:
    def __init__(self, db_path: str = None):
        if db_path is not None:
            db.DB_PATH = db_path
        self.db_path = db.DB_PATH
        db.init_db()
        graph_api.load_graph(force_refresh=True)   # прогреть кэш при старте

    @property
    def graph(self) -> nx.Graph:
        """Граф из graph_api — единственный источник истины."""
        return graph_api.load_graph()

    def find_route(
        self, source_id: str, target_id: str
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        G = graph_api.load_graph()
        if source_id not in G.nodes:
            return None, f"Источник {source_id} не найден в графе"
        if target_id not in G.nodes:
            return None, f"Цель {target_id} не найдена в графе"
        try:
            path = nx.shortest_path(G, source=source_id, target=target_id, weight="weight")
            return path, None
        except nx.NetworkXNoPath:
            return None, "Путь не найден"
        except Exception as exc:
            logger.error("Ошибка поиска маршрута: %s", exc)
            return None, str(exc)

    def update_graph(self):
        graph_api.load_graph(force_refresh=True)
        G = graph_api.load_graph()
        logger.info(
            "Граф обновлен: %d узлов, %d рёбер",
            G.number_of_nodes(),
            G.number_of_edges(),
        )

    def get_graph_stats(self) -> dict:
        G = graph_api.load_graph()
        n = G.number_of_nodes()
        if n == 0:
            return {"nodes": 0, "edges": 0, "connected": False}
        return {
            "nodes": n,
            "edges": G.number_of_edges(),
            "connected": nx.is_connected(G),
            "server_connected": SERVER_NODE_ID in G.nodes,
        }


# ---------------------------------------------------------------------------
# Message processing – extracted for unit-testability
# ---------------------------------------------------------------------------

def _to_hex(node_id) -> str:
    """Convert integer node ID to !hexhex format."""
    if isinstance(node_id, int):
        return f"!{node_id:08x}"
    if isinstance(node_id, str) and node_id.startswith("!"):
        return node_id
    return str(node_id)


def _path_score(svc: RoutingService, path: List[str]) -> float:
    """Confidence score ∈ (0, 1]: higher is better.  1 / (1 + total_weight)."""
    try:
        total = nx.path_weight(svc.graph, path, weight="weight")
        return round(1.0 / (1.0 + total), 3)
    except Exception:
        return 0.5


def _ml_route(svc: RoutingService, source: str, dest: str) -> Optional[List[str]]:
    """
    Ask the ML model server for a route.  Returns path list or None on any failure.
    Falls back to Dijkstra when ML_SERVER is not configured or the server is down.
    """
    if not ML_SERVER:
        return None
    try:
        nodes = list(svc.graph.nodes)
        edges = [
            {"from": u, "to": v, "snr": d.get("snr", 5.0)}
            for u, v, d in svc.graph.edges(data=True)
        ]
        resp = requests.post(
            f"{ML_SERVER}/route",
            json={"nodes": nodes, "edges": edges, "source": source, "target": dest},
            timeout=ML_TIMEOUT,
        )
        if resp.status_code == 200:
            path = resp.json().get("path")
            # Basic sanity: path must start at source and end at dest
            if (isinstance(path, list) and len(path) >= 2
                    and path[0] == source and path[-1] == dest):
                logger.debug("ML route %s→%s: %s", source, dest, path)
                return path
    except Exception as exc:
        logger.debug("ML server unavailable (%s), falling back to Dijkstra", exc)
    return None


def process_text_message(
    svc: RoutingService, mqtt_client, payload: dict
) -> Optional[str]:
    """
    Handle one decoded MQTT payload dict.  Returns the published topic, or None.

    payload must have at minimum:
      { "type": "text", "from": <int|str>, "to": <int|str> }

    Route selection order:
      1. ML model server (if ML_SERVER is set and responds)
      2. Dijkstra on the local NetworkX graph (fallback)
    """
    if payload.get("type") != "text":
        return None

    from_raw = payload.get("from")
    to_raw   = payload.get("to")
    if from_raw is None or to_raw is None:
        return None

    # Skip broadcasts
    if isinstance(to_raw, int) and to_raw == BROADCAST_ADDR:
        return None

    source_hex = _to_hex(from_raw)
    dest_hex   = _to_hex(to_raw)

    # Try ML model first; fall back to Dijkstra on any failure
    path   = _ml_route(svc, source_hex, dest_hex)
    method = "ml"
    if path is None:
        path, error = svc.find_route(source_hex, dest_hex)
        method = "dijkstra"
        if error or not path or len(path) < 2:
            logger.debug(
                "No route %s→%s: %s", source_hex, dest_hex, error or "path too short"
            )
            return None

    if len(path) < 2:
        return None

    # Full computed path as an ordered array of node IDs from source to destination.
    # The receiving node reads `hops` and uses each entry in sequence.
    # `use_next_hop` is the immediate next hop (path[1]) kept for quick lookup.
    next_hop = path[1]
    score    = _path_score(svc, path)
    recommendation = {
        "for_destination": dest_hex,
        "hops":            path,          # e.g. ["!000003e9", "!000003eb", "!000003ea"]
        "use_next_hop":    next_hop,      # convenience shortcut = hops[1]
        "ttl_s":           60,
        "score":           score,
    }
    topic = f"routing/recommendation/{source_hex}"
    mqtt_client.publish(topic, json.dumps(recommendation))
    logger.info(
        "Recommendation [%s]: %s → %s  path=%s  score=%.3f",
        method, source_hex, dest_hex, " → ".join(path), score,
    )
    return topic


# ---------------------------------------------------------------------------
# Standalone service entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    svc = RoutingService()

    def on_connect(client, _userdata, _flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(SUBSCRIBE_TOPIC)
            logger.info("Subscribed to %s", SUBSCRIBE_TOPIC)
        else:
            logger.error("MQTT connect failed, rc=%d", rc)

    def on_message(client, _userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            process_text_message(svc, client, payload)
        except Exception as exc:
            logger.error("on_message error: %s", exc)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()

    signal.signal(signal.SIGINT,  lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    try:
        while True:
            time.sleep(GRAPH_REFRESH_S)
            svc.update_graph()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
