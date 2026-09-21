from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",  # Ignore extra env vars
    )

    # ============================================================
    # App Settings
    # ============================================================
    APP_NAME: str = "KICS IT Help Desk"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # ============================================================
    # Database — MySQL (XAMPP)
    # ============================================================
    MYSQL_USER: str = "pacistv_kics"
    MYSQL_PASSWORD: str = "pacistv_kics"
    MYSQL_HOST: str ="198.251.83.106"          # ✅ no trailing colon
    MYSQL_PORT: int = 3306
    MYSQL_DB: str = "pacistv_kics"

    # Connection Pool
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_ECHO: bool = False

    # ============================================================
    # Redis (optional)
    # ============================================================
    REDIS_URL: str = "redis://localhost:6379/0"

    # ============================================================
    # Email — KICS (pacistv.rw)
    # ============================================================
    MAIL_USERNAME: str = "kics@pacistv.rw"
    MAIL_PASSWORD: str = "RwaPaC@2024!"
    MAIL_FROM: str = "kics@pacistv.rw"
    MAIL_FROM_NAME: str = "KICS IT Help Desk"
    MAIL_SERVER: str = "mail.pacistv.rw"
    MAIL_PORT: int = 465
    MAIL_STARTTLS: bool = False
    MAIL_SSL_TLS: bool = True
    MAIL_USE_CREDENTIALS: bool = True

    # IMAP — for email-to-ticket
    IMAP_SERVER: str = "mail.pacistv.rw"
    IMAP_PORT: int = 993
    IMAP_EMAIL: str = "kics@pacistv.rw"
    IMAP_PASSWORD: str = "RwaPaC@2024!"
    IMAP_USE_SSL: bool = True

    # ============================================================
    # Frontend
    # ============================================================
    FRONTEND_URL: str = "https://kics-front-roan.vercel.app"

    # ============================================================
    # Token expiry
    # ============================================================
    EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES: int = 1440   # 24 hours
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    MAGIC_LINK_TOKEN_EXPIRE_MINUTES: int = 15

    # ============================================================
    # Azure AD / Microsoft 365 SSO
    #   ✅ Now INSIDE the class so Settings picks them up
    # ============================================================
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    AZURE_TENANT_ID: str = ""
    AZURE_REDIRECT_URI: str = "https://kicsbackend.vercel.app/api/v1/auth/sso/callback"
    AZURE_AUTHORITY: str = "https://login.microsoftonline.com"

    # ============================================================
    # Computed Properties
    # ============================================================
    @property
    def DATABASE_URL(self) -> str:
        """Async MySQL URL for FastAPI runtime."""
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Sync MySQL URL for Alembic migrations."""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )


settings = Settings()
