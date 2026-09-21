import asyncio
import logging
from datetime import datetime, timedelta

from ..core.database import AsyncSessionLocal
from .otp_service import cleanup_expired_otps

logger = logging.getLogger(__name__)


async def cleanup_loop(interval_hours: int = 6):
    """Periodically delete expired OTPs."""
    logger.info("🧹 Cleanup service started")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                count = await cleanup_expired_otps(db)
                logger.info(f"🧹 Cleaned up {count} expired OTPs")
        except Exception as e:
            logger.exception(f"Cleanup failed: {e}")
        await asyncio.sleep(interval_hours * 3600)