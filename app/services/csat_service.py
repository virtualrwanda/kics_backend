"""
Sends a CSAT (Customer Satisfaction) survey email after a ticket is closed.
"""

import logging
from datetime import datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import AsyncSessionLocal
from ..models.ticket import Ticket, TicketStatus
from ..models.user import User
from ..models.rating import TicketRating
from .email_service import send_email, csat_survey_email_template

logger = logging.getLogger(__name__)


async def send_csat_survey(ticket_id: int) -> bool:
    """Send a CSAT survey email for a closed ticket."""
    async with AsyncSessionLocal() as db:
        ticket = await db.get(Ticket, ticket_id)
        if not ticket:
            return False

        # Only send if closed and no rating exists yet
        if ticket.status != TicketStatus.CLOSED:
            return False

        existing = await db.execute(
            select(TicketRating).where(TicketRating.ticket_id == ticket_id)
        )
        if existing.scalar_one_or_none():
            return False  # already rated

        # Get requester
        requester = await db.get(User, ticket.created_by)
        if not requester or not requester.email:
            return False

        # Get technician
        tech = await db.get(User, ticket.assigned_to) if ticket.assigned_to else None
        tech_name = tech.full_name if tech else "our IT team"

        # Build URL
        from ..core.config import settings
        rate_url = f"{settings.FRONTEND_URL}/tickets/{ticket.id}/rate"

        html = csat_survey_email_template(
            requester.full_name,
            ticket.ticket_number or f"#{ticket.id}",
            ticket.title,
            tech_name,
            rate_url,
        )

        await send_email(
            [requester.email],
            f"How did we do? Rate ticket {ticket.ticket_number or ticket.id}",
            html,
        )
        logger.info(f"📧 CSAT survey sent for ticket {ticket.id}")
        return True