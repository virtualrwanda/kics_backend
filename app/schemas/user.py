from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from ..models.user import UserRole


# ============================================================
# USER
# ============================================================
class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    department: Optional[str] = None
    phone: Optional[str] = None


class UserCreate(UserBase):
    password: str
    role: UserRole = UserRole.STAFF


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: int
    role: UserRole
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str] = None   # ← NEW
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================
# LOGIN / TOKENS
# ============================================================
class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============================================================
# PASSWORD RESET
# ============================================================
class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


# ============================================================
# MAGIC LINK
# ============================================================
class MagicLinkRequest(BaseModel):
    email: EmailStr


# ============================================================
# EMAIL VERIFICATION
# ============================================================
class EmailVerifyRequest(BaseModel):
    token: str


# ============================================================
# 2FA / OTP
# ============================================================
class OTPVerifyRequest(BaseModel):
    email: EmailStr
    code: str
    purpose: str = "login_2fa"


class OTPVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class Login2FARequired(BaseModel):
    requires_2fa: bool = True
    email: EmailStr
    message: str = "A 6-digit code has been sent to your email."
    expires_in_minutes: int = 5


class OTPResendRequest(BaseModel):
    email: EmailStr
    purpose: str = "login_2fa"