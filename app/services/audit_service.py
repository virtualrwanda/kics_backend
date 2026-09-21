import logging
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def log_action(
    db: AsyncSession,
    user_id: Optional[int],
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    description: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    changes: Optional[Dict[str, Any]] = None,
):
    """Record an audit event. Fails silently."""
    try:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:500],
            changes=changes,
        )
        db.add(entry)
        await db.flush()
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")