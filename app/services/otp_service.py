"""
OTP generation, hashing, and verification.
"""

import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.otp import OTPCode
from ..models.user import User

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============================================================
# CONFIG
# ============================================================
OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 5
MAX_ATTEMPTS = 3
MAX_RESEND_PER_WINDOW = 3
RESEND_WINDOW_MINUTES = 5


def _generate_otp() -> str:
    """Generate a cryptographically secure N-digit code."""
    return "".join([str(secrets.randbelow(10)) for _ in range(OTP_LENGTH)])


def _hash_otp(code: str) -> str:
    return pwd_context.hash(code)


def _verify_otp_hash(code: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(code, hashed)
    except Exception:
        return False


# ============================================================
# CREATE OTP
# ============================================================
async def create_otp(
    db: AsyncSession,
    user: User,
    purpose: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """
    Invalidate old OTPs for the same purpose and create a new one.
    Returns the plaintext code (to send via email).
    """
    # Check resend rate limit
    window_start = datetime.utcnow() - timedelta(minutes=RESEND_WINDOW_MINUTES)
    recent_result = await db.execute(
        select(OTPCode)
        .where(
            and_(
                OTPCode.user_id == user.id,
                OTPCode.purpose == purpose,
                OTPCode.created_at >= window_start,
            )
        )
        .order_by(desc(OTPCode.created_at))
    )
    recent = recent_result.scalars().all()

    if len(recent) >= MAX_RESEND_PER_WINDOW:
        logger.warning(f"Rate limit exceeded for OTP: user={user.email} purpose={purpose}")
        raise ValueError(
            f"Too many requests. Please wait {RESEND_WINDOW_MINUTES} minutes and try again."
        )

    # Invalidate old active OTPs
    for old in recent:
        if not old.is_used:
            old.is_used = True
            old.used_at = datetime.utcnow()

    # Generate new
    code = _generate_otp()
    otp = OTPCode(
        user_id=user.id,
        email=user.email,
        code_hash=_hash_otp(code),
        purpose=purpose,
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES),
        max_attempts=MAX_ATTEMPTS,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:500],
    )
    db.add(otp)
    await db.flush()

    logger.info(f"OTP created: user={user.email} purpose={purpose} expires_in={OTP_EXPIRY_MINUTES}m")
    return code


# ============================================================
# VERIFY OTP
# ============================================================
async def verify_otp(
    db: AsyncSession,
    email: str,
    purpose: str,
    code: str,
) -> tuple[bool, Optional[str], Optional[User]]:
    """
    Returns: (success, error_message, user)
    """
    # Find latest active OTP for this email + purpose
    result = await db.execute(
        select(OTPCode)
        .where(
            and_(
                OTPCode.email == email,
                OTPCode.purpose == purpose,
                OTPCode.is_used == False,
            )
        )
        .order_by(desc(OTPCode.created_at))
        .limit(1)
    )
    otp = result.scalar_one_or_none()

    if not otp:
        return False, "No active code found. Please request a new one.", None

    # Expired?
    if otp.expires_at < datetime.utcnow():
        otp.is_used = True
        otp.used_at = datetime.utcnow()
        await db.commit()
        return False, "Code has expired. Please request a new one.", None

    # Too many attempts?
    if otp.attempts >= otp.max_attempts:
        otp.is_used = True
        otp.used_at = datetime.utcnow()
        await db.commit()
        return False, "Too many failed attempts. Please request a new code.", None

    # Verify
    if not _verify_otp_hash(code, otp.code_hash):
        otp.attempts += 1
        await db.commit()
        remaining = otp.max_attempts - otp.attempts
        return False, f"Incorrect code. {remaining} attempts remaining.", None

    # Success — mark used
    otp.is_used = True
    otp.used_at = datetime.utcnow()
    await db.flush()

    # Load user
    user_result = await db.execute(select(User).where(User.id == otp.user_id))
    user = user_result.scalar_one_or_none()

    await db.commit()
    logger.info(f"OTP verified: user={email} purpose={purpose}")
    return True, None, user


# ============================================================
# CLEANUP (called periodically)
# ============================================================
async def cleanup_expired_otps(db: AsyncSession) -> int:
    """Delete OTPs older than 24 hours. Returns count deleted."""
    from sqlalchemy import delete
    cutoff = datetime.utcnow() - timedelta(hours=24)
    result = await db.execute(
        delete(OTPCode).where(OTPCode.created_at < cutoff)
    )
    await db.commit()
    return result.rowcount or 0