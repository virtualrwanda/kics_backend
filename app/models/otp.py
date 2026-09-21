from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean,
    ForeignKey, Index,
)
from sqlalchemy.sql import func
from ..core.database import Base


class OTPCode(Base):
    """
    One-time passwords for 2FA login, email verification, password reset.
    Codes are hashed with bcrypt for security.
    """
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = Column(String(255), nullable=False, index=True)

    # Hashed OTP (bcrypt) — never store plaintext
    code_hash = Column(String(255), nullable=False)

    # Purpose: "login_2fa", "email_verify", "password_reset", "magic_link"
    purpose = Column(String(30), nullable=False, index=True)

    # Expiry & attempts
    expires_at = Column(DateTime, nullable=False, index=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)

    # Lifecycle
    is_used = Column(Boolean, default=False, index=True)
    used_at = Column(DateTime, nullable=True)

    # Metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_otp_user_purpose", "user_id", "purpose"),
        Index("ix_otp_email_purpose", "email", "purpose"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )