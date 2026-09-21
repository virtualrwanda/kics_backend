from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional, List

from ....core.database import get_db
from ....core.dependencies import require_admin
from ....models.user import User
from ....models.audit_log import AuditLog

router = APIRouter(prefix="/admin/audit", tags=["Audit Log"])


@router.get("/logs")
async def list_audit_logs(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin: view the audit log."""
    q = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)

    result = await db.execute(q)
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "user_id": l.user_id,
            "action": l.action,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "description": l.description,
            "ip_address": l.ip_address,
            "created_at": l.created_at,
        }
        for l in logs
    ]