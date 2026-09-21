# generate_files.ps1 - Creates all missing KICS Ticketing files
Write-Host "📝 Generating KICS Ticketing files..." -ForegroundColor Cyan

function Write-File($path, $content) {
    $dir = Split-Path $path -Parent
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -Path $dir -ItemType Directory -Force | Out-Null
    }
    Set-Content -Path $path -Value $content -Encoding UTF8
    Write-Host "  ✅ Created $path" -ForegroundColor Green
}

# ==========================================
# 1. app/core/security.py
# ==========================================
Write-File "app\core\security.py" @'
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return {}
'@

# ==========================================
# 2. app/core/dependencies.py
# ==========================================
Write-File "app\core\dependencies.py" @'
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from .database import get_db
from .security import decode_token
from ..models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if not payload:
        raise credentials_exception
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    result = await db.execute(
        select(User).where(User.id == int(user_id), User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def require_admin(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


async def require_technician(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.role not in [UserRole.TECHNICIAN, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Technician privileges required")
    return current_user
'@

# ==========================================
# 3. app/models/user.py
# ==========================================
Write-File "app\models\user.py" @'
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
    is_active = Column(Boolean, default=True, index=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    created_tickets = relationship("Ticket", foreign_keys="Ticket.created_by", back_populates="creator")
    assigned_tickets = relationship("Ticket", foreign_keys="Ticket.assigned_to", back_populates="assignee")
    comments = relationship("Comment", back_populates="author")

    __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)
'@

# ==========================================
# 4. app/models/ticket.py
# ==========================================
Write-File "app\models\ticket.py" @'
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Enum, ForeignKey,
    Boolean, Index, CheckConstraint, JSON
)
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
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
'@

# ==========================================
# 5. app/models/comment.py
# ==========================================
Write-File "app\models\comment.py" @'
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..core.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    ticket = relationship("Ticket", back_populates="comments")
    author = relationship("User", back_populates="comments")

    __table_args__ = (
        Index("ix_comments_ticket_created", "ticket_id", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
'@

# ==========================================
# 6. app/models/__init__.py
# ==========================================
Write-File "app\models\__init__.py" @'
from .user import User, UserRole
from .ticket import Ticket, TicketPriority, TicketStatus, TicketCategory
from .comment import Comment

__all__ = [
    "User", "UserRole",
    "Ticket", "TicketPriority", "TicketStatus", "TicketCategory",
    "Comment",
]
'@

Write-Host "`n🎉 Core files generated!" -ForegroundColor Green
Write-Host "Now run: python -m uvicorn app.main:app --reload" -ForegroundColor Cyan