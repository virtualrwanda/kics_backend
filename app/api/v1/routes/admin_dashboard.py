from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ....core.database import get_db
from ....core.dependencies import require_admin
from ....models.user import User
from ....services import admin_dashboard_service

router = APIRouter(prefix="/admin/dashboard", tags=["Admin Dashboard"])


@router.get("/kpis")
async def get_kpis(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Top KPI tiles for the admin dashboard."""
    return await admin_dashboard_service.compute_kpis(db)


@router.get("/charts")
async def get_charts(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Chart data — volume trend, by category, priority, status."""
    return await admin_dashboard_service.compute_charts(db, days)


@router.get("/activity")
async def get_recent_activity(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Recent activity feed."""
    return await admin_dashboard_service.recent_activity(db, limit)


@router.get("/notifications")
async def get_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Things that need admin attention."""
    return await admin_dashboard_service.admin_notifications(db)


@router.get("/chats")
async def get_chat_overview(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Overview of chats across the system."""
    return await admin_dashboard_service.chat_overview(db, limit)


@router.get("/users")
async def get_users_activity(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """User counts and online users."""
    return await admin_dashboard_service.users_activity(db)


@router.get("/leaderboard")
async def get_admin_leaderboard(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Technician leaderboard for admin view (includes score)."""
    from ....services import rating_service
    entries = await rating_service.compute_leaderboard(db, days)
    return entries