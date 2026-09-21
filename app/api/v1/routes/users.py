from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    File,
    UploadFile,
    Query,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import List, Optional

from ....core.database import get_db
from ....core.dependencies import (
    require_admin,
    get_current_user,
    get_current_active_user,
)
from ....core.security import get_password_hash
from ....models.user import User, UserRole
from ....models.ticket import Ticket, TicketStatus
from ....schemas.user import UserResponse, UserUpdate, UserCreate
from ....schemas.ticket import TicketResponse
from ....services import file_service

router = APIRouter(prefix="/users", tags=["Users"])


# ============================================================
# MY PROFILE
# ============================================================
@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_active_user),
):
    """Get my own profile."""
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_my_profile(
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update my own profile (name, department, phone)."""
    # Only allow safe fields for self-update
    allowed = {"full_name", "department", "phone"}
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key in allowed:
            setattr(current_user, key, value)

    await db.commit()
    await db.refresh(current_user)
    return current_user


# ============================================================
# MY AVATAR
# ============================================================
@router.post("/me/avatar", response_model=UserResponse)
async def upload_my_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Upload or replace my profile picture."""
    # Delete old avatar if exists
    if current_user.avatar_url:
        file_service.delete_file(current_user.avatar_url)

    # Save new
    info = await file_service.save_avatar(file)

    current_user.avatar_url = info["url"]
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.delete("/me/avatar", response_model=UserResponse)
async def delete_my_avatar(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Remove my profile picture."""
    if current_user.avatar_url:
        file_service.delete_file(current_user.avatar_url)
        current_user.avatar_url = None
        await db.commit()
        await db.refresh(current_user)
    return current_user


# ============================================================
# USER DIRECTORY (for chat picker — any authenticated user)
# ============================================================
@router.get("/directory", response_model=List[UserResponse])
async def get_user_directory(
    search: Optional[str] = None,
    role: Optional[UserRole] = None,
    department: Optional[str] = None,
    exclude_self: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    List all active users so any staff member can pick someone to chat with.
    """
    query = select(User).where(User.is_active == True)

    if exclude_self:
        query = query.where(User.id != current_user.id)
    if role:
        query = query.where(User.role == role)
    if department:
        query = query.where(User.department == department)
    if search:
        query = query.where(
            or_(
                User.full_name.like(f"%{search}%"),
                User.email.like(f"%{search}%"),
                User.department.like(f"%{search}%"),
            )
        )

    query = query.order_by(User.role, User.full_name)
    result = await db.execute(query)
    return result.scalars().all()


# ============================================================
# TECHNICIANS (for assignment dropdowns)
# ============================================================
@router.get("/technicians", response_model=List[UserResponse])
async def get_technicians(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List all technicians and admins (for ticket assignment)."""
    result = await db.execute(
        select(User)
        .where(
            User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]),
            User.is_active == True,
        )
        .order_by(User.full_name)
    )
    return result.scalars().all()


# ============================================================
# ADMIN: LIST ALL USERS
# ============================================================
@router.get("/", response_model=List[UserResponse])
async def get_users(
    role: Optional[UserRole] = None,
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Get all users (Admin only)."""
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if department:
        query = query.where(User.department == department)
    if is_active is not None:
        query = query.where(User.is_active == is_active)

    result = await db.execute(query.order_by(User.full_name))
    return result.scalars().all()


# ============================================================
# ADMIN: CREATE USER
# ============================================================
@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Create a new user (Admin only)."""
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        role=payload.role,
        department=payload.department,
        phone=payload.phone,
        is_active=True,
        is_verified=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


# ============================================================
# GET USER BY ID (any authenticated user)
# ============================================================
@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get any user's public profile."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ============================================================
# USER TICKET HISTORY
# ============================================================
@router.get("/{user_id}/tickets", response_model=List[TicketResponse])
async def get_user_ticket_history(
    user_id: int,
    role: Optional[str] = Query(
        None,
        description="'created' | 'assigned' | 'both' (default: both)",
    ),
    status_filter: Optional[TicketStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a user's ticket history.

    - Staff can only view their own history.
    - Technicians and Admins can view any user's history.
    """
    # Permission check
    if current_user.role == UserRole.STAFF and current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own ticket history",
        )

    # Ensure the user exists
    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Build query
    query = select(Ticket)

    if role == "created":
        query = query.where(Ticket.created_by == user_id)
    elif role == "assigned":
        query = query.where(Ticket.assigned_to == user_id)
    else:  # both
        query = query.where(
            or_(
                Ticket.created_by == user_id,
                Ticket.assigned_to == user_id,
            )
        )

    if status_filter:
        query = query.where(Ticket.status == status_filter)

    query = query.order_by(Ticket.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# ============================================================
# ADMIN: UPDATE USER
# ============================================================
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    update_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Update user (Admin only)."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for key, value in update_data.model_dump(exclude_unset=True).items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    return user


# ============================================================
# ADMIN: DEACTIVATE USER
# ============================================================
@router.delete("/{user_id}")
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Deactivate a user (Admin only)."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=400, detail="Cannot deactivate yourself"
        )

    user.is_active = False
    await db.commit()
    return {"message": f"User {user.full_name} deactivated"}