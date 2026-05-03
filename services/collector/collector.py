#!/usr/bin/env python3
import json
import os
import time
import logging
import signal
import sys

import paho.mqtt.client as mqtt
import services.shared.db as db

logger = logging.getLogger("collector")

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))

SUBSCRIBE_TOPIC = "msh/+/json/+/+"


def _to_hex(node_id):
    if isinstance(node_id, int):
        return f"!{node_id:08x}"
    if isinstance(node_id, str) and node_id.startswith("!"):
        return node_id
    return str(node_id)


def handle_node_info(node_id, data, timestamp):
    try:
        long_name  = data.get("longname",  "N/A")
        short_name = data.get("shortname", "N/A")
        conn = db.connect()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO nodes (node_id, long_name, short_name, last_seen) VALUES (?, ?, ?, ?)",
            (node_id, long_name, short_name, timestamp),
        )
        conn.commit()
        conn.close()
        logger.debug("Node updated: %s (%s)", node_id, long_name)
    except Exception as exc:
        logger.error("NodeInfo error: %s", exc)


def handle_neighbor_info(packet_from, data, timestamp):
    try:
        neighbors = data.get("neighbors", [])
        if not neighbors:
            return
        conn = db.connect()
        c = conn.cursor()
        for nb in neighbors:
            to_node = _to_hex(nb.get("node_id"))
            snr     = nb.get("snr")
            if to_node:
                c.execute(
                    "INSERT OR REPLACE INTO edges (from_node, to_node, snr, last_seen) VALUES (?, ?, ?, ?)",
                    (packet_from, to_node, snr, timestamp),
                )
        conn.commit()
        conn.close()
        logger.info("NeighborInfo: %s -> %d neighbors", packet_from, len(neighbors))
    except Exception as exc:
        logger.error("NeighborInfo error: %s", exc)


def on_message(client, userdata, msg):
    try:
        payload   = json.loads(msg.payload.decode())
        from_int  = payload.get("from")
        sender    = payload.get("sender", "")
        timestamp = payload.get("timestamp", int(time.time()))
        msg_type  = payload.get("type", "")
        inner     = payload.get("payload", {})

        if from_int is None:
            return

        packet_from = _to_hex(from_int)

        if sender:
            db.store_edge("SERVER", sender, snr=100.0)

        if msg_type == "nodeinfo":
            node_id = inner.get("id", packet_from)
            handle_node_info(node_id, inner, timestamp)
        elif msg_type == "neighborinfo":
            handle_neighbor_info(packet_from, inner, timestamp)

    except Exception as exc:
        logger.error("on_message error: %s", exc)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    db.init_db()
    logger.info("Database initialised: %s", db.DB_PATH)

    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(SUBSCRIBE_TOPIC)
    logger.info("Collector started, subscribed to %s", SUBSCRIBE_TOPIC)

    signal.signal(signal.SIGINT,  lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    client.loop_forever()


if __name__ == "__main__":
    main()
