import os, sys, time, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import services.shared.db as db
import services.graph_service.graph_api as graph_api

TEST_DB = os.path.join(os.path.expanduser('~'), 'temp', 'graph_test.db')

def setup_function():
    db.DB_PATH = TEST_DB
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    conn = db.connect()
    c = conn.cursor()
    c.execute("""CREATE TABLE nodes (node_id TEXT PRIMARY KEY, long_name TEXT, short_name TEXT, last_seen INTEGER)""")
    c.execute("""CREATE TABLE edges (from_node TEXT, to_node TEXT, snr REAL, last_seen INTEGER)""")
    conn.commit()
    conn.close()

def teardown_function():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    graph_api.load_graph.cache_clear() if hasattr(graph_api.load_graph, 'cache_clear') else None

def test_empty_graph_returns_empty_path():
    assert graph_api.get_shortest_path('ANY', 'TARGET') == []

def test_nonexistent_target_returns_empty():
    tmp = os.path.join(os.path.expanduser('~'), 'temp', 't.db')
    # Ensure we start with a clean slate
    if os.path.exists(tmp):
        os.remove(tmp)
    db.DB_PATH = tmp
    db.init_db()
    conn = db.connect()
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('SERVER','S','S',int(time.time())))
    conn.commit()
    conn.close()
    graph_api.load_graph.cache_clear() if hasattr(graph_api.load_graph, 'cache_clear') else None
    assert graph_api.get_shortest_path('SERVER', 'X') == []
    if os.path.exists(tmp):
        os.remove(tmp)

def test_disconnected_target_returns_empty():
    tmp = os.path.join(os.path.expanduser('~'), 'temp', 'tdb.db')
    db.DB_PATH = tmp
    db.init_db()
    conn = db.connect()
    now = int(time.time())
    c = conn.cursor()
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('SERVER','S','S',now))
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('A','A','A',now))
    c.execute("INSERT INTO edges VALUES (?,?,?,?)", ('A','B',8.0,now))
    conn.commit()
    conn.close()
    graph_api.load_graph.cache_clear() if hasattr(graph_api.load_graph, 'cache_clear') else None
    assert graph_api.get_shortest_path('SERVER', 'B') == []
    os.remove(tmp)

def test_all_paths_receives_all_nodes():
    tmp = os.path.join(os.path.expanduser('~'), 'temp', 'tpdb.db')
    # Ensure we start with a clean slate
    if os.path.exists(tmp):
        os.remove(tmp)
    db.DB_PATH = tmp
    db.init_db()
    conn = db.connect()
    now = int(time.time())
    c = conn.cursor()
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('SERVER','S','S',now))
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('A','A1','A1',now))
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('B','B1','B1',now))
    c.execute("INSERT INTO edges VALUES (?,?,?,?)", ('SERVER','A',5.0,now))
    c.execute("INSERT INTO edges VALUES (?,?,?,?)", ('SERVER','B',7.0,now))
    conn.commit()
    conn.close()
    # Force a refresh of the graph cache to ensure we get the latest data
    graph_api.load_graph(force_refresh=True)
    paths = graph_api.get_all_paths()
    assert 'A' in paths and 'B' in paths
    if os.path.exists(tmp):
        os.remove(tmp)

def test_get_reachable_gateways_for_target_returns_valid_targets():
    tmp = os.path.join(os.path.expanduser('~'), 'temp', 'rgdb.db')
    # Ensure we start with a clean slate
    if os.path.exists(tmp):
        os.remove(tmp)
    db.DB_PATH = tmp
    db.init_db()
    conn = db.connect()
    now = int(time.time())
    c = conn.cursor()
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('SERVER','S','S',now))
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('A','A1','A1',now))
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('B','Beta','B',now))
    c.execute("INSERT INTO nodes VALUES (?,?,?,?)", ('C','Gamma','C',now))
    c.execute("INSERT INTO edges VALUES (?,?,?,?)", ('SERVER','A',5.0,now))
    c.execute("INSERT INTO edges VALUES (?,?,?,?)", ('A','C',6.0,now))
    conn.commit()
    conn.close()
    # Force a refresh of the graph cache to ensure we get the latest data
    graph_api.load_graph(force_refresh=True)
    gateways = graph_api.get_reachable_gateways_for_target('C')
    assert 'A' in gateways
    if os.path.exists(tmp):
        os.remove(tmp)
