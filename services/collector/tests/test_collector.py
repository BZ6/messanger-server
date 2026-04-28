import os, sys, json, time, sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import services.shared.db as db
import services.collector.collector as collector

TEST_DB = os.path.join(os.path.expanduser('~'), 'temp', 'collector_test.db')


def setup_function():
    db.DB_PATH = TEST_DB
    os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db.init_db()


def teardown_function():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


# ---------------------------------------------------------------------------
# handle_node_info
# ---------------------------------------------------------------------------

def test_handle_node_info():
    data = {'id': '!000003e9', 'longname': 'Long', 'shortname': 'S'}
    collector.handle_node_info('!000003e9', data, int(time.time()))
    conn = sqlite3.connect(TEST_DB)
    row = conn.execute(
        'SELECT node_id, long_name, short_name FROM nodes WHERE node_id=?',
        ('!000003e9',),
    ).fetchone()
    conn.close()
    assert row == ('!000003e9', 'Long', 'S')


def test_handle_node_info_update():
    ts = int(time.time())
    collector.handle_node_info('!00000001', {'longname': 'Old', 'shortname': 'O'}, ts)
    collector.handle_node_info('!00000001', {'longname': 'New', 'shortname': 'N'}, ts + 1)
    conn = sqlite3.connect(TEST_DB)
    row = conn.execute(
        'SELECT long_name, short_name FROM nodes WHERE node_id=?', ('!00000001',)
    ).fetchone()
    conn.close()
    assert row == ('New', 'N')


def test_handle_node_info_missing_fields():
    # Should not raise even with empty data
    collector.handle_node_info('!000000ff', {}, int(time.time()))
    conn = sqlite3.connect(TEST_DB)
    row = conn.execute('SELECT long_name, short_name FROM nodes WHERE node_id=?', ('!000000ff',)).fetchone()
    conn.close()
    assert row == ('N/A', 'N/A')


# ---------------------------------------------------------------------------
# handle_neighbor_info
# ---------------------------------------------------------------------------

def test_handle_neighbor_info():
    ts = int(time.time())
    data = {'neighbors': [{'node_id': 0x3EA, 'snr': 7.5}]}  # integer node_id
    collector.handle_neighbor_info('!000003e9', data, ts)
    conn = sqlite3.connect(TEST_DB)
    row = conn.execute(
        'SELECT from_node, to_node, snr FROM edges WHERE from_node=?', ('!000003e9',)
    ).fetchone()
    conn.close()
    assert row == ('!000003e9', '!000003ea', 7.5)


def test_handle_neighbor_info_multiple():
    ts = int(time.time())
    data = {'neighbors': [{'node_id': 0x3EA, 'snr': 7.5}, {'node_id': 0x3EB, 'snr': 6.0}]}
    collector.handle_neighbor_info('!000003e9', data, ts)
    conn = sqlite3.connect(TEST_DB)
    rows = conn.execute(
        'SELECT to_node, snr FROM edges WHERE from_node=?', ('!000003e9',)
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert ('!000003ea', 7.5) in rows
    assert ('!000003eb', 6.0) in rows


def test_handle_neighbor_info_empty():
    ts = int(time.time())
    collector.handle_neighbor_info('!000003e9', {'neighbors': []}, ts)
    conn = sqlite3.connect(TEST_DB)
    rows = conn.execute('SELECT * FROM edges WHERE from_node=?', ('!000003e9',)).fetchall()
    conn.close()
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# on_message – full pipeline
# ---------------------------------------------------------------------------

class _FakeMsg:
    def __init__(self, d):
        self.payload = json.dumps(d).encode()


def test_on_message_nodeinfo():
    ts = int(time.time())
    msg = _FakeMsg({
        'from': 0x3E9,
        'to': 0xFFFFFFFF,
        'sender': '!000003e9',
        'timestamp': ts,
        'type': 'nodeinfo',
        'payload': {'id': '!000003e9', 'longname': 'Alpha', 'shortname': 'A'},
    })
    collector.on_message(None, None, msg)
    row = db.get_node('!000003e9')
    assert row is not None
    assert row[1] == 'Alpha'
    # SERVER→sender gateway edge must be stored
    conn = sqlite3.connect(TEST_DB)
    gw = conn.execute('SELECT * FROM edges WHERE from_node=? AND to_node=?',
                      ('SERVER', '!000003e9')).fetchone()
    conn.close()
    assert gw is not None


def test_on_message_neighborinfo():
    ts = int(time.time())
    msg = _FakeMsg({
        'from': 0x3E9,
        'sender': '!000003e9',
        'timestamp': ts,
        'type': 'neighborinfo',
        'payload': {'node_id': 0x3E9, 'neighbors': [{'node_id': 0x3EA, 'snr': 8.0}]},
    })
    collector.on_message(None, None, msg)
    conn = sqlite3.connect(TEST_DB)
    row = conn.execute(
        'SELECT from_node, to_node, snr FROM edges WHERE from_node=? AND to_node=?',
        ('!000003e9', '!000003ea'),
    ).fetchone()
    conn.close()
    assert row == ('!000003e9', '!000003ea', 8.0)


def test_on_message_unknown_type_is_ignored():
    msg = _FakeMsg({'from': 1, 'sender': '!00000001', 'timestamp': 0, 'type': 'position', 'payload': {}})
    # Should not raise and should only store the gateway edge
    collector.on_message(None, None, msg)
    conn = sqlite3.connect(TEST_DB)
    rows = conn.execute('SELECT * FROM nodes').fetchall()
    conn.close()
    assert len(rows) == 0  # no node was inserted


def test_on_message_no_from_is_ignored():
    msg = _FakeMsg({'sender': '!00000001', 'type': 'nodeinfo', 'payload': {}})
    collector.on_message(None, None, msg)  # must not raise
