"""
Export reports to CSV and PDF.
"""

import csv
import io
from datetime import datetime
from typing import List, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from ..models.user import User, UserRole
from ..models.rating import TicketRating
from ..models.analytics import TicketSLA


# ============================================================
# CSV EXPORTERS
# ============================================================
def tickets_to_csv(tickets: List[Ticket], users: Dict[int, str]) -> str:
    """Export tickets to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Ticket Number", "Title", "Category", "Priority", "Status",
        "Created By", "Assigned To", "Created At", "Resolved At", "Time Spent (min)",
    ])

    for t in tickets:
        writer.writerow([
            t.ticket_number or f"#{t.id}",
            t.title,
            t.category.value if hasattr(t.category, "value") else str(t.category),
            t.priority.value if hasattr(t.priority, "value") else str(t.priority),
            t.status.value if hasattr(t.status, "value") else str(t.status),
            users.get(t.created_by, "Unknown"),
            users.get(t.assigned_to, "Unassigned") if t.assigned_to else "Unassigned",
            t.created_at.isoformat() if t.created_at else "",
            t.resolved_at.isoformat() if t.resolved_at else "",
            t.time_spent_minutes or 0,
        ])

    return output.getvalue()


async def export_tickets_csv(
    db: AsyncSession,
    days: int = 30,
    status: str = None,
) -> str:
    """Fetch tickets and convert to CSV."""
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(days=days)
    query = select(Ticket).where(Ticket.created_at >= since)
    if status:
        query = query.where(Ticket.status == status)
    query = query.order_by(Ticket.created_at.desc())

    result = await db.execute(query)
    tickets = result.scalars().all()

    # Get user names
    user_ids = {t.created_by for t in tickets} | {t.assigned_to for t in tickets if t.assigned_to}
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u.full_name for u in users_result.scalars().all()}

    return tickets_to_csv(list(tickets), users)


async def export_technician_performance_csv(db: AsyncSession, days: int = 30) -> str:
    """Export technician performance to CSV."""
    from datetime import timedelta
    from .rating_service import compute_technician_metrics, composite_score

    since = datetime.utcnow() - timedelta(days=days)

    techs_result = await db.execute(
        select(User).where(User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]))
    )
    technicians = techs_result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Technician", "Assigned", "Resolved", "Reopened",
        "Avg Hours", "Avg Stars", "SLA %", "Complaints", "Score",
    ])

    rows = []
    for tech in technicians:
        m = await compute_technician_metrics(db, tech.id, since)
        score = composite_score(m)
        rows.append({
            "name": tech.full_name,
            "assigned": m["total_assigned"],
            "resolved": m["total_resolved"],
            "reopened": m["total_reopened"],
            "hours": m["avg_resolution_hours"],
            "stars": m["avg_stars"],
            "sla": m["sla_compliance_percent"],
            "complaints": m["complaints_count"],
            "score": score,
        })

    rows.sort(key=lambda x: x["score"], reverse=True)

    for r in rows:
        writer.writerow([
            r["name"], r["assigned"], r["resolved"], r["reopened"],
            r["hours"], r["stars"], r["sla"], r["complaints"], r["score"],
        ])

    return output.getvalue()


# ============================================================
# PDF EXPORTER
# ============================================================
def tickets_to_pdf(tickets: List[Ticket], users: Dict[int, str], title: str = "Ticket Report") -> bytes:
    """Generate a simple PDF report. Uses reportlab."""
    try:
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
    except ImportError:
        raise RuntimeError("reportlab not installed. Run: pip install reportlab")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        title=title,
        author="KICS IT Help Desk",
    )

    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle(
        "CustomTitle", parent=styles["Heading1"],
        fontSize=18, textColor=colors.HexColor("#1e3a8a"), spaceAfter=12,
    )
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Total: {len(tickets)} tickets",
        styles["Normal"],
    ))
    story.append(Spacer(1, 12))

    # Table
    data = [["Ticket #", "Title", "Priority", "Status", "Created By", "Assigned", "Created"]]
    for t in tickets[:500]:  # cap for performance
        data.append([
            t.ticket_number or f"#{t.id}",
            (t.title or "")[:40],
            (t.priority.value if hasattr(t.priority, "value") else str(t.priority)).upper(),
            (t.status.value if hasattr(t.status, "value") else str(t.status)).upper(),
            users.get(t.created_by, "?"),
            users.get(t.assigned_to, "—") if t.assigned_to else "—",
            t.created_at.strftime("%Y-%m-%d") if t.created_at else "",
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ]))
    story.append(table)

    doc.build(story)
    return buffer.getvalue()


async def export_tickets_pdf(db: AsyncSession, days: int = 30) -> bytes:
    """Fetch tickets and export to PDF bytes."""
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(Ticket).where(Ticket.created_at >= since).order_by(Ticket.created_at.desc())
    )
    tickets = result.scalars().all()

    user_ids = {t.created_by for t in tickets} | {t.assigned_to for t in tickets if t.assigned_to}
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u.full_name for u in users_result.scalars().all()}

    return tickets_to_pdf(list(tickets), users, f"KICS Ticket Report — Last {days} Days")