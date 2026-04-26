#!/usr/bin/env python3
"""
Routing Service - маршрутизация сообщений через шлюзы
Находит кратчайший путь от сервера к целевой ноде и отправляет сообщение через нужный шлюз
"""

import json, time, logging
from typing import Optional, List, Tuple
import services.shared.db as db
import networkx as nx

logger = logging.getLogger("routing_service")

SERVER_NODE_ID = "SERVER"

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
    
    def _add_server_connections(self):
        """Добавляет виртуальное соединение от сервера ко всем узлам"""
        # Удаляем старые виртуальные соединения
        edges_to_remove = []
        for u, v, data in self.graph.edges(data=True):
            if data.get('is_virtual') and (u == SERVER_NODE_ID or v == SERVER_NODE_ID):
                edges_to_remove.append((u, v))
        for u, v in edges_to_remove:
            self.graph.remove_edge(u, v)
        
        # Удаляем SERVER если он есть
        if SERVER_NODE_ID in self.graph.nodes:
            self.graph.remove_node(SERVER_NODE_ID)
        
        # Добавляем SERVER заново
        self.graph.add_node(SERVER_NODE_ID)
        
        # Соединяем SERVER со всеми реальными узлами
        for node in [n for n in self.graph.nodes if n != SERVER_NODE_ID]:
            self.graph.add_edge(SERVER_NODE_ID, node, weight=0.0, is_virtual=True)
    
    def find_route_to_target(self, target_id: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """Находит маршрут от SERVER до целевой ноды"""
        if target_id not in self.graph.nodes:
            return None, f"Цель {target_id} не найдена в графе"
        
        # Добавляем SERVER если еще не добавлен
        if SERVER_NODE_ID not in self.graph.nodes:
            self._add_server_connections()
        
        try:
            path = nx.shortest_path(self.graph, source=SERVER_NODE_ID, target=target_id, weight='weight')
            return path, None
        except nx.NetworkXNoPath:
            return None, "Путь не найден"
        except Exception as e:
            logger.error(f"Ошибка поиска маршрута: {e}")
            return None, str(e)
    
    def select_gateway(self, target_id: str) -> Tuple[Optional[str], Optional[List[str]], Optional[str]]:
        """
        Выбирает шлюз для доставки сообщения целевой ноде.
        Возвращает (gateway_id, route, error)
        Шлюз - это первая нода после SERVER в маршруте.
        """
        path, error = self.find_route_to_target(target_id)
        if error:
            return None, None, error
        
        if len(path) < 2:
            return None, None, "Некорректный маршрут"
        
        gateway = path[1]  # Первая реальная нода после SERVER
        return gateway, path, None
    
    def format_gateway_command(self, gateway_id: str, destination_id: str, text: str) -> dict:
        """Форматирует команду для отправки шлюзу"""
        return {
            "type": "sendText",
            "destinationId": destination_id,
            "text": text,
            "timestamp": int(time.time()),
            "route_type": "mesh"
        }
    
    def get_routing_table(self) -> List[dict]:
        """Возвращает таблицу маршрутизации (кратчайшие пути до всех узлов)"""
        if SERVER_NODE_ID not in self.graph.nodes:
            self._add_server_connections()
        
        routing_table = []
        for node in self.graph.nodes:
            if node == SERVER_NODE_ID:
                continue
            
            path, error = self.find_route_to_target(node)
            if path:
                routing_table.append({
                    "destination": node,
                    "gateway": path[1] if len(path) > 1 else None,
                    "path": path,
                    "hops": len(path) - 1
                })
        
        return routing_table
    
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

    # Пример использования
if __name__ == "__main__":
    router = RoutingService()
    
    # Добавляем тестовые данные
    db.register_node("node1", "Node 1", "N1")
    db.register_node("node2", "Node 2", "N2")
    db.store_edge("node1", "node2", 8.0)
    
    # Обновляем граф
    router.update_graph()
    
    # Ищем маршрут
    gateway, route, error = router.select_gateway("node2")
    if gateway:
        print(f"Шлюз: {gateway}")
        print(f"Маршрут: {' -> '.join(route)}")
        
        # Формируем команду
        cmd = router.format_gateway_command(gateway, "node2", "Hello World")
        print(f"Команда: {json.dumps(cmd, ensure_ascii=False)}")
    else:
        print(f"Ошибка: {error}")