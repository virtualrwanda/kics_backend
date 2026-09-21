from datetime import datetime, timedelta
import asyncio
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="kics-auth")


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


def create_email_token(email: str, purpose: str = "verify") -> str:
    """Create a signed token for email verification / password reset / magic link."""
    return _serializer.dumps({"email": email, "purpose": purpose})


def verify_email_token(token: str, purpose: str, max_age_seconds: int) -> Optional[str]:
    """Verify a signed token. Returns email if valid, else None."""
    try:
        data = _serializer.loads(token, max_age=max_age_seconds)
        if data.get("purpose") != purpose:
            return None
        return data.get("email")
    except (BadSignature, SignatureExpired):
        return None
