import os, sys, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import services.shared.db as db
from services.node_service.node_service import NodeService

TEST_DB = os.path.join(os.path.expanduser('~'), 'temp', 'node_service_test.db')

def setup_function():
    db.DB_PATH = TEST_DB
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db.init_db()

def teardown_function():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

def test_register_node():
    service = NodeService()
    service.register_node(long_name='Alpha', short_name='A', node_id='n1')
    row = service.get_node('n1')
    assert row is not None
    assert row.node_id == 'n1'

def test_unique_registration():
    service = NodeService()
    assert service.unique_registration('n2') is True
    service.register_node(long_name='Beta', short_name='B', node_id='n2')
    assert service.unique_registration('n2') is False
