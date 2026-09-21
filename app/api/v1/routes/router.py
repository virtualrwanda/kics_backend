from fastapi import APIRouter
from .routes import auth, tickets, users, dashboard, admin
from ....services import audit_service

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(tickets.router)
api_router.include_router(users.router)
api_router.include_router(dashboard.router)
api_router.include_router(admin.router)

# ---- Ratings & Performance ----
try:
    from .routes import ratings
    api_router.include_router(ratings.router)
    print("✅ Ratings routes registered")
except Exception as e:
    print(f"⚠️  Ratings routes NOT registered: {type(e).__name__}: {e}")

# ---- Chat ----
try:
    from .routes import chat
    api_router.include_router(chat.router)
    print("✅ Chat routes registered")
except Exception as e:
    print(f"⚠️  Chat routes NOT registered: {type(e).__name__}: {e}")

# ---- WebSocket ----
try:
    from .routes import ws
    api_router.include_router(ws.router)
    print("✅ WebSocket route registered")
except Exception as e:
    print(f"⚠️  WebSocket route NOT registered: {type(e).__name__}: {e}")
    
try:
    from .routes import kb
    api_router.include_router(kb.router)
    print("✅ Knowledge Base routes registered")
except Exception as e:
    print(f"⚠️  KB routes NOT registered: {e}")
    

await audit_service.log_action(
    db, current_user.id, "ticket_created",
    entity_type="ticket", entity_id=new_ticket.id,
    description=f"Created ticket {new_ticket.ticket_number}",
)