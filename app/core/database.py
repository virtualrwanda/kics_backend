"""
Database configuration and session management for MySQL.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
    AsyncEngine,
)
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator
import logging

from .config import settings

logger = logging.getLogger(__name__)

# Create async engine with MySQL-optimized pool settings
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,  # MySQL closes idle connections after 8h
    pool_pre_ping=True,  # Verify connection before use
    connect_args={
        "connect_timeout": 10,
        "charset": "utf8mb4",
    },
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Declarative base for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting database sessions.
    Handles commit/rollback automatically.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        from ..models import user, ticket, comment, analytics, chat, otp  # noqa
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")

async def close_db() -> None:
    """Close database connections on shutdown."""
    await engine.dispose()
    logger.info("Database connections closed")

async def init_db() -> None:
    async with engine.begin() as conn:
        # Import all models so they register with Base.metadata
        from ..models import user, ticket, comment, analytics, chat, otp, rating  # noqa
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")
async def check_db_health() -> bool:
    """
    Health check for the database.
    Returns True if the connection works, False otherwise.
    """
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False