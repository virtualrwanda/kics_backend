from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, literal_column, case
from typing import Optional, List
from datetime import datetime, timedelta

from ....core.database import get_db
from ....core.dependencies import require_admin
from ....models.user import User, UserRole
from ....models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from ....models.analytics import (
    TicketSLA,
    Complaint,
    ComplaintType,
    SatisfactionRating,
    SLAPolicy,
)
from ....schemas.admin import (
    UserListResponse,
    TechnicianPerformance,
    DeadlineItem,
    ComplaintResponse,
    TicketVolumeReport,
    SLAPolicyUpdate,
)
from ....services import export_service

router = APIRouter(prefix="/admin", tags=["Admin"])


# ============================================================
# 1. USER MANAGEMENT
# ============================================================
@router.get("/users", response_model=List[UserListResponse])
async def list_all_users(
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    department: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List all users with filters."""
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if department:
        query = query.where(User.department == department)
    if search:
        query = query.where(
            or_(
                User.full_name.like(f"%{search}%"),
                User.email.like(f"%{search}%"),
            )
        )
    query = query.order_by(User.role, User.full_name)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/users/stats")
async def user_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """User count by role."""
    result = await db.execute(select(User.role, func.count()).group_by(User.role))
    by_role = {
        str(r.value if hasattr(r, "value") else r): c
        for r, c in result.all()
    }
    active_result = await db.execute(
        select(func.count()).select_from(User).where(User.is_active == True)
    )
    total_active = active_result.scalar() or 0
    return {"by_role": by_role, "total_active": total_active}


# ============================================================
# 2. TECHNICIAN PERFORMANCE
# ============================================================
@router.get("/performance/technicians", response_model=List[TechnicianPerformance])
async def technician_performance(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Performance report for all technicians over last N days."""
    since = datetime.utcnow() - timedelta(days=days)

    techs_result = await db.execute(
        select(User).where(User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]))
    )
    technicians = techs_result.scalars().all()

    performances = []

    for tech in technicians:
        # One query for counts + avg
        stats_query = (
            select(
                func.count(Ticket.id).label("total"),
                func.sum(case((Ticket.status == TicketStatus.RESOLVED, 1), else_=0)).label("resolved"),
                func.sum(case((Ticket.status == TicketStatus.REOPENED, 1), else_=0)).label("reopened"),
                func.avg(
                    func.timestampdiff(
                        literal_column("SECOND"),
                        Ticket.created_at,
                        Ticket.resolved_at,
                    )
                ).label("avg_seconds"),
            )
            .where(
                and_(
                    Ticket.assigned_to == tech.id,
                    Ticket.created_at >= since,
                )
            )
        )
        row = (await db.execute(stats_query)).one()

        total_assigned = int(row.total or 0)
        total_resolved = int(row.resolved or 0)
        total_reopened = int(row.reopened or 0)
        avg_hours = round(float(row.avg_seconds or 0) / 3600, 2)

        # Complaints
        complaints_count = await db.scalar(
            select(func.count()).select_from(Complaint).where(
                and_(
                    Complaint.against_user == tech.id,
                    Complaint.created_at >= since,
                )
            )
        ) or 0

        # CSAT
        avg_csat = await db.scalar(
            select(func.avg(SatisfactionRating.rating)).where(
                and_(
                    SatisfactionRating.technician_id == tech.id,
                    SatisfactionRating.created_at >= since,
                )
            )
        )

        performances.append({
            "technician_id": tech.id,
            "technician_name": tech.full_name,
            "total_assigned": total_assigned,
            "total_resolved": total_resolved,
            "total_reopened": total_reopened,
            "avg_resolution_hours": avg_hours,
            "avg_first_response_minutes": 0.0,
            "sla_compliance_percent": 0.0,
            "avg_csat_rating": round(float(avg_csat), 2) if avg_csat else None,
            "complaints_count": complaints_count,
            "rank": None,
        })

    performances.sort(
        key=lambda x: (x["total_resolved"], -x["complaints_count"]),
        reverse=True,
    )
    for i, p in enumerate(performances, start=1):
        p["rank"] = i

    return performances


# ============================================================
# 3. DEADLINES / SLA
# ============================================================
@router.get("/deadlines", response_model=List[DeadlineItem])
async def upcoming_deadlines(
    hours_ahead: int = Query(48, ge=1, le=720),
    overdue_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List tickets approaching or past deadline."""
    now = datetime.utcnow()
    cutoff = now + timedelta(hours=hours_ahead)

    query = select(TicketSLA, Ticket).join(Ticket, Ticket.id == TicketSLA.ticket_id)
    if overdue_only:
        query = query.where(TicketSLA.resolution_deadline < now)
    else:
        query = query.where(TicketSLA.resolution_deadline <= cutoff)
    query = query.where(Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]))
    query = query.order_by(TicketSLA.resolution_deadline.asc())

    result = await db.execute(query)
    rows = result.all()

    items = []
    for sla, ticket in rows:
        minutes_remaining = int((sla.resolution_deadline - now).total_seconds() / 60)
        assignee_name = None
        if ticket.assigned_to:
            assignee = await db.get(User, ticket.assigned_to)
            assignee_name = assignee.full_name if assignee else None

        items.append({
            "ticket_id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "priority": ticket.priority.value if hasattr(ticket.priority, "value") else str(ticket.priority),
            "status": ticket.status.value if hasattr(ticket.status, "value") else str(ticket.status),
            "assigned_to": assignee_name,
            "resolution_deadline": sla.resolution_deadline,
            "minutes_remaining": minutes_remaining,
            "is_overdue": minutes_remaining < 0,
            "is_escalated": sla.is_escalated,
        })
    return items


@router.get("/deadlines/overdue")
async def overdue_tickets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List of overdue tickets."""
    now = datetime.utcnow()
    result = await db.execute(
        select(TicketSLA, Ticket)
        .join(Ticket, Ticket.id == TicketSLA.ticket_id)
        .where(
            and_(
                TicketSLA.resolution_deadline < now,
                Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
        )
        .order_by(TicketSLA.resolution_deadline.asc())
    )
    rows = result.all()
    return {
        "count": len(rows),
        "tickets": [
            {
                "id": t.id,
                "number": t.ticket_number,
                "title": t.title,
                "deadline": s.resolution_deadline.isoformat(),
                "overdue_minutes": int((now - s.resolution_deadline).total_seconds() / 60),
            }
            for s, t in rows
        ],
    }


# ============================================================
# 4. COMPLAINTS
# ============================================================
@router.get("/complaints", response_model=List[ComplaintResponse])
async def list_complaints(
    is_resolved: Optional[bool] = None,
    complaint_type: Optional[ComplaintType] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List all complaints."""
    query = select(Complaint)
    if is_resolved is not None:
        query = query.where(Complaint.is_resolved == is_resolved)
    if complaint_type:
        query = query.where(Complaint.complaint_type == complaint_type)
    query = query.order_by(desc(Complaint.created_at))
    result = await db.execute(query)
    complaints = result.scalars().all()

    out = []
    for c in complaints:
        against_name = None
        if c.against_user:
            u = await db.get(User, c.against_user)
            against_name = u.full_name if u else None
        out.append({
            "id": c.id,
            "ticket_id": c.ticket_id,
            "complaint_type": c.complaint_type.value if hasattr(c.complaint_type, "value") else str(c.complaint_type),
            "description": c.description,
            "severity": c.severity,
            "against_user": against_name,
            "is_resolved": c.is_resolved,
            "created_at": c.created_at,
        })
    return out


@router.post("/complaints/{complaint_id}/resolve")
async def resolve_complaint(
    complaint_id: int,
    resolution_notes: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Mark a complaint as resolved."""
    complaint = await db.get(Complaint, complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    complaint.is_resolved = True
    complaint.resolved_by = current_user.id
    complaint.resolution_notes = resolution_notes
    complaint.resolved_at = datetime.utcnow()
    await db.commit()
    return {"message": "Complaint resolved"}


# ============================================================
# 5. REPORTS
# ============================================================
@router.get("/reports/tickets", response_model=TicketVolumeReport)
async def ticket_volume_report(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Ticket volume report."""
    since = datetime.utcnow() - timedelta(days=days)

    total_created = await db.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.created_at >= since)
    ) or 0
    total_resolved = await db.scalar(
        select(func.count()).select_from(Ticket).where(
            and_(Ticket.status == TicketStatus.RESOLVED, Ticket.created_at >= since)
        )
    ) or 0
    total_closed = await db.scalar(
        select(func.count()).select_from(Ticket).where(
            and_(Ticket.status == TicketStatus.CLOSED, Ticket.created_at >= since)
        )
    ) or 0
    total_reopened = await db.scalar(
        select(func.count()).select_from(Ticket).where(
            and_(Ticket.status == TicketStatus.REOPENED, Ticket.created_at >= since)
        )
    ) or 0

    cat_result = await db.execute(
        select(Ticket.category, func.count())
        .where(Ticket.created_at >= since)
        .group_by(Ticket.category)
    )
    by_category = {
        (c.value if hasattr(c, "value") else str(c)): cnt
        for c, cnt in cat_result.all()
    }

    pri_result = await db.execute(
        select(Ticket.priority, func.count())
        .where(Ticket.created_at >= since)
        .group_by(Ticket.priority)
    )
    by_priority = {
        (p.value if hasattr(p, "value") else str(p)): cnt
        for p, cnt in pri_result.all()
    }

    stat_result = await db.execute(
        select(Ticket.status, func.count())
        .where(Ticket.created_at >= since)
        .group_by(Ticket.status)
    )
    by_status = {
        (s.value if hasattr(s, "value") else str(s)): cnt
        for s, cnt in stat_result.all()
    }

    return {
        "period": f"last_{days}_days",
        "total_created": total_created,
        "total_resolved": total_resolved,
        "total_closed": total_closed,
        "total_reopened": total_reopened,
        "by_category": by_category,
        "by_priority": by_priority,
        "by_status": by_status,
    }


# ============================================================
# 6. EXPORTS (CSV / PDF)
# ============================================================
@router.get("/reports/tickets/export")
async def export_tickets(
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Download ticket report as CSV or PDF."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    if format == "csv":
        content = await export_service.export_tickets_csv(db, days)
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="tickets_{timestamp}.csv"'
            },
        )
    else:
        content = await export_service.export_tickets_pdf(db, days)
        return StreamingResponse(
            iter([content]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="tickets_{timestamp}.pdf"'
            },
        )


@router.get("/reports/technicians/export")
async def export_technician_performance(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Download technician performance as CSV."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    content = await export_service.export_technician_performance_csv(db, days)
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="technicians_{timestamp}.csv"'
        },
    )


# ============================================================
# 7. SLA POLICIES
# ============================================================
@router.get("/sla-policies")
async def list_sla_policies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(SLAPolicy))
    return result.scalars().all()


@router.put("/sla-policies/{policy_id}")
async def update_sla_policy(
    policy_id: int,
    payload: SLAPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    policy = await db.get(SLAPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    policy.first_response_minutes = payload.first_response_minutes
    policy.resolution_minutes = payload.resolution_minutes
    policy.is_active = payload.is_active
    await db.commit()
    return {"message": "Policy updated"}