from . import auth
from . import tickets
from . import users
from . import dashboard
from . import admin

# chat and ws are imported lazily in router.py
# so a missing dependency doesn't break the whole app

__all__ = [
    "auth",
    "tickets",
    "users",
    "dashboard",
    "admin",
]