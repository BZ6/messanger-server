import os, sys, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import services.shared.db as db
import services.graph_service.graph_api as graph_api

TEST_DB = os.path.join(os.path.expanduser('~'), 'temp', 'graph_test.db')


def _reset_graph_cache():
    """Force graph_api to rebuild from DB on the next call."""
    graph_api._graph_cache = None


def setup_function():
    db.DB_PATH = TEST_DB
    os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db.init_db()
    _reset_graph_cache()


def teardown_function():
    _reset_graph_cache()
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert(c, nodes=(), edges=()):
    now = int(time.time())
    for node_id in nodes:
        c.execute("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?)", (node_id, node_id, node_id, now))
    for frm, to, snr in edges:
        c.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", (frm, to, snr, now))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_graph_returns_empty_path():
    _reset_graph_cache()
    assert graph_api.get_shortest_path('ANY', 'TARGET') == []


def test_nonexistent_target_returns_empty():
    conn = db.connect()
    _insert(conn.cursor(), nodes=['SERVER'])
    conn.commit()
    conn.close()
    graph_api.load_graph(force_refresh=True)
    assert graph_api.get_shortest_path('SERVER', 'X') == []


def test_disconnected_target_returns_empty():
    conn = db.connect()
    _insert(conn.cursor(), nodes=['SERVER', 'A'], edges=[('A', 'B', 8.0)])
    conn.commit()
    conn.close()
    graph_api.load_graph(force_refresh=True)
    # SERVER is not connected to A or B, so no path
    assert graph_api.get_shortest_path('SERVER', 'B') == []


def test_all_paths_receives_all_nodes():
    conn = db.connect()
    _insert(conn.cursor(), nodes=['SERVER', 'A', 'B'],
            edges=[('SERVER', 'A', 5.0), ('SERVER', 'B', 7.0)])
    conn.commit()
    conn.close()
    graph_api.load_graph(force_refresh=True)
    paths = graph_api.get_all_paths()
    assert 'A' in paths and 'B' in paths


def test_get_reachable_gateways_for_target_returns_valid_targets():
    conn = db.connect()
    _insert(conn.cursor(), nodes=['SERVER', 'A', 'B', 'C'],
            edges=[('SERVER', 'A', 5.0), ('A', 'C', 6.0)])
    conn.commit()
    conn.close()
    graph_api.load_graph(force_refresh=True)
    gateways = graph_api.get_reachable_gateways_for_target('C')
    assert 'A' in gateways


def test_get_reachable_gateways_empty_graph():
    _reset_graph_cache()
    gateways = graph_api.get_reachable_gateways_for_target('nonexistent')
    assert isinstance(gateways, list)


def test_shortest_path_prefers_high_snr():
    conn = db.connect()
    _insert(conn.cursor(), nodes=['A', 'B', 'C', 'D'],
            edges=[
                ('A', 'B', 5.0),   # weight 5
                ('B', 'C', 5.0),   # weight 5  → A→B→C total 10
                ('A', 'D', 9.0),   # weight 1
                ('D', 'C', 9.0),   # weight 1  → A→D→C total 2
            ])
    conn.commit()
    conn.close()
    graph_api.load_graph(force_refresh=True)
    path = graph_api.get_shortest_path('A', 'C')
    assert path == ['A', 'D', 'C']
