"""
Aggregated metrics for the admin dashboard.
All queries are MySQL/MariaDB-compatible.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List

from sqlalchemy import select, func, and_, case, literal_column, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User, UserRole
from ..models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from ..models.comment import Comment
from ..models.analytics import (
    TicketSLA, Complaint, SatisfactionRating, SLAPolicy,
)
from ..models.chat import (
    Conversation, ConversationParticipant, ChatMessage,
)
from ..models.rating import TicketRating
from ..services.ws_manager import manager


# ============================================================
# 1. TOP KPIs
# ============================================================
async def compute_kpis(db: AsyncSession) -> Dict[str, Any]:
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    # Ticket counts
    total = await db.scalar(select(func.count()).select_from(Ticket)) or 0
    open_tickets = await db.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
        )
    ) or 0
    resolved_today = await db.scalar(
        select(func.count()).select_from(Ticket).where(
            and_(
                Ticket.status == TicketStatus.RESOLVED,
                Ticket.resolved_at >= today_start,
            )
        )
    ) or 0
    created_today = await db.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.created_at >= today_start
        )
    ) or 0
    created_week = await db.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.created_at >= week_start
        )
    ) or 0
    overdue = await db.scalar(
        select(func.count())
        .select_from(TicketSLA)
        .join(Ticket, Ticket.id == TicketSLA.ticket_id)
        .where(
            and_(
                TicketSLA.resolution_deadline < now,
                Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
        )
    ) or 0

    # Avg response time (first comment after ticket created)
    avg_response_seconds = await db.scalar(
        select(
            func.avg(
                func.timestampdiff(
                    literal_column("SECOND"),
                    Ticket.created_at,
                    TicketSLA.first_responded_at,
                )
            )
        )
        .select_from(Ticket)
        .join(TicketSLA, TicketSLA.ticket_id == Ticket.id)
        .where(TicketSLA.first_responded_at.isnot(None))
    ) or 0

    # Avg resolution time
    avg_resolution_seconds = await db.scalar(
        select(
            func.avg(
                func.timestampdiff(
                    literal_column("SECOND"),
                    Ticket.created_at,
                    Ticket.resolved_at,
                )
            )
        ).where(Ticket.resolved_at.isnot(None))
    ) or 0

    # Avg CSAT
    avg_csat = await db.scalar(
        select(func.avg(TicketRating.stars))
    )
    total_rated = await db.scalar(
        select(func.count()).select_from(TicketRating)
    ) or 0

    # Active users
    total_users = await db.scalar(
        select(func.count()).select_from(User).where(User.is_active == True)
    ) or 0

    # Online users (from WebSocket)
    online_users = len(manager.active)

    # Complaints unresolved
    open_complaints = await db.scalar(
        select(func.count()).select_from(Complaint).where(
            Complaint.is_resolved == False
        )
    ) or 0

    return {
        "tickets": {
            "total": total,
            "open": open_tickets,
            "created_today": created_today,
            "resolved_today": resolved_today,
            "created_week": created_week,
            "overdue": overdue,
        },
        "performance": {
            "avg_first_response_minutes": round(float(avg_response_seconds) / 60, 1),
            "avg_resolution_hours": round(float(avg_resolution_seconds) / 3600, 2),
            "avg_csat": round(float(avg_csat), 2) if avg_csat else 0.0,
            "total_rated": total_rated,
        },
        "team": {
            "total_users": total_users,
            "online_users": online_users,
            "open_complaints": open_complaints,
        },
        "generated_at": now.isoformat(),
    }


# ============================================================
# 2. CHARTS DATA
# ============================================================
async def compute_charts(db: AsyncSession, days: int = 30) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=days)

    # ---- Volume trend (daily created vs resolved) ----
    # MySQL: DATE(created_at)
    daily_created = await db.execute(
        select(
            func.date(Ticket.created_at).label("day"),
            func.count().label("count"),
        )
        .where(Ticket.created_at >= since)
        .group_by(func.date(Ticket.created_at))
        .order_by(func.date(Ticket.created_at))
    )
    created_map = {str(r.day): r.count for r in daily_created.all()}

    daily_resolved = await db.execute(
        select(
            func.date(Ticket.resolved_at).label("day"),
            func.count().label("count"),
        )
        .where(and_(Ticket.resolved_at >= since, Ticket.resolved_at.isnot(None)))
        .group_by(func.date(Ticket.resolved_at))
        .order_by(func.date(Ticket.resolved_at))
    )
    resolved_map = {str(r.day): r.count for r in daily_resolved.all()}

    # Build a complete day range
    trend = []
    for i in range(days):
        d = (since + timedelta(days=i)).date()
        key = str(d)
        trend.append({
            "date": key,
            "created": created_map.get(key, 0),
            "resolved": resolved_map.get(key, 0),
        })

    # ---- By category ----
    cat_result = await db.execute(
        select(Ticket.category, func.count())
        .where(Ticket.created_at >= since)
        .group_by(Ticket.category)
    )
    by_category = [
        {
            "category": c.value if hasattr(c, "value") else str(c),
            "count": cnt,
        }
        for c, cnt in cat_result.all()
    ]

    # ---- By priority ----
    pri_result = await db.execute(
        select(Ticket.priority, func.count())
        .where(Ticket.created_at >= since)
        .group_by(Ticket.priority)
    )
    by_priority = [
        {
            "priority": p.value if hasattr(p, "value") else str(p),
            "count": cnt,
        }
        for p, cnt in pri_result.all()
    ]

    # ---- By status ----
    status_result = await db.execute(
        select(Ticket.status, func.count())
        .where(Ticket.created_at >= since)
        .group_by(Ticket.status)
    )
    by_status = [
        {
            "status": s.value if hasattr(s, "value") else str(s),
            "count": cnt,
        }
        for s, cnt in status_result.all()
    ]

    return {
        "days": days,
        "volume_trend": trend,
        "by_category": by_category,
        "by_priority": by_priority,
        "by_status": by_status,
    }


# ============================================================
# 3. RECENT ACTIVITY FEED
# ============================================================
async def recent_activity(db: AsyncSession, limit: int = 20) -> List[Dict[str, Any]]:
    """Latest ticket + comment + assignment events."""
    events = []

    # Recent tickets
    recent_tickets = await db.execute(
        select(Ticket, User)
        .join(User, User.id == Ticket.created_by)
        .order_by(desc(Ticket.created_at))
        .limit(limit)
    )
    for ticket, creator in recent_tickets.all():
        events.append({
            "type": "ticket_created",
            "timestamp": ticket.created_at.isoformat(),
            "ticket_id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "actor": creator.full_name,
            "actor_id": creator.id,
        })

    # Recent comments
    recent_comments = await db.execute(
        select(Comment, User, Ticket)
        .join(User, User.id == Comment.author_id)
        .join(Ticket, Ticket.id == Comment.ticket_id)
        .order_by(desc(Comment.created_at))
        .limit(limit)
    )
    for comment, author, ticket in recent_comments.all():
        events.append({
            "type": "ticket_commented",
            "timestamp": comment.created_at.isoformat(),
            "ticket_id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "actor": author.full_name,
            "actor_id": author.id,
            "preview": comment.content[:120],
            "is_internal": comment.is_internal,
        })

    # Sort all by timestamp desc, take top N
    events.sort(key=lambda x: x["timestamp"], reverse=True)
    return events[:limit]


# ============================================================
# 4. NOTIFICATIONS (things needing admin attention)
# ============================================================
async def admin_notifications(db: AsyncSession) -> Dict[str, Any]:
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    # New unassigned tickets
    unassigned = await db.execute(
        select(Ticket)
        .where(
            and_(
                Ticket.status == TicketStatus.NEW,
                Ticket.assigned_to.is_(None),
            )
        )
        .order_by(desc(Ticket.created_at))
        .limit(10)
    )
    unassigned_list = [
        {
            "ticket_id": t.id,
            "ticket_number": t.ticket_number,
            "title": t.title,
            "priority": t.priority.value if hasattr(t.priority, "value") else str(t.priority),
            "created_at": t.created_at.isoformat(),
        }
        for t in unassigned.scalars().all()
    ]

    # Overdue tickets
    overdue = await db.execute(
        select(TicketSLA, Ticket)
        .join(Ticket, Ticket.id == TicketSLA.ticket_id)
        .where(
            and_(
                TicketSLA.resolution_deadline < now,
                Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            )
        )
        .order_by(TicketSLA.resolution_deadline.asc())
        .limit(10)
    )
    overdue_list = [
        {
            "ticket_id": t.id,
            "ticket_number": t.ticket_number,
            "title": t.title,
            "overdue_minutes": int((now - s.resolution_deadline).total_seconds() / 60),
        }
        for s, t in overdue.all()
    ]

    # New complaints (last 7 days)
    new_complaints = await db.execute(
        select(Complaint)
        .where(
            and_(
                Complaint.is_resolved == False,
                Complaint.created_at >= week_ago,
            )
        )
        .order_by(desc(Complaint.created_at))
        .limit(10)
    )
    complaints_list = [
        {
            "complaint_id": c.id,
            "ticket_id": c.ticket_id,
            "type": c.complaint_type.value if hasattr(c.complaint_type, "value") else str(c.complaint_type),
            "description": c.description,
            "severity": c.severity,
            "created_at": c.created_at.isoformat(),
        }
        for c in new_complaints.scalars().all()
    ]

    return {
        "unassigned_tickets": unassigned_list,
        "overdue_tickets": overdue_list,
        "new_complaints": complaints_list,
        "counts": {
            "unassigned": len(unassigned_list),
            "overdue": len(overdue_list),
            "complaints": len(complaints_list),
        },
    }


# ============================================================
# 5. CHAT OVERVIEW
# ============================================================
async def chat_overview(db: AsyncSession, limit: int = 10) -> Dict[str, Any]:
    """Most recent / active conversations across the whole system."""
    result = await db.execute(
        select(
            Conversation,
            func.count(ChatMessage.id).label("message_count"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .join(ChatMessage, ChatMessage.conversation_id == Conversation.id, isouter=True)
        .where(Conversation.is_active == True)
        .group_by(Conversation.id)
        .order_by(desc(func.max(ChatMessage.created_at)))
        .limit(limit)
    )
    convs = []
    for conv, msg_count, last_at in result.all():
        # Fetch participants
        parts = await db.execute(
            select(User.full_name, User.id)
            .join(ConversationParticipant, ConversationParticipant.user_id == User.id)
            .where(ConversationParticipant.conversation_id == conv.id)
        )
        names = [f"{r[0]}" for r in parts.all()]
        convs.append({
            "conversation_id": conv.id,
            "type": conv.type.value if hasattr(conv.type, "value") else str(conv.type),
            "name": conv.name,
            "participants": names,
            "message_count": msg_count or 0,
            "last_message_at": last_at.isoformat() if last_at else None,
        })

    total_conversations = await db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.is_active == True)
    ) or 0
    total_messages = await db.scalar(
        select(func.count()).select_from(ChatMessage)
    ) or 0
    messages_today = await db.scalar(
        select(func.count()).select_from(ChatMessage).where(
            ChatMessage.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        )
    ) or 0

    return {
        "recent_conversations": convs,
        "stats": {
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "messages_today": messages_today,
        },
    }


# ============================================================
# 6. USERS ACTIVITY OVERVIEW
# ============================================================
async def users_activity(db: AsyncSession) -> Dict[str, Any]:
    """Admins overview of user counts + online status."""
    by_role_result = await db.execute(
        select(User.role, func.count()).where(User.is_active == True).group_by(User.role)
    )
    by_role = {
        (r.value if hasattr(r, "value") else str(r)): cnt
        for r, cnt in by_role_result.all()
    }

    total_active = sum(by_role.values())
    online_ids = list(manager.active.keys())

    online_users = []
    if online_ids:
        result = await db.execute(
            select(User).where(User.id.in_(online_ids))
        )
        for u in result.scalars().all():
            online_users.append({
                "id": u.id,
                "full_name": u.full_name,
                "email": u.email,
                "role": u.role.value if hasattr(u.role, "value") else str(u.role),
                "avatar_url": u.avatar_url,
            })

    return {
        "by_role": by_role,
        "total_active": total_active,
        "online_count": len(online_users),
        "online_users": online_users,
    }