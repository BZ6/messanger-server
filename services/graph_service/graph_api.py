#!/usr/bin/env python3
"""
Graph API – central services for:
* loading the graph from SQLite,
* computing shortest paths from the virtual SERVER node,
* exposing path data for the web UI.
All functions are thread‑safe and cache the DB‐derived graph.
"""

import os, time, json, threading, sqlite3
import networkx as nx
import services.shared.db as db

# -----------------------------------------------------------------
# 1. Configuration & thread‑safe cache
# -----------------------------------------------------------------
_graph_lock = threading.Lock()
_graph_cache = None          # type: nx.Graph | None
_cache_path = os.getenv('GRAPH_CACHE_PATH', '/tmp/graph_cache.pkl')

# -----------------------------------------------------------------
# 2. Low‑level DB → NetworkX conversion
# -----------------------------------------------------------------
def _load_graph_from_db() -> nx.Graph:
    """
    Read the current edge set from the SQLite DB and build a NetworkX graph.
    Edge weight = max(0.1, 10 − snr).  Only edges newer than 7 days are used.
    The virtual SERVER node is added and connected with weight‑0 edges.
    """
    G = nx.Graph()

    conn = sqlite3.connect(db.DB_PATH)
    cur = conn.cursor()
    cutoff = int(time.time() - 7 * 86400)          # 7‑day freshness window
    cur.execute(
        "SELECT from_node, to_node, snr, last_seen FROM edges WHERE last_seen > ?",
        (cutoff,))
    for frm, to, snr, _ in cur.fetchall():
        if not frm or not to:
            continue
        weight = max(0.1, 10 - snr) if snr is not None else 1.0
        G.add_edge(frm, to, weight=weight, snr=snr)
    conn.close()

    # Ensure the virtual SERVER exists
    SERVER_NODE_ID = "SERVER"
    if SERVER_NODE_ID not in G.nodes:
        G.add_node(SERVER_NODE_ID)

    return G

def load_graph(force_refresh: bool = False) -> nx.Graph:
    """
    Public accessor – thread‑safe.  Returns the cached graph unless
    ``force_refresh`` is True, in which case the DB is read again.
    """
    global _graph_cache
    with _graph_lock:
        if _graph_cache is None or force_refresh:
            _graph_cache = _load_graph_from_db()
            # Persist cache to disk for the next run (optional)
            try:
                cache_path = os.getenv('GRAPH_CACHE_PATH', '/tmp/graph_cache.pkl')
                with open(cache_path, 'wb') as f:
                    import pickle
                    pickle.dump(_graph_cache, f)
            except Exception:
                pass
        return _graph_cache

# -----------------------------------------------------------------
# 3. Public query helpers
# -----------------------------------------------------------------
def get_shortest_path(source: str, target: str) -> list:
    """Return the shortest path from `source` to `target` as a list of node IDs.
    If either node does not exist or no path exists, return an empty list."""
    G = load_graph()
    if source not in G or target not in G:
        return []
    try:
        return nx.shortest_path(G, source=source, target=target, weight='weight')
    except nx.NetworkXNoPath:
        return []

def get_all_paths() -> dict:
    """
    Return mapping ``{target_node: [path_list]}`` for every reachable node
    from the virtual SERVER node.  If SERVER is missing, returns an empty dict.
    """
    G = load_graph()
    SERVER_NODE_ID = "SERVER"
    if SERVER_NODE_ID not in G:
        return {}

    paths = {}
    for node in G.nodes:
        if node == SERVER_NODE_ID:
            continue
        try:
            path = nx.shortest_path(G, source=SERVER_NODE_ID, target=node, weight='weight')
            paths[node] = path
        except nx.NetworkXNoPath:
            pass
    return paths

def get_reachable_gateways_for_target(target: str) -> list:
    """
    In the recommendation model the first real hop after SERVER is the
    “gateway” that will forward messages to the target.
    Return a list of candidate gateway IDs.
    """
    all_paths = get_all_paths()
    if target not in all_paths:
        # Target unreachable – fall back to offering *any* non‑SERVER node
        G = load_graph()
        return [n for n in G.nodes if n != "SERVER" and n != target]

    route = all_paths[target]
    if len(route) < 2:
        return []
    return [route[1]]   # first real node after SERVER