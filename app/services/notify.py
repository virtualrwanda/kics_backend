"""
Sends real-time notifications over WebSocket when ticket events occur.
"""

from typing import List, Optional
from .ws_manager import manager
from ..core.database import AsyncSessionLocal
from ..models.user import User, UserRole
from sqlalchemy import select


async def notify_ticket_event(
    event: str,
    ticket_id: int,
    ticket_number: Optional[str],
    title: str,
    actor_id: int,
    actor_name: str,
    extra: Optional[dict] = None,
    audience: Optional[List[int]] = None,
):
    """
    Broadcast a ticket event to relevant users.

    event: "ticket_created" | "ticket_assigned" | "ticket_commented" |
           "ticket_resolved" | "ticket_reopened" | "ticket_closed"
    """
    payload = {
        "event": event,
        "ticket_id": ticket_id,
        "ticket_number": ticket_number,
        "title": title,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "extra": extra or {},
    }

    if audience is None:
        # Default: notify admins + technicians
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User.id).where(
                    User.role.in_([UserRole.ADMIN, UserRole.TECHNICIAN]),
                    User.is_active == True,
                )
            )
            audience = [row[0] for row in result.all()]

    # Remove the actor themselves
    audience = [uid for uid in audience if uid != actor_id]

    await manager.broadcast(audience, payload)