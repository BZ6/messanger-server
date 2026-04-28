import os, sys, json, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import services.shared.db as db
import services.recommendation_engine.router as router
import services.graph_service.graph_api as graph_api

TEST_DB = os.path.join(os.path.expanduser('~'), 'temp', 'router_test.db')


def setup_function():
    db.DB_PATH = TEST_DB
    graph_api._graph_cache = None
    os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db.init_db()


def teardown_function():
    graph_api._graph_cache = None
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _populate():
    """Square A-B-C-D-A with cross edge B-D (higher SNR = better)."""
    conn = db.connect()
    cur  = conn.cursor()
    now  = int(time.time())
    for nid in ('A', 'B', 'C', 'D'):
        cur.execute("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?)", (nid, nid+'1', nid+'1', now))
    # edges: (from, to, snr)  weight = max(0.1, 10 - snr)
    for frm, to, snr in [
        ('A', 'B', 5.0),   # weight 5
        ('B', 'C', 6.0),   # weight 4
        ('C', 'D', 7.0),   # weight 3
        ('D', 'A', 8.0),   # weight 2
        ('B', 'D', 9.0),   # weight 1  ← best cross edge
    ]:
        cur.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", (frm, to, snr, now))
    conn.commit()
    conn.close()


def _populate_two_components():
    conn = db.connect()
    cur  = conn.cursor()
    now  = int(time.time())
    for nid in ('A', 'B', 'C', 'D'):
        cur.execute("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?)", (nid, nid+'1', nid+'1', now))
    cur.execute("INSERT OR REPLACE INTO edges VALUES ('A','B',5.0,?)", (now,))
    cur.execute("INSERT OR REPLACE INTO edges VALUES ('C','D',5.0,?)", (now,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# RoutingService – graph building and path finding
# ---------------------------------------------------------------------------

def test_find_route_exists():
    _populate()
    svc = router.RoutingService()
    # A→C: options A-B-C (5+4=9), A-D-C (2+3=5), A-B-D-C (5+1+3=9)
    path, error = svc.find_route('A', 'C')
    assert error is None
    assert path == ['A', 'D', 'C']


def test_find_route_direct_edge():
    _populate()
    svc = router.RoutingService()
    path, error = svc.find_route('B', 'D')
    assert error is None
    assert path == ['B', 'D']


def test_find_route_same_node():
    _populate()
    svc = router.RoutingService()
    path, error = svc.find_route('A', 'A')
    assert error is None
    assert path == ['A']


def test_find_route_missing_source():
    _populate()
    svc = router.RoutingService()
    path, error = svc.find_route('X', 'A')
    assert error is not None
    assert "Источник X не найден" in error
    assert path is None


def test_find_route_missing_target():
    _populate()
    svc = router.RoutingService()
    path, error = svc.find_route('A', 'Y')
    assert error is not None
    assert "Цель Y не найден" in error
    assert path is None


def test_find_route_no_path():
    _populate_two_components()
    svc = router.RoutingService()
    path, error = svc.find_route('A', 'C')
    assert error is not None
    assert "Путь не найден" in error
    assert path is None


def test_update_graph_refreshes():
    _populate()
    svc = router.RoutingService()
    assert 'F' not in svc.graph.nodes
    conn = db.connect()
    cur  = conn.cursor()
    now  = int(time.time())
    cur.execute("INSERT OR REPLACE INTO nodes VALUES ('F','F1','F1',?)", (now,))
    cur.execute("INSERT OR REPLACE INTO edges VALUES ('A','F',3.0,?)", (now,))
    conn.commit()
    conn.close()
    svc.update_graph()
    assert 'F' in svc.graph.nodes
    assert ('A', 'F') in svc.graph.edges or ('F', 'A') in svc.graph.edges
    for u, v, data in svc.graph.edges(data=True):
        if set((u, v)) == {'A', 'F'}:
            assert data['weight'] == 7.0
            break


def test_get_graph_stats():
    _populate()
    svc   = router.RoutingService()
    stats = svc.get_graph_stats()
    assert stats['nodes'] == 4
    assert stats['edges'] == 5
    assert stats['connected'] is True
    assert stats['server_connected'] is False


# ---------------------------------------------------------------------------
# process_text_message – recommendation publishing
# ---------------------------------------------------------------------------

class _MockMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, json.loads(payload)))


def test_process_text_message_publishes_recommendation():
    _populate()
    svc    = router.RoutingService()
    client = _MockMqttClient()
    payload = {'type': 'text', 'from': 'A', 'to': 'C', 'payload': {'text': 'hello'}}
    topic = router.process_text_message(svc, client, payload)
    assert topic == 'routing/recommendation/A'
    assert len(client.published) == 1
    rec = client.published[0][1]
    assert rec['for_destination'] == 'C'
    assert rec['use_next_hop'] == 'D'           # shortest path A→D→C
    assert rec['hops'] == ['A', 'D', 'C']       # full path as ordered array
    assert rec['hops'][0] == 'A'                # starts at source
    assert rec['hops'][-1] == 'C'              # ends at destination
    assert 'ttl_s' in rec
    assert 0 < rec['score'] <= 1


def test_process_text_message_skips_broadcast():
    _populate()
    svc    = router.RoutingService()
    client = _MockMqttClient()
    payload = {'type': 'text', 'from': 1001, 'to': router.BROADCAST_ADDR}
    result = router.process_text_message(svc, client, payload)
    assert result is None
    assert len(client.published) == 0


def test_process_text_message_skips_non_text():
    _populate()
    svc    = router.RoutingService()
    client = _MockMqttClient()
    for msg_type in ('nodeinfo', 'neighborinfo', 'position', 'telemetry'):
        payload = {'type': msg_type, 'from': 'A', 'to': 'C'}
        assert router.process_text_message(svc, client, payload) is None
    assert len(client.published) == 0


def test_process_text_message_no_route():
    _populate_two_components()
    svc    = router.RoutingService()
    client = _MockMqttClient()
    payload = {'type': 'text', 'from': 'A', 'to': 'C'}
    result = router.process_text_message(svc, client, payload)
    assert result is None
    assert len(client.published) == 0


def test_process_text_message_int_ids_converted_to_hex():
    """Integer from/to are converted to !hex before graph lookup."""
    conn = db.connect()
    cur  = conn.cursor()
    now  = int(time.time())
    for nid in ('!000003e9', '!000003ea'):
        cur.execute("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?)", (nid, nid, nid, now))
    cur.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", ('!000003e9', '!000003ea', 8.0, now))
    conn.commit()
    conn.close()
    svc    = router.RoutingService()
    client = _MockMqttClient()
    # from=1001 (0x3e9), to=1002 (0x3ea)
    payload = {'type': 'text', 'from': 0x3E9, 'to': 0x3EA}
    topic = router.process_text_message(svc, client, payload)
    assert topic == 'routing/recommendation/!000003e9'
    rec = client.published[0][1]
    assert rec['for_destination'] == '!000003ea'
    assert rec['use_next_hop'] == '!000003ea'
    assert rec['hops'] == ['!000003e9', '!000003ea']


def test_find_route_via_server():
    """SERVER acts as a relay with small weight (SNR=100 → weight=0.1).
    Routing through SERVER is valid and often preferred over weak RF links."""
    conn = db.connect()
    cur  = conn.cursor()
    now  = int(time.time())
    for nid in ('!000003e9', '!000003ea'):
        cur.execute("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?)", (nid, nid, nid, now))
    # Weak direct RF edge (SNR=2 → weight=8)
    cur.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", ('!000003e9', '!000003ea', 2.0, now))
    # Server gateway edges (SNR=100 → weight=0.1 each)
    cur.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", ('SERVER', '!000003e9', 100.0, now))
    cur.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", ('SERVER', '!000003ea', 100.0, now))
    conn.commit()
    conn.close()
    svc = router.RoutingService()
    path, error = svc.find_route('!000003e9', '!000003ea')
    assert error is None
    # Via SERVER: 0.1 + 0.1 = 0.2 < direct 8.0 — SERVER path is correctly preferred
    assert 'SERVER' in path
    assert path == ['!000003e9', 'SERVER', '!000003ea']


# ---------------------------------------------------------------------------
# ML model server integration – _ml_route fallback behaviour
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_ml_route_disabled_when_no_server(monkeypatch):
    """ML_SERVER='' means _ml_route always returns None (Dijkstra used)."""
    _populate()
    monkeypatch.setattr(router, 'ML_SERVER', '')
    svc    = router.RoutingService()
    result = router._ml_route(svc, 'A', 'C')
    assert result is None


def test_ml_route_returns_path_on_200(monkeypatch):
    """Valid 200 response with correct endpoints is accepted."""
    _populate()
    monkeypatch.setattr(router, 'ML_SERVER', 'http://fake-ml')
    monkeypatch.setattr(
        router.requests, 'post',
        lambda *a, **kw: _MockResponse(200, {'path': ['A', 'D', 'C']}),
    )
    svc    = router.RoutingService()
    result = router._ml_route(svc, 'A', 'C')
    assert result == ['A', 'D', 'C']


def test_ml_route_rejected_on_wrong_endpoints(monkeypatch):
    """Path with wrong source/target is rejected → returns None."""
    _populate()
    monkeypatch.setattr(router, 'ML_SERVER', 'http://fake-ml')
    monkeypatch.setattr(
        router.requests, 'post',
        lambda *a, **kw: _MockResponse(200, {'path': ['X', 'Y']}),
    )
    svc    = router.RoutingService()
    result = router._ml_route(svc, 'A', 'C')
    assert result is None


def test_ml_route_fallback_on_503(monkeypatch):
    """503 from ML server → _ml_route returns None → Dijkstra used."""
    _populate()
    monkeypatch.setattr(router, 'ML_SERVER', 'http://fake-ml')
    monkeypatch.setattr(
        router.requests, 'post',
        lambda *a, **kw: _MockResponse(503, {}),
    )
    svc    = router.RoutingService()
    client = _MockMqttClient()
    payload = {'type': 'text', 'from': 'A', 'to': 'C'}
    topic  = router.process_text_message(svc, client, payload)
    # Dijkstra fallback must still publish a recommendation
    assert topic == 'routing/recommendation/A'
    assert len(client.published) == 1
    rec = client.published[0][1]
    assert rec['hops'] == ['A', 'D', 'C']


def test_ml_route_fallback_on_connection_error(monkeypatch):
    """Network error → _ml_route returns None → Dijkstra used."""
    _populate()
    monkeypatch.setattr(router, 'ML_SERVER', 'http://fake-ml')

    def _raise(*a, **kw):
        raise ConnectionError("refused")

    monkeypatch.setattr(router.requests, 'post', _raise)
    svc    = router.RoutingService()
    client = _MockMqttClient()
    payload = {'type': 'text', 'from': 'A', 'to': 'C'}
    topic  = router.process_text_message(svc, client, payload)
    assert topic == 'routing/recommendation/A'
    assert client.published[0][1]['hops'] == ['A', 'D', 'C']


def test_process_text_message_uses_ml_path(monkeypatch):
    """When ML returns a valid path it is published (not the Dijkstra path)."""
    _populate()
    monkeypatch.setattr(router, 'ML_SERVER', 'http://fake-ml')
    monkeypatch.setattr(
        router.requests, 'post',
        lambda *a, **kw: _MockResponse(200, {'path': ['A', 'B', 'C']}),
    )
    svc    = router.RoutingService()
    client = _MockMqttClient()
    payload = {'type': 'text', 'from': 'A', 'to': 'C'}
    topic  = router.process_text_message(svc, client, payload)
    assert topic == 'routing/recommendation/A'
    rec = client.published[0][1]
    # ML returned A→B→C, even though Dijkstra would pick A→D→C
    assert rec['hops'] == ['A', 'B', 'C']
    assert rec['use_next_hop'] == 'B'


def test_find_route_direct_beats_server():
    """Strong direct RF link is preferred over the SERVER relay.
    Direct SNR=9 → weight=1.0; SERVER edges SNR=2 → weight=8.0 each (total 16.0).
    Dijkstra must pick the direct path."""
    conn = db.connect()
    cur  = conn.cursor()
    now  = int(time.time())
    for nid in ('!000003e9', '!000003ea'):
        cur.execute("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?)", (nid, nid, nid, now))
    cur.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", ('!000003e9', '!000003ea', 9.0, now))
    cur.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", ('SERVER', '!000003e9', 2.0, now))
    cur.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", ('SERVER', '!000003ea', 2.0, now))
    conn.commit()
    conn.close()

    svc = router.RoutingService()
    path, error = svc.find_route('!000003e9', '!000003ea')
    
    assert error is None
    assert 'SERVER' not in path
    assert path == ['!000003e9', '!000003ea']
