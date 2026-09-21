from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from typing import Optional, List
from datetime import datetime, timedelta

from ....core.database import get_db
from ....core.dependencies import (
    get_current_user,
    require_technician,
    require_admin,
)
from ....models.user import User, UserRole
from ....models.ticket import (
    Ticket, TicketStatus, TicketPriority, TicketCategory,
)
from ....models.comment import Comment
from ....models.analytics import (
    SLAPolicy, TicketSLA, Complaint, ComplaintType,
)
from ....schemas.ticket import (
    TicketCreate, TicketUpdate, TicketResponse,
)
from ....schemas.comment import CommentCreate, CommentResponse
from ....services.notify import notify_ticket_event

router = APIRouter(prefix="/tickets", tags=["Tickets"])


# ============================================================
# INTERNAL HELPERS
# ============================================================
async def _get_or_create_sla(
    db: AsyncSession,
    ticket: Ticket,
) -> Optional[TicketSLA]:
    """
    Look up the SLA policy for the ticket's priority,
    then create a TicketSLA row with computed deadlines.
    """
    priority_value = (
        ticket.priority.value
        if hasattr(ticket.priority, "value")
        else str(ticket.priority)
    )
    policy_result = await db.execute(
        select(SLAPolicy).where(
            SLAPolicy.priority == priority_value,
            SLAPolicy.is_active == True,
        )
    )
    policy = policy_result.scalar_one_or_none()
    if not policy:
        return None

    now = datetime.utcnow()
    sla = TicketSLA(
        ticket_id=ticket.id,
        policy_id=policy.id,
        response_deadline=now + timedelta(minutes=policy.first_response_minutes),
        resolution_deadline=now + timedelta(minutes=policy.resolution_minutes),
    )
    db.add(sla)
    await db.flush()
    return sla


async def _mark_first_response(
    db: AsyncSession,
    ticket_id: int,
    responded_at: Optional[datetime] = None,
):
    """Mark the first response on a ticket's SLA row."""
    responded_at = responded_at or datetime.utcnow()
    result = await db.execute(
        select(TicketSLA).where(TicketSLA.ticket_id == ticket_id)
    )
    sla = result.scalar_one_or_none()
    if sla and sla.first_responded_at is None:
        sla.first_responded_at = responded_at
        sla.response_met = responded_at <= sla.response_deadline
        await db.flush()


async def _mark_resolved(
    db: AsyncSession,
    ticket_id: int,
    resolved_at: Optional[datetime] = None,
):
    """Mark resolution on the SLA row."""
    resolved_at = resolved_at or datetime.utcnow()
    result = await db.execute(
        select(TicketSLA).where(TicketSLA.ticket_id == ticket_id)
    )
    sla = result.scalar_one_or_none()
    if sla:
        sla.resolved_at = resolved_at
        sla.resolution_met = resolved_at <= sla.resolution_deadline
        await db.flush()


async def _assert_can_view(
    db: AsyncSession,
    ticket: Ticket,
    user: User,
):
    """Raise 403 if user cannot view this ticket."""
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.STAFF:
        if ticket.created_by != user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        return
    if user.role == UserRole.TECHNICIAN:
        if ticket.assigned_to is not None and ticket.assigned_to != user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        return


async def _assert_can_edit(
    db: AsyncSession,
    ticket: Ticket,
    user: User,
):
    """Raise 403 if user cannot edit."""
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.TECHNICIAN:
        if ticket.assigned_to is not None and ticket.assigned_to != user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        return
    if user.role == UserRole.STAFF:
        if ticket.created_by != user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        return


# ============================================================
# CREATE TICKET
# ============================================================
@router.post("/", response_model=TicketResponse, status_code=201)
async def create_ticket(
    ticket_data: TicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new support ticket."""
    new_ticket = Ticket(
        title=ticket_data.title,
        description=ticket_data.description,
        category=ticket_data.category,
        priority=ticket_data.priority,
        created_by=current_user.id,
    )
    db.add(new_ticket)
    await db.commit()
    await db.refresh(new_ticket)

    # Auto-create SLA tracking
    await _get_or_create_sla(db, new_ticket)
    await db.commit()
    await db.refresh(new_ticket)

    # Notify admins + technicians
    await notify_ticket_event(
        event="ticket_created",
        ticket_id=new_ticket.id,
        ticket_number=new_ticket.ticket_number,
        title=new_ticket.title,
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        extra={
            "priority": new_ticket.priority.value if hasattr(new_ticket.priority, "value") else str(new_ticket.priority),
            "category": new_ticket.category.value if hasattr(new_ticket.category, "value") else str(new_ticket.category),
        },
    )

    return new_ticket


# ============================================================
# LIST TICKETS (with filters)
# ============================================================
@router.get("/", response_model=List[TicketResponse])
async def get_tickets(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: Optional[TicketStatus] = Query(None, alias="status"),
    priority: Optional[TicketPriority] = None,
    category: Optional[TicketCategory] = None,
    assigned_to: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get tickets with filters (role-aware)."""
    query = select(Ticket)

    # Filters
    if status_filter:
        query = query.where(Ticket.status == status_filter)
    if priority:
        query = query.where(Ticket.priority == priority)
    if category:
        query = query.where(Ticket.category == category)
    if assigned_to:
        query = query.where(Ticket.assigned_to == assigned_to)
    if search:
        query = query.where(
            or_(
                Ticket.title.like(f"%{search}%"),
                Ticket.description.like(f"%{search}%"),
                Ticket.ticket_number.like(f"%{search}%"),
            )
        )

    # Role-based visibility
    if current_user.role == UserRole.STAFF:
        query = query.where(Ticket.created_by == current_user.id)
    elif current_user.role == UserRole.TECHNICIAN:
        query = query.where(
            or_(
                Ticket.assigned_to == current_user.id,
                Ticket.assigned_to.is_(None),
            )
        )

    query = query.order_by(Ticket.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# ============================================================
# GET TICKET BY ID
# ============================================================
@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a ticket by ID (role-aware)."""
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    await _assert_can_view(db, ticket, current_user)
    return ticket


# ============================================================
# UPDATE TICKET
# ============================================================
@router.put("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: int,
    update_data: TicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a ticket (status, priority, assignment, etc.)."""
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    await _assert_can_edit(db, ticket, current_user)

    update_dict = update_data.model_dump(exclude_unset=True)

    # Handle status transitions
    if "status" in update_dict:
        new_status = update_dict["status"]
        if isinstance(new_status, str):
            new_status = TicketStatus(new_status)

        # Staff cannot close/resolve directly — only comment
        if (
            current_user.role == UserRole.STAFF
            and new_status in (TicketStatus.RESOLVED, TicketStatus.CLOSED)
        ):
            raise HTTPException(
                status_code=403,
                detail="Only technicians can resolve or close tickets",
            )

        old_status = ticket.status

        if new_status == TicketStatus.RESOLVED:
            ticket.resolved_at = datetime.utcnow()
            ticket.is_resolved = True
            await _mark_resolved(db, ticket.id, ticket.resolved_at)

        elif new_status == TicketStatus.CLOSED:
            ticket.closed_at = datetime.utcnow()

        elif new_status == TicketStatus.REOPENED:
            # Reopen: create a complaint for tracking
            ticket.is_resolved = False
            ticket.resolved_at = None

            complaint = Complaint(
                ticket_id=ticket.id,
                reported_by=current_user.id,
                against_user=ticket.assigned_to,
                complaint_type=ComplaintType.REOPENED,
                description=f"Ticket reopened by {current_user.full_name}",
                severity="medium",
            )
            db.add(complaint)

    # Apply the rest of the updates
    for key, value in update_dict.items():
        setattr(ticket, key, value)

    ticket.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ticket)

    # Notify
    event_name = "ticket_updated"
    if "status" in update_dict:
        s = update_dict["status"]
        s_val = s.value if hasattr(s, "value") else str(s)
        event_name = f"ticket_{s_val}"

    audience = list({ticket.created_by, ticket.assigned_to} - {None})
    await notify_ticket_event(
        event=event_name,
        ticket_id=ticket.id,
        ticket_number=ticket.ticket_number,
        title=ticket.title,
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        extra={"changes": list(update_dict.keys())},
        audience=audience,
    )

    return ticket


# ============================================================
# DELETE TICKET
# ============================================================
@router.delete("/{ticket_id}")
async def delete_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Delete a ticket (Admin only)."""
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    await db.delete(ticket)
    await db.commit()
    return {"message": "Ticket deleted successfully"}


# ============================================================
# ASSIGN TO TECHNICIAN
# ============================================================
@router.post("/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: int,
    technician_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    """Assign a ticket to a technician."""
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    tech_result = await db.execute(
        select(User).where(
            User.id == technician_id,
            User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]),
            User.is_active == True,
        )
    )
    technician = tech_result.scalar_one_or_none()
    if not technician:
        raise HTTPException(status_code=404, detail="Technician not found")

    ticket.assigned_to = technician_id
    ticket.status = TicketStatus.ASSIGNED
    ticket.updated_at = datetime.utcnow()
    await db.commit()

    # Notify
    await notify_ticket_event(
        event="ticket_assigned",
        ticket_id=ticket.id,
        ticket_number=ticket.ticket_number,
        title=ticket.title,
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        extra={"assigned_to_name": technician.full_name},
        audience=[ticket.created_by, technician_id],
    )

    return {"message": f"Ticket assigned to {technician.full_name}"}


# ============================================================
# ADD COMMENT
# ============================================================
@router.post("/{ticket_id}/comments", response_model=CommentResponse)
async def add_comment(
    ticket_id: int,
    comment_data: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a comment (public or internal)."""
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    await _assert_can_view(db, ticket, current_user)

    if comment_data.is_internal and current_user.role == UserRole.STAFF:
        raise HTTPException(status_code=403, detail="Staff cannot add internal notes")

    # Auto-reopen if staff comments on a resolved/closed ticket
    if (
        current_user.role == UserRole.STAFF
        and ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED)
    ):
        ticket.status = TicketStatus.REOPENED
        ticket.is_resolved = False
        ticket.resolved_at = None

        complaint = Complaint(
            ticket_id=ticket.id,
            reported_by=current_user.id,
            against_user=ticket.assigned_to,
            complaint_type=ComplaintType.REOPENED,
            description=f"Ticket auto-reopened by staff comment: {comment_data.content[:150]}",
            severity="medium",
        )
        db.add(complaint)
        await db.flush()

    # Create comment
    new_comment = Comment(
        ticket_id=ticket_id,
        author_id=current_user.id,
        content=comment_data.content,
        is_internal=comment_data.is_internal,
    )
    db.add(new_comment)

    # If technician comment (public) and no first_response yet, mark it
    if current_user.role in (UserRole.TECHNICIAN, UserRole.ADMIN) and not comment_data.is_internal:
        await _mark_first_response(db, ticket_id)

    await db.commit()
    await db.refresh(new_comment)
    # After `await db.refresh(ticket)`:
    if "status" in update_dict and update_dict["status"] == TicketStatus.CLOSED:
        from ....services.csat_service import send_csat_survey
        import asyncio
        asyncio.create_task(send_csat_survey(ticket.id))
    # Notify
    audience = list({ticket.created_by, ticket.assigned_to} - {None})
    await notify_ticket_event(
        event="ticket_commented",
        ticket_id=ticket.id,
        ticket_number=ticket.ticket_number,
        title=ticket.title,
        actor_id=current_user.id,
        actor_name=current_user.full_name,
        extra={
            "comment_preview": comment_data.content[:120],
            "is_internal": comment_data.is_internal,
            "comment_id": new_comment.id,
        },
        audience=audience,
    )

    return new_comment


# ============================================================
# LIST COMMENTS
# ============================================================
@router.get("/{ticket_id}/comments", response_model=List[CommentResponse])
async def get_comments(
    ticket_id: int,
    include_internal: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all comments for a ticket."""
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    await _assert_can_view(db, ticket, current_user)

    query = select(Comment).where(Comment.ticket_id == ticket_id)

    # Staff can never see internal notes
    if current_user.role == UserRole.STAFF:
        query = query.where(Comment.is_internal == False)
    elif not include_internal:
        query = query.where(Comment.is_internal == False)

    query = query.order_by(Comment.created_at.asc())
    result = await db.execute(query)
    return result.scalars().all()