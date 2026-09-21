from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    BackgroundTasks,
    Request,
)
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from ....core.database import get_db
from ....core.security import (
    verify_password,
    create_access_token,
    get_password_hash,
    create_email_token,
    verify_email_token,
)
from ....core.dependencies import get_current_user, require_admin
from ....core.config import settings
from ....models.user import User, UserRole
from ....schemas.user import (
    UserCreate,
    UserResponse,
    TokenResponse,
    UserLogin,
    PasswordResetRequest,
    PasswordResetConfirm,
    MagicLinkRequest,
    EmailVerifyRequest,
    OTPVerifyRequest,
    OTPVerifyResponse,
    Login2FARequired,
    OTPResendRequest,
)
from ....services.email_service import (
    send_email,
    verification_email_template,
    password_reset_email_template,
    magic_link_email_template,
    otp_email_template,
)
from ....services import otp_service, sso_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ============================================================
# REGISTER
# ============================================================
@router.post("/register", response_model=UserResponse, status_code=201)
async def register_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user.
    Sends an email verification link.
    """
    # Check email uniqueness
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=get_password_hash(user_data.password),
        role=user_data.role,
        department=user_data.department,
        phone=user_data.phone,
        is_active=True,
        is_verified=False,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    # Send verification email in background
    token = create_email_token(new_user.email, "verify")
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    html = verification_email_template(new_user.full_name, verify_url)
    background_tasks.add_task(
        send_email,
        [new_user.email],
        "Verify your KICS Help Desk account",
        html,
    )

    logger.info(f"New user registered: {new_user.email} (role={new_user.role.value})")
    return new_user


# ============================================================
# LOGIN — STEP 1: Verify password, send OTP
# ============================================================
@router.post("/login", response_model=Login2FARequired)
async def login(
    login_data: UserLogin,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 1 of 2FA login: verify email + password, then send 6-digit OTP.
    """
    result = await db.execute(select(User).where(User.email == login_data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(login_data.password, user.hashed_password):
        # Same message for both cases → prevents email enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="User account is disabled")

    # Generate OTP (rate-limited)
    try:
        code = await otp_service.create_otp(
            db=db,
            user=user,
            purpose="login_2fa",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))

    await db.commit()

    # Send OTP email in background
    html = otp_email_template(user.full_name, code, purpose="login_2fa")
    background_tasks.add_task(
        send_email,
        [user.email],
        "Your KICS Help Desk login code",
        html,
    )

    logger.info(f"2FA OTP sent: {user.email}")

    return Login2FARequired(
        requires_2fa=True,
        email=user.email,
        message=f"A 6-digit code has been sent to {user.email}",
        expires_in_minutes=otp_service.OTP_EXPIRY_MINUTES,
    )


# ============================================================
# LOGIN — STEP 2: Verify OTP, issue JWT
# ============================================================
@router.post("/verify-otp", response_model=OTPVerifyResponse)
async def verify_otp(
    payload: OTPVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2 of 2FA login: verify OTP code and return JWT.
    """
    success, error, user = await otp_service.verify_otp(
        db=db,
        email=payload.email,
        purpose=payload.purpose,
        code=payload.code,
    )

    if not success or not user:
        raise HTTPException(status_code=400, detail=error or "Invalid code")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Account disabled")

    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value}
    )

    logger.info(f"User logged in via 2FA: {user.email}")

    return OTPVerifyResponse(
        access_token=access_token,
        user=user,
    )


# ============================================================
# LOGIN — RESEND OTP
# ============================================================
@router.post("/resend-otp", response_model=Login2FARequired)
async def resend_otp(
    payload: OTPResendRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Resend OTP code (rate-limited to 3 per 5 min)."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Don't reveal whether the email exists
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Unable to resend code")

    try:
        code = await otp_service.create_otp(
            db=db,
            user=user,
            purpose=payload.purpose,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))

    await db.commit()

    html = otp_email_template(user.full_name, code, purpose=payload.purpose)
    background_tasks.add_task(
        send_email,
        [user.email],
        "Your KICS Help Desk code (resend)",
        html,
    )

    logger.info(f"OTP resent: {user.email}")

    return Login2FARequired(
        requires_2fa=True,
        email=user.email,
        message=f"A new code has been sent to {user.email}",
        expires_in_minutes=otp_service.OTP_EXPIRY_MINUTES,
    )


# ============================================================
# SWAGGER / OAUTH2 FORM LOGIN (bypasses 2FA for API testing)
# ============================================================
@router.post("/login-form", response_model=TokenResponse)
async def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth2 form login for Swagger UI.
    ⚠️  Bypasses 2FA — only for API testing.
    """
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Account disabled")

    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value}
    )
    return TokenResponse(access_token=access_token, user=user)


# ============================================================
# CURRENT USER
# ============================================================
@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user."""
    return current_user


@router.post("/logout")
async def logout():
    """Logout (client-side token removal)."""
    return {"message": "Successfully logged out"}


# ============================================================
# EMAIL VERIFICATION
# ============================================================
@router.post("/verify-email")
async def verify_email(
    payload: EmailVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify email using token from verification email."""
    email = verify_email_token(
        payload.token,
        purpose="verify",
        max_age_seconds=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES * 60,
    )
    if not email:
        raise HTTPException(
            status_code=400, detail="Invalid or expired verification token"
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_verified:
        return {"message": "Email already verified"}

    user.is_verified = True
    await db.commit()

    logger.info(f"Email verified: {user.email}")
    return {"message": "Email verified successfully"}


# ============================================================
# PASSWORD RESET — REQUEST
# ============================================================
@router.post("/forgot-password")
async def forgot_password(
    payload: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Request password reset link."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Always return success (don't reveal whether email exists)
    if not user or not user.is_active:
        return {"message": "If that email exists, a reset link has been sent."}

    token = create_email_token(user.email, "reset")
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    html = password_reset_email_template(user.full_name, reset_url)
    background_tasks.add_task(
        send_email,
        [user.email],
        "Reset your KICS Help Desk password",
        html,
    )

    logger.info(f"Password reset requested: {user.email}")
    return {"message": "If that email exists, a reset link has been sent."}


# ============================================================
# PASSWORD RESET — CONFIRM
# ============================================================
@router.post("/reset-password")
async def reset_password(
    payload: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using token from email."""
    email = verify_email_token(
        payload.token,
        purpose="reset",
        max_age_seconds=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES * 60,
    )
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(payload.new_password)
    await db.commit()

    logger.info(f"Password reset: {user.email}")
    return {"message": "Password reset successfully. You can now log in."}


# ============================================================
# MAGIC LINK — REQUEST
# ============================================================
@router.post("/magic-link")
async def request_magic_link(
    payload: MagicLinkRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Request a one-time login link by email."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Always return success
    if not user or not user.is_active:
        return {"message": "If that email exists, a login link has been sent."}

    token = create_email_token(user.email, "magic")
    login_url = f"{settings.FRONTEND_URL}/magic-login?token={token}"
    html = magic_link_email_template(user.full_name, login_url)
    background_tasks.add_task(
        send_email,
        [user.email],
        "Your KICS Help Desk login link",
        html,
    )

    logger.info(f"Magic link requested: {user.email}")
    return {"message": "If that email exists, a login link has been sent."}


# ============================================================
# MAGIC LINK — CONSUME
# ============================================================
@router.get("/magic-login", response_model=TokenResponse)
async def magic_login(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Consume a magic link token and return a JWT."""
    email = verify_email_token(
        token,
        purpose="magic",
        max_age_seconds=settings.MAGIC_LINK_TOKEN_EXPIRE_MINUTES * 60,
    )
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired login link")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")

    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value}
    )

    logger.info(f"User logged in via magic link: {user.email}")
    return TokenResponse(access_token=access_token, user=user)


# ============================================================
# SSO — MICROSOFT 365 / AZURE AD — START
# ============================================================
@router.get("/sso/login")
async def sso_login():
    """Redirect user to Microsoft login."""
    try:
        url = await sso_service.get_authorization_url(state="kics-sso")
        return RedirectResponse(url)
    except Exception as e:
        logger.exception(f"SSO start failed: {e}")
        raise HTTPException(status_code=500, detail="SSO unavailable")


# ============================================================
# SSO — CALLBACK
# ============================================================
@router.get("/sso/callback")
async def sso_callback(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Microsoft OAuth callback.
    Auto-provisions users on first login.
    """
    userinfo = await sso_service.exchange_code_for_token(code)
    if not userinfo or not userinfo.get("email"):
        raise HTTPException(status_code=400, detail="SSO authentication failed")

    email = userinfo["email"].lower()

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Auto-provision new user
    if not user:
        user = User(
            email=email,
            full_name=userinfo.get("name") or email.split("@")[0],
            hashed_password=get_password_hash("SSO_USER_NO_PASSWORD"),
            role=UserRole.STAFF,
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info(f"Auto-provisioned SSO user: {email}")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value}
    )

    logger.info(f"User logged in via SSO: {user.email}")

    # Redirect to frontend with token
    redirect = (
        f"{settings.FRONTEND_URL}/sso-callback"
        f"?access_token={access_token}"
        f"&token_type=bearer"
    )
    return RedirectResponse(redirect)