#!/usr/bin/env python3
"""
Node Service - регистрация и управление нодами
Предоставляет API для регистрации новых нод и присвоения уникальных ID
"""

import os, sqlite3, time, uuid, logging
from typing import Optional, Dict, List
from dataclasses import dataclass
import services.shared.db as db

logger = logging.getLogger("node_service")

@dataclass
class NodeInfo:
    node_id: str
    long_name: str = ""
    short_name: str = ""
    last_seen: int = 0
    is_gateway: bool = False

class NodeService:
    def __init__(self, db_path: str = None):
        if db_path is not None:
            db.DB_PATH = db_path
        self.db_path = db.DB_PATH
        db.init_db()
    
    def register_node(self, long_name: str = "", short_name: str = "", 
                     node_id: str = None, is_gateway: bool = False) -> NodeInfo:
        """Регистрирует новую ноду с уникальным ID"""
        if not node_id:
            # Генерируем уникальный ID если не указан
            node_id = str(uuid.uuid4())[:8]  # 8 символов UUID
        
        # Проверка уникальности ID
        existing = db.get_node(node_id)
        if existing:
            logger.warning(f"Node ID {node_id} уже существует, обновляем")
         
        # Регистрация
        db.register_node(node_id, long_name, short_name)
        
        # Сохраняем информацию о шлюзе если указано
        if is_gateway:
            self._set_gateway_status(node_id, True)
        
        node = NodeInfo(
            node_id=node_id,
            long_name=long_name,
            short_name=short_name,
            last_seen=int(time.time()),
            is_gateway=is_gateway
        )
        
        logger.info(f"Зарегистрирована нода: {node_id} ({long_name or 'unnamed'})")
        return node
    
    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """Получает информацию о ноде по ID"""
        data = db.get_node(node_id)
        if data:
            return NodeInfo(
                node_id=data[0],
                long_name=data[1],
                short_name=data[2],
                last_seen=data[3]
            )
        return None
    
    def list_nodes(self) -> List[NodeInfo]:
        """Возвращает список всех нод"""
        nodes_data = db.list_nodes()
        return [
            NodeInfo(
                node_id=data[0],
                long_name=data[1],
                short_name=data[2],
                last_seen=data[3]
            )
            for data in nodes_data
        ]
    
    def get_gateways(self) -> List[NodeInfo]:
        """Возвращает список шлюзовых нод"""
        all_nodes = self.list_nodes()
        # В реальности здесь была бы проверка флага is_gateway
        return [node for node in all_nodes if node.is_gateway]
    
    def _set_gateway_status(self, node_id: str, is_gateway: bool):
        """Устанавливает статус шлюза для ноды"""
        # В реальной реализации здесь была бы таблица gateway_status
        pass

    def unique_registration(self, node_id: str) -> bool:
        """Проверяет, свободен ли узел ID для регистрации."""
        return self.get_node(node_id) is None

# Пример использования
if __name__ == "__main__":
    service = NodeService()
    
    # Регистрация новой ноды
    node1 = service.register_node(long_name="Node1", short_name="N1")
    print(f"Зарегистрирована нода: {node1.node_id}")
    
    # Регистрация шлюза
    gateway = service.register_node(
        long_name="Gateway1", 
        short_name="GW1", 
        is_gateway=True
    )
    print(f"Зарегистрирован шлюз: {gateway.node_id}")
    
    # Получение списка всех нод
    all_nodes = service.list_nodes()
    print(f"Всего нод: {len(all_nodes)}")