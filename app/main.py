from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
import logging
from .services.sla_escalation_service import escalation_loop
from .services.auto_close_service import auto_close_loop
from .core.config import settings
from .core.database import init_db, close_db, check_db_health
from .api.v1.router import api_router

# Import all models so they register with SQLAlchemy
from .models import user, ticket, comment, analytics, chat, otp  # noqa

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================
# LIFESPAN
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(
        f"🐬 MySQL: {settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}"
    )

    if settings.DEBUG:
        await init_db()
        logger.info("✅ Database tables initialized (dev mode)")
    else:
        if await check_db_health():
            logger.info("✅ Database connection healthy")
        else:
            raise RuntimeError("Cannot connect to database")

    yield

    await close_db()
    logger.info("👋 Application shutdown complete")


# ============================================================
# 1. CREATE THE APP FIRST
# ============================================================
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="IT Help Desk and Ticketing System for KICS",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ============================================================
# 2. CORS
# ============================================================
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    settings.FRONTEND_URL,
]
ALLOWED_ORIGINS = list({o for o in ALLOWED_ORIGINS if o})

logger.info(f"🌐 CORS allowed origins: {ALLOWED_ORIGINS}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)


# ============================================================
# 3. STATIC FILES — /uploads (avatars, chat attachments)
# ============================================================
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
(UPLOAD_DIR / "chat").mkdir(exist_ok=True)
(UPLOAD_DIR / "avatars").mkdir(exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# ============================================================
# 4. ROUTES
# ============================================================
app.include_router(api_router)


# ============================================================
# 5. ROOT + HEALTH
# ============================================================
@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "database": "mysql",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    db_healthy = await check_db_health()
    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
    }


# ============================================================
# 6. GLOBAL EXCEPTION HANDLER
# ============================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    origin = request.headers.get("origin", "*")
    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
    }
    if settings.DEBUG:
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "type": type(exc).__name__},
            headers=headers,
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )