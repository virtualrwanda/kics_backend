"""
WebSocket connection manager.
Tracks active WebSocket connections per user and broadcasts messages.
"""

from fastapi import WebSocket
from typing import Dict, Set
import logging
import json

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # user_id → set of WebSockets (a user may have multiple tabs open)
        self.active: Dict[int, Set[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active.setdefault(user_id, set()).add(websocket)
        logger.info(f"🔌 WS connected: user {user_id} (total: {len(self.active[user_id])})")

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active:
            self.active[user_id].discard(websocket)
            if not self.active[user_id]:
                del self.active[user_id]
        logger.info(f"🔌 WS disconnected: user {user_id}")

    async def send_to_user(self, user_id: int, payload: dict):
        """Send a message to all connections of a user."""
        if user_id not in self.active:
            return
        dead = set()
        for ws in self.active[user_id]:
            try:
                await ws.send_text(json.dumps(payload, default=str))
            except Exception as e:
                logger.warning(f"WS send failed to user {user_id}: {e}")
                dead.add(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    async def broadcast(self, user_ids: list, payload: dict):
        """Send to many users."""
        for uid in set(user_ids):
            await self.send_to_user(uid, payload)

    def is_online(self, user_id: int) -> bool:
        return user_id in self.active


manager = ConnectionManager()