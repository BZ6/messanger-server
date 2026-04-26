import os, sys, json, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import services.shared.db as db
import services.recommendation_engine.router as router

TEST_DB = os.path.join(os.path.expanduser('~'), 'temp', 'router_test.db')

def setup_function():
    db.DB_PATH = TEST_DB
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    conn = db.connect()
    c = conn.cursor()
    c.execute("CREATE TABLE nodes (node_id TEXT PRIMARY KEY, long_name TEXT, short_name TEXT, last_seen INTEGER)")
    c.execute("CREATE TABLE edges (from_node TEXT, to_node TEXT, snr REAL, last_seen INTEGER)")
    conn.commit()
    conn.close()

def teardown_function():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

def _populate():
    conn = db.connect()
    cur = conn.cursor()
    now = int(time.time())
    # Add nodes
    cur.execute("INSERT INTO nodes VALUES ('A','A1','A1',?)", (now,))
    cur.execute("INSERT INTO nodes VALUES ('B','B1','B1',?)", (now,))
    cur.execute("INSERT INTO nodes VALUES ('C','C1','C1',?)", (now,))
    cur.execute("INSERT INTO nodes VALUES ('D','D1','D1',?)", (now,))
    # Add edges forming a square A-B-C-D-A with varying SNR
    cur.execute("INSERT INTO edges VALUES ('A','B',5.0,?)", (now,))   # weight = 5
    cur.execute("INSERT INTO edges VALUES ('B','C',6.0,?)", (now,))   # weight = 4
    cur.execute("INSERT INTO edges VALUES ('C','D',7.0,?)", (now,))   # weight = 3
    cur.execute("INSERT INTO edges VALUES ('D','A',8.0,?)", (now,))   # weight = 2
    # Add a cross edge B-D with high SNR (low weight)
    cur.execute("INSERT INTO edges VALUES ('B','D',9.0,?)", (now,))   # weight = 1
    conn.commit()
    conn.close()

def _populate_two_components():
    conn = db.connect()
    cur = conn.cursor()
    now = int(time.time())
    # Component 1: A-B
    cur.execute("INSERT INTO nodes VALUES ('A','A1','A1',?)", (now,))
    cur.execute("INSERT INTO nodes VALUES ('B','B1','B1',?)", (now,))
    cur.execute("INSERT INTO edges VALUES ('A','B',5.0,?)", (now,))
    # Component 2: C-D
    cur.execute("INSERT INTO nodes VALUES ('C','C1','C1',?)", (now,))
    cur.execute("INSERT INTO nodes VALUES ('D','D1','D1',?)", (now,))
    cur.execute("INSERT INTO edges VALUES ('C','D',5.0,?)", (now,))
    conn.commit()
    conn.close()

def test_find_route_exists():
    _populate()
    r = router.RoutingService()
    # Path from A to C: possible routes: A-B-C (weights 5+4=9), A-D-C (2+3=5), A-B-D-C (5+1+3=9)
    # Shortest should be A-D-C (weight 5)
    path, error = r.find_route('A', 'C')
    assert error is None
    assert path == ['A', 'D', 'C']

def test_find_route_direct_edge():
    _populate()
    r = router.RoutingService()
    # Direct edge B-D exists with weight 1
    path, error = r.find_route('B', 'D')
    assert error is None
    assert path == ['B', 'D']

def test_find_route_same_node():
    _populate()
    r = router.RoutingService()
    path, error = r.find_route('A', 'A')
    assert error is None
    assert path == ['A']

def test_find_route_missing_source():
    _populate()
    r = router.RoutingService()
    path, error = r.find_route('X', 'A')
    assert error is not None
    assert "Источник X не найден" in error
    assert path is None

def test_find_route_missing_target():
    _populate()
    r = router.RoutingService()
    path, error = r.find_route('A', 'Y')
    assert error is not None
    assert "Цель Y не найден" in error
    assert path is None

def test_find_route_no_path():
    _populate_two_components()
    r = router.RoutingService()
    # A and C are in different components, no path
    path, error = r.find_route('A', 'C')
    assert error is not None
    assert "Путь не найден" in error
    assert path is None

def test_update_graph_refreshes():
    _populate()
    r = router.RoutingService()
    initial_nodes = set(r.graph.nodes)
    # Add a new node and edge via direct DB manipulation
    conn = db.connect()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("INSERT INTO nodes VALUES ('F','F1','F1',?)", (now,))
    cur.execute("INSERT INTO edges VALUES ('A','F',3.0,?)", (now,))  # weight 7
    conn.commit()
    conn.close()
    # Before update, graph should not have F
    assert 'F' not in r.graph.nodes
    # Call update_graph
    r.update_graph()
    # After update, graph should have F and edge A-F
    assert 'F' in r.graph.nodes
    assert ('A', 'F') in r.graph.edges or ('F', 'A') in r.graph.edges
    # Check that weight is correct (should be max(0.1, 10-3)=7)
    for u, v, data in r.graph.edges(data=True):
        if set((u, v)) == {'A', 'F'}:
            assert data['weight'] == 7.0
            break

def test_get_graph_stats():
    _populate()
    r = router.RoutingService()
    stats = r.get_graph_stats()
    assert stats['nodes'] == 4  # A, B, C, D
    # edges: we added 5 edges (A-B, B-C, C-D, D-A, B-D)
    assert stats['edges'] == 5
    assert stats['connected'] is True
    # SERVER node is not in graph unless we added it; we didn't, so server_connected False
    assert stats['server_connected'] is False