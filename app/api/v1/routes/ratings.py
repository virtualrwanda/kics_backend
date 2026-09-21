from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from datetime import datetime, timedelta

from ....core.database import get_db
from ....core.dependencies import get_current_user, require_admin, require_technician
from ....models.user import User, UserRole
from ....models.ticket import Ticket, TicketStatus
from ....models.rating import TicketRating, TechnicianTarget
from ....schemas.rating import (
    TicketRatingCreate, TicketRatingResponse,
    MyPerformance, LeaderboardEntry,
    TechnicianTargetCreate, TechnicianTargetUpdate,
    TechnicianTargetResponse, TechnicianProgress,
)
from ....services import rating_service
from ....services.ws_manager import manager

router = APIRouter(tags=["Ratings & Performance"])


# ============================================================
# RATE A TICKET
# ============================================================
@router.post(
    "/tickets/{ticket_id}/rate",
    response_model=TicketRatingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rate_ticket(
    ticket_id: int,
    payload: TicketRatingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rate a technician after a ticket is resolved/closed."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Must be resolved or closed
    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise HTTPException(
            status_code=400,
            detail="You can only rate tickets that are resolved or closed",
        )

    # Must be the ticket's creator or an admin
    if ticket.created_by != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Only the ticket creator or an admin can rate",
        )

    # Must have a technician assigned
    if not ticket.assigned_to:
        raise HTTPException(status_code=400, detail="Ticket has no assigned technician")

    # Prevent duplicate rating by same user
    existing = await db.execute(
        select(TicketRating).where(
            and_(
                TicketRating.ticket_id == ticket_id,
                TicketRating.rater_id == current_user.id,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="You have already rated this ticket",
        )

    rating = TicketRating(
        ticket_id=ticket_id,
        technician_id=ticket.assigned_to,
        rater_id=current_user.id,
        rater_role=current_user.role.value,
        stars=payload.stars,
        comment=payload.comment,
        speed_rating=payload.speed_rating,
        quality_rating=payload.quality_rating,
        communication_rating=payload.communication_rating,
        professionalism_rating=payload.professionalism_rating,
    )
    db.add(rating)
    await db.commit()
    await db.refresh(rating)

    # Notify technician via WebSocket
    try:
        await manager.send_to_user(
            ticket.assigned_to,
            {
                "event": "ticket_rated",
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "stars": payload.stars,
                "rater_name": current_user.full_name,
                "comment": payload.comment,
            },
        )
    except Exception:
        pass

    # Enrich response
    tech = await db.get(User, ticket.assigned_to)
    rater = await db.get(User, current_user.id)
    response = TicketRatingResponse.model_validate(rating)
    response.technician_name = tech.full_name if tech else None
    response.rater_name = rater.full_name if rater else None
    return response


# ============================================================
# GET TICKET RATING(S)
# ============================================================
@router.get("/tickets/{ticket_id}/rating", response_model=List[TicketRatingResponse])
async def get_ticket_ratings(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """View all ratings for a ticket."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Access control
    if (
        current_user.role == UserRole.STAFF
        and ticket.created_by != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(TicketRating).where(TicketRating.ticket_id == ticket_id)
    )
    ratings = result.scalars().all()

    out = []
    for r in ratings:
        tech = await db.get(User, r.technician_id)
        rater = await db.get(User, r.rater_id)
        item = TicketRatingResponse.model_validate(r)
        item.technician_name = tech.full_name if tech else None
        item.rater_name = rater.full_name if rater else None
        out.append(item)
    return out


# ============================================================
# MY PERFORMANCE (technician self-view)
# ============================================================
@router.get("/me/performance", response_model=MyPerformance)
async def my_performance(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    """Get my own performance metrics."""
    since = datetime.utcnow() - timedelta(days=days)
    m = await rating_service.compute_technician_metrics(db, current_user.id, since)

    # Rank
    leaderboard = await rating_service.compute_leaderboard(db, days)
    rank = next(
        (e["rank"] for e in leaderboard if e["technician_id"] == current_user.id),
        None,
    )

    # Active target
    target_result = await db.execute(
        select(TechnicianTarget).where(
            and_(
                TechnicianTarget.technician_id == current_user.id,
                TechnicianTarget.is_active == True,
            )
        ).order_by(TechnicianTarget.end_date.desc()).limit(1)
    )
    active_target = target_result.scalar_one_or_none()
    target_response = None
    if active_target:
        target_response = TechnicianTargetResponse.model_validate(active_target)
        target_response.technician_name = current_user.full_name

    return MyPerformance(
        technician_id=current_user.id,
        technician_name=current_user.full_name,
        total_rated=m["total_rated"],
        avg_stars=m["avg_stars"],
        avg_speed=m["avg_speed"],
        avg_quality=m["avg_quality"],
        avg_communication=m["avg_communication"],
        avg_professionalism=m["avg_professionalism"],
        total_resolved=m["total_resolved"],
        avg_resolution_hours=m["avg_resolution_hours"],
        sla_compliance_percent=m["sla_compliance_percent"],
        rank=rank,
        active_target=target_response,
    )


# ============================================================
# LEADERBOARD (public to all authenticated users)
# ============================================================
@router.get("/leaderboard", response_model=List[LeaderboardEntry])
async def leaderboard(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Leaderboard of technicians, ranked by composite score."""
    entries = await rating_service.compute_leaderboard(db, days)
    return [
        LeaderboardEntry(
            rank=e["rank"],
            technician_id=e["technician_id"],
            technician_name=e["technician_name"],
            avatar_url=e.get("avatar_url"),
            total_resolved=e["total_resolved"],
            total_rated=e["total_rated"],
            avg_stars=e["avg_stars"],
            avg_resolution_hours=e["avg_resolution_hours"],
            sla_compliance_percent=e["sla_compliance_percent"],
            complaints_count=e["complaints_count"],
            score=e["score"],
        )
        for e in entries[:limit]
    ]


# ============================================================
# ADMIN: SET TARGET / SPRINT FOR A TECHNICIAN
# ============================================================
@router.post(
    "/admin/technicians/{technician_id}/target",
    response_model=TechnicianTargetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def set_technician_target(
    technician_id: int,
    payload: TechnicianTargetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Assign a KPI target / sprint to a technician."""
    tech = await db.get(User, technician_id)
    if not tech or tech.role not in (UserRole.TECHNICIAN, UserRole.ADMIN):
        raise HTTPException(status_code=404, detail="Technician not found")

    if payload.start_date >= payload.end_date:
        raise HTTPException(status_code=400, detail="end_date must be after start_date")

    # Deactivate any existing active targets for this technician
    existing = await db.execute(
        select(TechnicianTarget).where(
            and_(
                TechnicianTarget.technician_id == technician_id,
                TechnicianTarget.is_active == True,
            )
        )
    )
    for old in existing.scalars().all():
        old.is_active = False

    target = TechnicianTarget(
        technician_id=technician_id,
        set_by=current_user.id,
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        target_resolved=payload.target_resolved,
        target_csat_min=payload.target_csat_min,
        target_avg_hours_max=payload.target_avg_hours_max,
        target_sla_percent=payload.target_sla_percent,
        notes=payload.notes,
        is_active=True,
    )
    db.add(target)
    await db.commit()
    await db.refresh(target)

    # Notify technician
    try:
        await manager.send_to_user(
            technician_id,
            {
                "event": "target_assigned",
                "target_id": target.id,
                "name": target.name,
                "target_resolved": target.target_resolved,
                "target_csat_min": target.target_csat_min,
                "end_date": target.end_date.isoformat(),
            },
        )
    except Exception:
        pass

    response = TechnicianTargetResponse.model_validate(target)
    response.technician_name = tech.full_name
    response.set_by_name = current_user.full_name
    return response


# ============================================================
# ADMIN: UPDATE TARGET
# ============================================================
@router.put(
    "/admin/technicians/{technician_id}/target/{target_id}",
    response_model=TechnicianTargetResponse,
)
async def update_technician_target(
    technician_id: int,
    target_id: int,
    payload: TechnicianTargetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Update an existing target."""
    target = await db.get(TechnicianTarget, target_id)
    if not target or target.technician_id != technician_id:
        raise HTTPException(status_code=404, detail="Target not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, key, value)

    await db.commit()
    await db.refresh(target)

    tech = await db.get(User, technician_id)
    response = TechnicianTargetResponse.model_validate(target)
    response.technician_name = tech.full_name if tech else None
    return response


# ============================================================
# ADMIN: LIST TARGETS FOR A TECHNICIAN
# ============================================================
@router.get(
    "/admin/technicians/{technician_id}/targets",
    response_model=List[TechnicianTargetResponse],
)
async def list_technician_targets(
    technician_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(
        select(TechnicianTarget)
        .where(TechnicianTarget.technician_id == technician_id)
        .order_by(TechnicianTarget.created_at.desc())
    )
    targets = result.scalars().all()

    tech = await db.get(User, technician_id)
    out = []
    for t in targets:
        item = TechnicianTargetResponse.model_validate(t)
        item.technician_name = tech.full_name if tech else None
        out.append(item)
    return out


# ============================================================
# ADMIN: VIEW PROGRESS AGAINST ACTIVE TARGET
# ============================================================
@router.get(
    "/admin/technicians/{technician_id}/progress",
    response_model=TechnicianProgress,
)
async def technician_progress(
    technician_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Show actual vs target for the technician's active sprint."""
    tech = await db.get(User, technician_id)
    if not tech:
        raise HTTPException(status_code=404, detail="Technician not found")

    target_result = await db.execute(
        select(TechnicianTarget).where(
            and_(
                TechnicianTarget.technician_id == technician_id,
                TechnicianTarget.is_active == True,
            )
        ).limit(1)
    )
    target = target_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="No active target for this technician")

    data = await rating_service.compute_target_progress(db, target, tech.full_name)

    response = TechnicianProgress(
        technician_id=data["technician_id"],
        technician_name=data["technician_name"],
        target=TechnicianTargetResponse.model_validate(data["target"]),
        actual_resolved=data["actual_resolved"],
        actual_avg_stars=data["actual_avg_stars"],
        actual_avg_hours=data["actual_avg_hours"],
        actual_sla_percent=data["actual_sla_percent"],
        resolved_progress=data["resolved_progress"],
        csat_progress=data["csat_progress"],
        time_progress=data["time_progress"],
        sla_progress=data["sla_progress"],
        resolved_met=data["resolved_met"],
        csat_met=data["csat_met"],
        time_met=data["time_met"],
        sla_met=data["sla_met"],
        all_met=data["all_met"],
        days_remaining=data["days_remaining"],
    )
    response.target.technician_name = tech.full_name
    return response