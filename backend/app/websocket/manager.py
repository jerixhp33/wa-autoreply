import json
import logging
from typing import Dict, List, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per user."""

    def __init__(self):
        # Maps user_id -> list of websocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket connected for user {user_id}")

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"WebSocket disconnected for user {user_id}")

    async def send_to_user(self, user_id: str, event: str, data: dict):
        """Send event to all connections for a user."""
        if user_id not in self.active_connections:
            return

        message = json.dumps({"event": event, "data": data})
        dead_connections = []

        for connection in self.active_connections[user_id]:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send WS message: {e}")
                dead_connections.append(connection)

        for conn in dead_connections:
            self.disconnect(conn, user_id)

    async def broadcast_event(self, event: str, data: dict):
        """Broadcast event to all connected users."""
        message = json.dumps({"event": event, "data": data})
        for user_id in list(self.active_connections.keys()):
            for connection in list(self.active_connections.get(user_id, [])):
                try:
                    await connection.send_text(message)
                except Exception:
                    self.disconnect(connection, user_id)


# Global manager instance
ws_manager = ConnectionManager()
