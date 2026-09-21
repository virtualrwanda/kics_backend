from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.sql import func
from ..core.database import Base


class TicketRating(Base):
    """
    A rating given by a staff/admin user to a technician for a completed ticket.
    One rating per ticket per rater.
    """
    __tablename__ = "ticket_ratings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    technician_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rater_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 1–5 stars
    stars = Column(Integer, nullable=False)

    # Dimensions (optional but useful for leaderboards)
    speed_rating = Column(Integer, nullable=True)          # 1–5
    quality_rating = Column(Integer, nullable=True)        # 1–5
    communication_rating = Column(Integer, nullable=True)  # 1–5
    professionalism_rating = Column(Integer, nullable=True)  # 1–5

    comment = Column(Text, nullable=True)

    # Rater's role at time of rating (for auditing)
    rater_role = Column(String(20), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        UniqueConstraint("ticket_id", "rater_id", name="uq_rating_per_rater_per_ticket"),
        Index("ix_rating_tech_created", "technician_id", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class TechnicianTarget(Base):
    """
    Admin-defined KPI target for a technician.
    Can be assigned for a specific period (sprint) or ongoing.
    """
    __tablename__ = "technician_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)

    technician_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    set_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Period (sprint)
    name = Column(String(100), nullable=False)              # e.g. "Q1 2026 Sprint"
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)

    # Targets
    target_resolved = Column(Integer, default=0)            # tickets to resolve
    target_csat_min = Column(Integer, default=0)            # min stars (1-5)
    target_avg_hours_max = Column(Integer, default=0)       # max avg resolution hours
    target_sla_percent = Column(Integer, default=0)         # min SLA compliance %

    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    __table_args__ = (
        Index("ix_target_tech_active", "technician_id", "is_active"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )