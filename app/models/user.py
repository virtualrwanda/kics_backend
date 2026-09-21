from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from ..core.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    TECHNICIAN = "technician"
    STAFF = "staff"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]),
        default=UserRole.STAFF,
        nullable=False,
        index=True,
    )
    department = Column(String(100))
    phone = Column(String(20))
    avatar_url = Column(String(500), nullable=True)   # ← NEW
    is_active = Column(Boolean, default=True, index=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    created_tickets = relationship("Ticket", foreign_keys="Ticket.created_by", back_populates="creator")
    assigned_tickets = relationship("Ticket", foreign_keys="Ticket.assigned_to", back_populates="assignee")
    comments = relationship("Comment", back_populates="author")

    __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)