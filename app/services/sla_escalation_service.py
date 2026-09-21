"""
Background service that scans for overdue tickets and escalates them.
Runs every N minutes.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import AsyncSessionLocal
from ..models.ticket import Ticket, TicketStatus
from ..models.user import User, UserRole
from ..models.analytics import TicketSLA, Complaint, ComplaintType
from .ws_manager import manager

logger = logging.getLogger(__name__)


# ============================================================
# ESCALATE A SINGLE TICKET
# ============================================================
async def _escalate_ticket(db: AsyncSession, sla: TicketSLA, ticket: Ticket):
    """Mark the SLA as escalated, notify admin + technician."""
    if sla.is_escalated:
        return  # already done

    sla.is_escalated = True
    sla.escalated_at = datetime.utcnow()
    sla.escalation_reason = (
        f"Resolution deadline passed at {sla.resolution_deadline.isoformat()}"
    )

    # Create a complaint record for tracking
    complaint = Complaint(
        ticket_id=ticket.id,
        against_user=ticket.assigned_to,
        complaint_type=ComplaintType.SLA_BREACH,
        description=f"SLA breach: {sla.escalation_reason}",
        severity="high",
    )
    db.add(complaint)
    await db.flush()

    # Notify admins + assigned technician
    notify_ids = set()
    if ticket.assigned_to:
        notify_ids.add(ticket.assigned_to)

    admins = await db.execute(
        select(User.id).where(
            User.role == UserRole.ADMIN,
            User.is_active == True,
        )
    )
    for row in admins.all():
        notify_ids.add(row[0])

    payload = {
        "event": "sla_breached",
        "ticket_id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "title": ticket.title,
        "priority": ticket.priority.value if hasattr(ticket.priority, "value") else str(ticket.priority),
        "deadline": sla.resolution_deadline.isoformat(),
        "overdue_minutes": int(
            (datetime.utcnow() - sla.resolution_deadline).total_seconds() / 60
        ),
    }

    try:
        await manager.broadcast(list(notify_ids), payload)
    except Exception as e:
        logger.warning(f"WS broadcast failed for SLA breach: {e}")

    logger.warning(
        f"🚨 SLA BREACH: Ticket {ticket.ticket_number} — "
        f"overdue since {sla.resolution_deadline.isoformat()}"
    )


# ============================================================
# MAIN SCAN
# ============================================================
async def scan_and_escalate() -> int:
    """Find overdue tickets and escalate them. Returns count escalated."""
    now = datetime.utcnow()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TicketSLA, Ticket)
            .join(Ticket, Ticket.id == TicketSLA.ticket_id)
            .where(
                and_(
                    TicketSLA.resolution_deadline < now,
                    TicketSLA.is_escalated == False,
                    Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
                )
            )
        )
        rows = result.all()

        count = 0
        for sla, ticket in rows:
            try:
                await _escalate_ticket(db, sla, ticket)
                count += 1
            except Exception as e:
                logger.exception(f"Failed to escalate ticket {ticket.id}: {e}")

        if count > 0:
            await db.commit()
            logger.info(f"🚨 Escalated {count} SLA breaches")
        return count


# ============================================================
# BACKGROUND LOOP
# ============================================================
async def escalation_loop(interval_minutes: int = 5):
    """Continuously scan for SLA breaches."""
    logger.info(f"⏰ SLA escalation service started (every {interval_minutes}m)")
    while True:
        try:
            await scan_and_escalate()
        except Exception as e:
            logger.exception(f"Escalation scan failed: {e}")
        await asyncio.sleep(interval_minutes * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(escalation_loop())