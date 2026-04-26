#!/usr/bin/env python3
"""
Routing Service - вычисление маршрутов между любыми узлами через MQTT
Слушает запросы на маршрут и публикует ответы.
"""
import json, time, logging
from typing import Optional, List, Tuple
import paho.mqtt.client as mqtt
import services.shared.db as db
import networkx as nx

logger = logging.getLogger("routing_service")

# MQTT settings
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
REQUEST_TOPIC = "route/request"
RESPONSE_TOPIC = "route/response"

SERVER_NODE_ID = "SERVER"  # kept for compatibility, but not used for routing between arbitrary nodes


class RoutingService:
    def __init__(self, db_path: str = None):
        if db_path is not None:
            db.DB_PATH = db_path
        self.db_path = db.DB_PATH
        db.init_db()
        self.graph = nx.Graph()
        self._build_graph()

    def _build_graph(self):
        """Строит граф на основе данных из БД"""
        self.graph.clear()
        edges = db.list_edges()
        
        # Добавляем все узлы и ребра
        nodes_set = set()
        for edge in edges:
            from_node, to_node, snr, last_seen = edge
            
            for node in [from_node, to_node]:
                if node not in nodes_set:
                    self.graph.add_node(node)
                    nodes_set.add(node)
            
            weight = self._calculate_weight(snr)
            self.graph.add_edge(from_node, to_node, weight=weight, snr=snr)

    def _calculate_weight(self, snr: Optional[float]) -> float:
        """Вычисляет вес ребра на основе SNR"""
        if snr is None:
            return 1.0
        return max(0.1, 10.0 - snr)

    def find_route(self, source_id: str, target_id: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """Находит кратчайший путь между source_id и target_id.
        Возвращает (path, error). Если путь не существует, path=None и error содержит описание.
        """
        if source_id not in self.graph.nodes:
            return None, f"Источник {source_id} не найден в графе"
        if target_id not in self.graph.nodes:
            return None, f"Цель {target_id} не найдена в графе"
        
        try:
            path = nx.shortest_path(self.graph, source=source_id, target=target_id, weight='weight')
            return path, None
        except nx.NetworkXNoPath:
            return None, "Путь не найден"
        except Exception as e:
            logger.error(f"Ошибка поиска маршрута: {e}")
            return None, str(e)

    def update_graph(self):
        """Обновляет граф из БД"""
        self._build_graph()
        logger.info(f"Граф обновлен: {self.graph.number_of_nodes()} узлов, {self.graph.number_of_edges()} ребер")

    def get_graph_stats(self) -> dict:
        """Возвращает статистику графа"""
        if self.graph.number_of_nodes() == 0:
            return {"nodes": 0, "edges": 0, "connected": False}
        
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "connected": nx.is_connected(self.graph),
            "server_connected": SERVER_NODE_ID in self.graph.nodes
        }


def main():
    # Настройка логирования
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Инициализируем сервис маршрутизации
    router = RoutingService()
    
    # MQTT клиент
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("Подключен к MQTT брокеру")
            client.subscribe(REQUEST_TOPIC)
            logger.info(f"Подписан на топик {REQUEST_TOPIC}")
        else:
            logger.error(f"Не удалось подключиться к MQTT, код возврата {rc}")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            source = payload.get('source')
            target = payload.get('target')
            request_id = payload.get('request_id')
            
            if not source or not target:
                logger.warning(f"Получен запрос без source или target: {payload}")
                return
            
            logger.info(f"Запрос маршрута: {source} -> {target} (id={request_id})")
            path, error = router.find_route(source, target)
            
            response = {
                "request_id": request_id,
                "source": source,
                "target": target,
                "path": path,
                "error": error,
                "timestamp": int(time.time())
            }
            
            client.publish(RESPONSE_TOPIC, json.dumps(response, ensure_ascii=False))
            if error:
                logger.warning(f"Маршрут не найден: {error}")
            else:
                logger.info(f"Маршрут найден: {' -> '.join(path)}")
                
        except json.JSONDecodeError:
            logger.error(f"Не удалось декодировать JSON из сообщения: {msg.payload}")
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Подключаемся и начинаем цикл
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    
    try:
        # Периодически обновляем граф (например, каждые 30 секунд)
        while True:
            time.sleep(5)
            router.update_graph()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()