from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, Enum, Float, JSON, Index
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from ..core.database import Base


# ============================================================
# SLA POLICIES (deadlines by priority)
# ============================================================
class SLAPolicy(Base):
    __tablename__ = "sla_policies"

    id = Column(Integer, primary_key=True)
    priority = Column(String(20), unique=True, nullable=False)  # low/medium/high/urgent
    first_response_minutes = Column(Integer, nullable=False)     # e.g., 30
    resolution_minutes = Column(Integer, nullable=False)         # e.g., 480 (8 hours)
    business_hours_only = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)


# ============================================================
# TICKET SLA TRACKING (per ticket deadline info)
# ============================================================
class TicketSLA(Base):
    __tablename__ = "ticket_slas"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), unique=True, nullable=False)
    policy_id = Column(Integer, ForeignKey("sla_policies.id"), nullable=False)

    response_deadline = Column(DateTime, nullable=False)
    resolution_deadline = Column(DateTime, nullable=False)

    first_responded_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    response_met = Column(Boolean, nullable=True)
    resolution_met = Column(Boolean, nullable=True)

    is_escalated = Column(Boolean, default=False)
    escalated_at = Column(DateTime, nullable=True)
    escalation_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_sla_resolution_deadline", "resolution_deadline"),
        Index("ix_sla_escalated", "is_escalated"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


# ============================================================
# COMPLAINTS / FEEDBACK
# ============================================================
class ComplaintType(str, enum.Enum):
    REOPENED = "reopened"           # Ticket reopened because not fixed
    NEGATIVE_FEEDBACK = "negative"  # CSAT 1-2 stars
    SLA_BREACH = "sla_breach"       # Missed deadline
    STAFF_REPORTED = "staff_reported"  # Staff complained about service


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    reported_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    against_user = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # technician complained about
    complaint_type = Column(
        Enum(ComplaintType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    description = Column(Text, nullable=False)
    severity = Column(String(20), default="medium")  # low/medium/high

    # Resolution
    is_resolved = Column(Boolean, default=False, index=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)


# ============================================================
# CSAT (Customer Satisfaction) — for rankings
# ============================================================
class SatisfactionRating(Base):
    __tablename__ = "satisfaction_ratings"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), unique=True, nullable=False)
    rated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    technician_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    rating = Column(Integer, nullable=False)  # 1-5 stars
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_csat_technician", "technician_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )