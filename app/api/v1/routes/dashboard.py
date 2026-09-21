from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta

from ....core.database import get_db
from ....core.dependencies import require_technician
from ....models.user import User
from ....models.ticket import Ticket, TicketStatus, TicketPriority
from sqlalchemy import case
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    """Get dashboard statistics for technicians and admins."""
    # Total tickets
    total_result = await db.execute(select(func.count()).select_from(Ticket))
    total_tickets = total_result.scalar() or 0

    # Tickets by status
    status_results = await db.execute(
        select(Ticket.status, func.count()).group_by(Ticket.status)
    )
    tickets_by_status = {
        (s.value if hasattr(s, "value") else str(s)): c
        for s, c in status_results.all()
    }

    # Tickets by priority
    priority_results = await db.execute(
        select(Ticket.priority, func.count()).group_by(Ticket.priority)
    )
    tickets_by_priority = {
        (p.value if hasattr(p, "value") else str(p)): c
        for p, c in priority_results.all()
    }

    # Tickets created in last 7 days
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_result = await db.execute(
        select(func.count()).select_from(Ticket).where(Ticket.created_at >= week_ago)
    )
    recent_tickets = recent_result.scalar() or 0

    # Tickets assigned to current user (active)
    my_tickets = await db.execute(
        select(func.count()).select_from(Ticket).where(
            and_(
                Ticket.assigned_to == current_user.id,
                Ticket.status.in_([TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS]),
            )
        )
    )
    my_active_tickets = my_tickets.scalar() or 0

    return {
        "total_tickets": total_tickets,
        "tickets_by_status": tickets_by_status,
        "tickets_by_priority": tickets_by_priority,
        "recent_tickets_7days": recent_tickets,
        "my_active_tickets": my_active_tickets,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/technician-performance")
async def get_technician_performance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    """Get performance stats for technicians."""
    from ....models.user import UserRole
    from sqlalchemy import case

    # Conditional aggregation using CASE WHEN (works on MySQL/MariaDB)
    resolved_count = func.sum(
        case((Ticket.status == TicketStatus.RESOLVED, 1), else_=0)
    ).label("resolved")

    total_assigned = func.count(Ticket.id).label("total_assigned")

    # Admins see all technicians; technicians see only themselves
    if current_user.role == UserRole.ADMIN:
        query = (
            select(
                User.full_name,
                total_assigned,
                resolved_count,
            )
            .join(Ticket, Ticket.assigned_to == User.id, isouter=True)
            .where(User.role == UserRole.TECHNICIAN)
            .group_by(User.id, User.full_name)
        )
    else:
        query = (
            select(
                User.full_name,
                total_assigned,
                resolved_count,
            )
            .join(Ticket, Ticket.assigned_to == User.id, isouter=True)
            .where(User.id == current_user.id)
            .group_by(User.id, User.full_name)
        )

    result = await db.execute(query)
    performances = [
        {
            "technician": row[0],
            "total_assigned": row[1] or 0,
            "resolved": row[2] or 0,
        }
        for row in result.all()
    ]

    return {"technicians": performances}