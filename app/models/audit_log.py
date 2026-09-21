from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, JSON, ForeignKey, Index,
)
from sqlalchemy.sql import func
from ..core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(50), nullable=True, index=True)   # "ticket", "user", "chat"
    entity_id = Column(Integer, nullable=True, index=True)
    description = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    changes = Column(JSON, nullable=True)                        # before/after
    created_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_audit_user_action", "user_id", "action"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )