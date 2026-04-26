import os, sys, json, time, sqlite3

# Add project root to path for proper imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import services.shared.db as db
import services.collector.collector as collector

TEST_DB = os.path.join(os.path.expanduser('~'), 'temp', 'collector_test.db')

def setup_function():
    db.DB_PATH = TEST_DB
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db.init_db()

def teardown_function():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

def test_handle_node_info():
    payload = {
        'from': 'node123',
        'rxTime': int(time.time()),
        'decoded': {'portnum': 'NODEINFO_APP', 'user': {'longName': 'Long', 'shortName': 'S'}}
    }
    collector.handle_node_info('node123', payload['decoded'], payload['rxTime'])
    conn = sqlite3.connect(TEST_DB)
    row = conn.execute('SELECT node_id, long_name, short_name FROM nodes WHERE node_id=?', ('node123',)).fetchone()
    conn.close()
    assert row == ('node123', 'Long', 'S')

def test_handle_node_info_update():
    ts = int(time.time())
    collector.handle_node_info('n1', {'portnum': 'NODEINFO_APP', 'user': {'longName': 'Old', 'shortName': 'O'}}, ts)
    collector.handle_node_info('n1', {'portnum': 'NODEINFO_APP', 'user': {'longName': 'New', 'shortName': 'N'}}, ts+1)
    conn = sqlite3.connect(TEST_DB)
    row = conn.execute('SELECT long_name, short_name FROM nodes WHERE node_id=?', ('n1',)).fetchone()
    conn.close()
    assert row == ('New', 'N')

def test_handle_neighbor_info():
    ts = int(time.time())
    payload = {
        'from': 'A',
        'decoded': {'portnum': 'NEIGHBORINFO_APP',
                    'neighborinfo': {'neighbors': [{'node_id': 'B', 'snr': 7.5}]}}
    }
    collector.handle_neighbor_info('A', payload['decoded'], ts)
    conn = sqlite3.connect(TEST_DB)
    row = conn.execute('SELECT from_node, to_node, snr FROM edges WHERE from_node=?', ('A',)).fetchone()
    conn.close()
    assert row == ('A', 'B', 7.5)

def test_handle_neighbor_info_multiple():
    ts = int(time.time())
    payload = {
        'from': 'A',
        'decoded': {'portnum': 'NEIGHBORINFO_APP',
                    'neighborinfo': {'neighbors': [
                        {'node_id': 'B', 'snr': 7.5},
                        {'node_id': 'C', 'snr': 6.0}
                    ]}}
    }
    collector.handle_neighbor_info('A', payload['decoded'], ts)
    conn = sqlite3.connect(TEST_DB)
    rows = conn.execute('SELECT to_node, snr FROM edges WHERE from_node=?', ('A',)).fetchall()
    conn.close()
    assert len(rows) == 2
    assert ('B', 7.5) in rows
    assert ('C', 6.0) in rows

def test_handle_neighbor_info_empty():
    ts = int(time.time())
    payload = {
        'from': 'A',
        'decoded': {'portnum': 'NEIGHBORINFO_APP',
                    'neighborinfo': {'neighbors': []}}
    }
    collector.handle_neighbor_info('A', payload['decoded'], ts)
    conn = sqlite3.connect(TEST_DB)
    rows = conn.execute('SELECT * FROM edges WHERE from_node=?', ('A',)).fetchall()
    conn.close()
    assert len(rows) == 0
