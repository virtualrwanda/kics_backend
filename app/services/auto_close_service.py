"""
Auto-close tickets that have been RESOLVED for N days without confirmation.
Default: 7 days.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, and_

from ..core.database import AsyncSessionLocal
from ..models.ticket import Ticket, TicketStatus
from ..models.comment import Comment

logger = logging.getLogger(__name__)

AUTO_CLOSE_DAYS = 7


async def auto_close_tickets() -> int:
    """Close tickets resolved more than N days ago."""
    cutoff = datetime.utcnow() - timedelta(days=AUTO_CLOSE_DAYS)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Ticket).where(
                and_(
                    Ticket.status == TicketStatus.RESOLVED,
                    Ticket.resolved_at.isnot(None),
                    Ticket.resolved_at <= cutoff,
                )
            )
        )
        tickets = result.scalars().all()

        count = 0
        for ticket in tickets:
            ticket.status = TicketStatus.CLOSED
            ticket.closed_at = datetime.utcnow()

            # System comment for audit trail
            db.add(
                Comment(
                    ticket_id=ticket.id,
                    author_id=ticket.assigned_to or ticket.created_by,
                    content=(
                        f"Ticket auto-closed after {AUTO_CLOSE_DAYS} days "
                        f"of no response from the requester."
                    ),
                    is_internal=True,
                )
            )
            count += 1

        if count > 0:
            await db.commit()
            logger.info(f"✅ Auto-closed {count} tickets")

            # Fire CSAT surveys AFTER commit (each in its own task)
            for ticket in tickets:
                try:
                    asyncio.create_task(_send_csat_safely(ticket.id))
                except Exception as e:
                    logger.warning(f"CSAT scheduling failed for ticket {ticket.id}: {e}")

        return count


async def _send_csat_safely(ticket_id: int):
    """Wrapper so CSAT failures don't affect the auto-close loop."""
    try:
        from .csat_service import send_csat_survey
        await send_csat_survey(ticket_id)
    except Exception as e:
        logger.warning(f"CSAT survey failed for ticket {ticket_id}: {e}")


async def auto_close_loop(interval_hours: int = 6):
    """Run every 6 hours."""
    logger.info(f"⏰ Auto-close service started (every {interval_hours}h)")
    while True:
        try:
            await auto_close_tickets()
        except Exception as e:
            logger.exception(f"Auto-close failed: {e}")
        await asyncio.sleep(interval_hours * 3600)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(auto_close_loop())