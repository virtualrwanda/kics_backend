from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, Boolean, Index, CheckConstraint, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
import uuid
from ..core.database import Base


class TicketPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketStatus(str, enum.Enum):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


class TicketCategory(str, enum.Enum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    NETWORK = "network"
    ACCOUNT = "account"
    PRINTER = "printer"
    EMAIL = "email"
    OTHER = "other"


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    uuid = Column(String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False, index=True)
    ticket_number = Column(String(20), unique=True, index=True, nullable=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(Enum(TicketCategory, values_callable=lambda x: [e.value for e in x]), default=TicketCategory.OTHER, nullable=False, index=True)
    priority = Column(Enum(TicketPriority, values_callable=lambda x: [e.value for e in x]), default=TicketPriority.MEDIUM, nullable=False, index=True)
    status = Column(Enum(TicketStatus, values_callable=lambda x: [e.value for e in x]), default=TicketStatus.NEW, nullable=False, index=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_to = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    is_resolved = Column(Boolean, default=False, index=True)
    resolution_notes = Column(Text, nullable=True)
    time_spent_minutes = Column(Integer, default=0)
    tags = Column(JSON, default=list)
    extra_metadata = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, onupdate=func.now())
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)

    creator = relationship("User", foreign_keys=[created_by], back_populates="created_tickets")
    assignee = relationship("User", foreign_keys=[assigned_to], back_populates="assigned_tickets")
    comments = relationship("Comment", back_populates="ticket", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("time_spent_minutes >= 0", name="check_time_positive"),
        Index("ix_tickets_status_priority", "status", "priority"),
        Index("ix_tickets_assigned_status", "assigned_to", "status"),
        Index("ix_tickets_created_by_status", "created_by", "status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
