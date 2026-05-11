#!/usr/bin/env python3
import os, sqlite3, time

DB_PATH = os.getenv('MESHTASTIC_DB', '/var/lib/meshtastic/mesh_network.db')

def _connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = _connect()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS nodes
                    (node_id TEXT PRIMARY KEY,
                     long_name TEXT,
                     short_name TEXT,
                     last_seen INTEGER)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS edges
                    (from_node TEXT,
                     to_node TEXT,
                     snr REAL,
                     last_seen INTEGER,
                     UNIQUE(from_node, to_node))''')
    conn.commit()
    conn.close()

def connect():
    return _connect()

def ensure_init():
    init_db()

def register_node(node_id, long_name='', short_name=''):
    ensure_init()
    ts = int(time.time())
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        '''INSERT OR REPLACE INTO nodes (node_id, long_name, short_name, last_seen)
           VALUES (?, ?, ?, ?)''',
        (node_id, long_name, short_name, ts)
    )
    conn.commit()
    conn.close()

def store_edge(from_node, to_node, snr=None):
    ensure_init()
    ts = int(time.time())
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        '''INSERT OR REPLACE INTO edges (from_node, to_node, snr, last_seen)
           VALUES (?, ?, ?, ?)''',
        (from_node, to_node, snr, ts)
    )
    conn.commit()
    conn.close()

def get_node(node_id):
    ensure_init()
    conn = _connect()
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes WHERE node_id = ?', (node_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_neighbors(node_id):
    ensure_init()
    conn = _connect()
    cur = conn.cursor()
    cur.execute('SELECT to_node, snr FROM edges WHERE from_node = ?', (node_id,))
    rows = cur.fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows]

def list_nodes():
    ensure_init()
    conn = _connect()
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes')
    rows = cur.fetchall()
    conn.close()
    return rows

def list_edges(cutoff: int | None = None):
    ensure_init()
    conn = _connect()
    cur = conn.cursor()
    if cutoff is not None:
        cur.execute('SELECT from_node, to_node, snr, last_seen FROM edges WHERE last_seen > ?', (cutoff,))
    else:
        cur.execute('SELECT * FROM edges')
    rows = cur.fetchall()
    conn.close()
    return rows
