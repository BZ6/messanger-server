#!/usr/bin/env python3
"""
collector.py – MQTT Collector for Meshtastic
Сохраняет информацию об узлах и рёбрах графа в SQLite.
"""
import json
import time
import logging
import signal
import sys

import paho.mqtt.client as mqtt
import services.shared.db as db

logger = logging.getLogger("collector")

# ========== НАСТРОЙКИ ==========
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

def init_db():
    db.init_db()
    logger.info(f"База данных инициализирована: {db.DB_PATH}")

def handle_node_info(packet_from, data, timestamp):
    try:
        user = data.get('user', {})
        long_name = user.get('longName', 'N/A')
        short_name = user.get('shortName', 'N/A')
        conn = db.connect()
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO nodes (node_id, long_name, short_name, last_seen)
                     VALUES (?, ?, ?, ?)''', (packet_from, long_name, short_name, timestamp))
        conn.commit()
        conn.close()
        logger.debug(f"Node updated: {packet_from} ({long_name})")
    except Exception as e:
        logger.error(f"NodeInfo error: {e}")

def handle_neighbor_info(packet_from, data, timestamp):
    try:
        neighbor_info = data.get('neighborinfo', {})
        neighbors = neighbor_info.get('neighbors', [])
        if not neighbors:
            return
        conn = db.connect()
        c = conn.cursor()
        for nb in neighbors:
            to_node = nb.get('node_id')
            snr = nb.get('snr')
            if to_node:
                c.execute('''INSERT OR REPLACE INTO edges (from_node, to_node, snr, last_seen)
                             VALUES (?, ?, ?, ?)''', (packet_from, to_node, snr, timestamp))
        conn.commit()
        conn.close()
        logger.info(f"NeighborInfo: {packet_from} -> {len(neighbors)} neighbors")
    except Exception as e:
        logger.error(f"NeighborInfo error: {e}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        packet_from = payload.get('from')
        if not packet_from:
            return
        timestamp = payload.get('rxTime', int(time.time()))
        decoded = payload.get('decoded', {})
        portnum = decoded.get('portnum')
        if portnum == 'NODEINFO_APP':
            handle_node_info(packet_from, decoded, timestamp)
        elif portnum == 'NEIGHBORINFO_APP':
            handle_neighbor_info(packet_from, decoded, timestamp)
    except Exception as e:
        logger.error(f"on_message error: {e}")

def main():
    init_db()
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe("msh/+/2/json/#")
    logger.info("Collector запущен, ожидает MQTT...")
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    client.loop_forever()

if __name__ == "__main__":
    main()