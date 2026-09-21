from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from jose import JWTError
import json
import logging

from ....core.security import decode_token
from ....core.database import AsyncSessionLocal
from ....models.user import User
from ....services.ws_manager import manager
from sqlalchemy import select

router = APIRouter(tags=["WebSocket"])
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """
    WebSocket for real-time chat + notifications.
    Connect: ws://localhost:8000/api/v1/ws?token=YOUR_JWT
    """
    # Authenticate
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id = int(payload.get("sub", 0))
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Verify user exists
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    # Connect
    await manager.connect(user_id, websocket)
    try:
        await websocket.send_text(json.dumps({
            "event": "connected",
            "user_id": user_id,
            "message": "WebSocket connected",
        }))

        # Listen for incoming messages (simple echo/ping handler)
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                # Handle ping
                if msg.get("event") == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
                # Optionally handle typing indicators here
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception as e:
        logger.exception(f"WS error for user {user_id}: {e}")
        manager.disconnect(user_id, websocket)