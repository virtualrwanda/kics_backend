"""
Rating, leaderboard, and target tracking service.
All queries are MySQL/MariaDB-compatible.
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, case, literal_column, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User, UserRole
from ..models.ticket import Ticket, TicketStatus
from ..models.rating import TicketRating, TechnicianTarget
from ..models.analytics import TicketSLA, Complaint


# ============================================================
# PERFORMANCE METRICS FOR A SINGLE TECHNICIAN
# ============================================================
async def compute_technician_metrics(
    db: AsyncSession,
    technician_id: int,
    since: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return a dict of computed metrics for one technician."""
    since = since or (datetime.utcnow() - timedelta(days=30))

    # Ticket counts
    counts = await db.execute(
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
        ).where(
            and_(
                Ticket.assigned_to == technician_id,
                Ticket.created_at >= since,
            )
        )
    )
    row = counts.one()
    total_assigned = int(row.total or 0)
    total_resolved = int(row.resolved or 0)
    total_reopened = int(row.reopened or 0)
    avg_resolution_hours = round(float(row.avg_seconds or 0) / 3600, 2)

    # CSAT
    csat = await db.execute(
        select(
            func.count(TicketRating.id).label("total_rated"),
            func.avg(TicketRating.stars).label("avg_stars"),
            func.avg(TicketRating.speed_rating).label("avg_speed"),
            func.avg(TicketRating.quality_rating).label("avg_quality"),
            func.avg(TicketRating.communication_rating).label("avg_communication"),
            func.avg(TicketRating.professionalism_rating).label("avg_professionalism"),
        ).where(
            and_(
                TicketRating.technician_id == technician_id,
                TicketRating.created_at >= since,
            )
        )
    )
    c = csat.one()
    total_rated = int(c.total_rated or 0)
    avg_stars = round(float(c.avg_stars or 0), 2)

    # SLA compliance (percent of tickets whose resolution SLA was met)
    sla_row = await db.execute(
        select(
            func.count(TicketSLA.id).label("total_with_sla"),
            func.sum(case((TicketSLA.resolution_met == True, 1), else_=0)).label("met"),
        )
        .join(Ticket, Ticket.id == TicketSLA.ticket_id)
        .where(
            and_(
                Ticket.assigned_to == technician_id,
                TicketSLA.resolved_at.isnot(None),
                Ticket.created_at >= since,
            )
        )
    )
    sla = sla_row.one()
    sla_total = int(sla.total_with_sla or 0)
    sla_met = int(sla.met or 0)
    sla_percent = round((sla_met / sla_total) * 100, 1) if sla_total else 0.0

    # Complaints
    complaints = await db.scalar(
        select(func.count()).select_from(Complaint).where(
            and_(
                Complaint.against_user == technician_id,
                Complaint.created_at >= since,
            )
        )
    ) or 0

    return {
        "technician_id": technician_id,
        "total_assigned": total_assigned,
        "total_resolved": total_resolved,
        "total_reopened": total_reopened,
        "avg_resolution_hours": avg_resolution_hours,
        "total_rated": total_rated,
        "avg_stars": avg_stars,
        "avg_speed": round(float(c.avg_speed or 0), 2) if c.avg_speed else None,
        "avg_quality": round(float(c.avg_quality or 0), 2) if c.avg_quality else None,
        "avg_communication": round(float(c.avg_communication or 0), 2) if c.avg_communication else None,
        "avg_professionalism": round(float(c.avg_professionalism or 0), 2) if c.avg_professionalism else None,
        "sla_compliance_percent": sla_percent,
        "complaints_count": complaints,
    }


# ============================================================
# COMPOSITE SCORE (for ranking)
# ============================================================
def composite_score(metrics: Dict[str, Any]) -> float:
    """
    Weighted score for leaderboard ranking.
      - CSAT (avg stars)      : 40%
      - SLA compliance        : 25%
      - Resolution volume     : 20%
      - Speed (inverse time)  : 15%
    """
    csat = metrics.get("avg_stars") or 0            # 0–5
    sla = metrics.get("sla_compliance_percent") or 0  # 0–100
    resolved = metrics.get("total_resolved") or 0
    hours = metrics.get("avg_resolution_hours") or 0

    # Normalize to 0–1
    csat_n = csat / 5.0
    sla_n = sla / 100.0
    volume_n = min(resolved / 50.0, 1.0)   # 50+ resolved = full marks
    speed_n = 1.0 / (1.0 + (hours / 24.0)) if hours >= 0 else 0

    score = (
        csat_n * 0.40 +
        sla_n * 0.25 +
        volume_n * 0.20 +
        speed_n * 0.15
    ) * 100

    return round(score, 2)


# ============================================================
# LEADERBOARD
# ============================================================
async def compute_leaderboard(
    db: AsyncSession,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Compute leaderboard entries for all technicians + admins."""
    since = datetime.utcnow() - timedelta(days=days)

    techs_result = await db.execute(
        select(User).where(
            User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]),
            User.is_active == True,
        )
    )
    technicians = techs_result.scalars().all()

    entries = []
    for tech in technicians:
        m = await compute_technician_metrics(db, tech.id, since)
        m["technician_name"] = tech.full_name
        m["avatar_url"] = tech.avatar_url
        m["score"] = composite_score(m)
        entries.append(m)

    # Sort by score desc, then resolved desc
    entries.sort(key=lambda x: (x["score"], x["total_resolved"]), reverse=True)
    for i, e in enumerate(entries, start=1):
        e["rank"] = i

    return entries


# ============================================================
# TARGET PROGRESS
# ============================================================
async def compute_target_progress(
    db: AsyncSession,
    target: TechnicianTarget,
    technician_name: str,
) -> Dict[str, Any]:
    """Compare actuals against a target (sprint) for one technician."""
    m = await compute_technician_metrics(db, target.technician_id, target.start_date)

    # Progress percentages (cap 100 for display, but report raw)
    resolved_progress = (
        round((m["total_resolved"] / target.target_resolved) * 100, 1)
        if target.target_resolved else 0.0
    )
    csat_progress = (
        round((m["avg_stars"] / target.target_csat_min) * 100, 1)
        if target.target_csat_min else 0.0
    )
    time_progress = (
        round((target.target_avg_hours_max / m["avg_resolution_hours"]) * 100, 1)
        if m["avg_resolution_hours"] > 0 and target.target_avg_hours_max else 0.0
    )
    sla_progress = (
        round((m["sla_compliance_percent"] / target.target_sla_percent) * 100, 1)
        if target.target_sla_percent else 0.0
    )

    resolved_met = m["total_resolved"] >= target.target_resolved if target.target_resolved else True
    csat_met = m["avg_stars"] >= target.target_csat_min if target.target_csat_min else True
    time_met = (
        m["avg_resolution_hours"] <= target.target_avg_hours_max
        if target.target_avg_hours_max and m["avg_resolution_hours"] > 0 else True
    )
    sla_met = m["sla_compliance_percent"] >= target.target_sla_percent if target.target_sla_percent else True

    days_remaining = max(
        (target.end_date - datetime.utcnow()).days,
        0,
    )

    return {
        "technician_id": target.technician_id,
        "technician_name": technician_name,
        "target": target,
        "actual_resolved": m["total_resolved"],
        "actual_avg_stars": m["avg_stars"],
        "actual_avg_hours": m["avg_resolution_hours"],
        "actual_sla_percent": m["sla_compliance_percent"],
        "resolved_progress": resolved_progress,
        "csat_progress": csat_progress,
        "time_progress": time_progress,
        "sla_progress": sla_progress,
        "resolved_met": resolved_met,
        "csat_met": csat_met,
        "time_met": time_met,
        "sla_met": sla_met,
        "all_met": resolved_met and csat_met and time_met and sla_met,
        "days_remaining": days_remaining,
    }