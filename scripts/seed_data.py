"""
Seed data script for KICS IT Help Desk ticketing system.
Creates initial users and sample tickets in MySQL.

Run with: python scripts/seed_data.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal, init_db, engine, Base
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.ticket import Ticket, TicketCategory, TicketPriority, TicketStatus
from app.models.comment import Comment


async def create_tables():
    """Create all database tables."""
    print("🔨 Creating database tables...")
    async with engine.begin() as conn:
        # Import all models so they register with Base.metadata
        from app.models import user, ticket, comment  # noqa
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tables created successfully!")


async def seed_users(db):
    """Create initial users if they don't exist."""
    print("\n👥 Creating users...")

    users_data = [
        {
            "email": "admin@kics.rw",
            "full_name": "System Administrator",
            "password": "Admin@123",
            "role": UserRole.ADMIN,
            "department": "IT",
        },
        {
            "email": "tech@kics.rw",
            "full_name": "Fulgence",
            "password": "Tech@123",
            "role": UserRole.TECHNICIAN,
            "department": "IT",
        },
        {
            "email": "staff@kics.rw",
            "full_name": "Jane Teacher",
            "password": "Staff@123",
            "role": UserRole.STAFF,
            "department": "Elementary",
        },
    ]

    created_users = {}

    for data in users_data:
        # Check if user exists
        result = await db.execute(
            select(User).where(User.email == data["email"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            print(f"  ⚠️  User {data['email']} already exists — skipping")
            created_users[data["email"]] = existing
            continue

        user = User(
            email=data["email"],
            full_name=data["full_name"],
            hashed_password=get_password_hash(data["password"]),
            role=data["role"],
            department=data["department"],
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        await db.flush()  # Get ID without committing
        created_users[data["email"]] = user
        print(f"  ✅ Created {data['role'].value}: {data['email']}")

    await db.commit()
    return created_users


async def seed_tickets(db, users):
    """Create sample tickets."""
    print("\n🎫 Creating sample tickets...")

    # Check if tickets already exist
    result = await db.execute(select(Ticket).limit(1))
    if result.scalar_one_or_none():
        print("  ⚠️  Tickets already exist — skipping")
        return

    admin = users["admin@kics.rw"]
    tech = users["tech@kics.rw"]
    staff = users["staff@kics.rw"]

    tickets_data = [
        {
            "title": "Printer not working in Room 204",
            "description": (
                "The HP LaserJet printer in Room 204 shows 'offline' status. "
                "Cannot print lesson plans for tomorrow's class. "
                "Tried restarting the printer but no luck."
            ),
            "category": TicketCategory.PRINTER,
            "priority": TicketPriority.HIGH,
            "status": TicketStatus.ASSIGNED,
            "created_by": staff.id,
            "assigned_to": tech.id,
        },
        {
            "title": "Password reset for email account",
            "description": (
                "I forgot my school email password and cannot access my account. "
                "Please reset it or send me a recovery link."
            ),
            "category": TicketCategory.ACCOUNT,
            "priority": TicketPriority.MEDIUM,
            "status": TicketStatus.NEW,
            "created_by": staff.id,
            "assigned_to": None,
        },
        {
            "title": "WiFi not connecting in Library",
            "description": (
                "The WiFi network 'KICS-Staff' is not connecting on my laptop. "
                "It was working yesterday. Other teachers have the same issue."
            ),
            "category": TicketCategory.NETWORK,
            "priority": TicketPriority.URGENT,
            "status": TicketStatus.IN_PROGRESS,
            "created_by": staff.id,
            "assigned_to": tech.id,
        },
        {
            "title": "Install Microsoft Office on new laptop",
            "description": (
                "I received a new laptop for the new school year. "
                "Need Microsoft Office installed for lesson planning."
            ),
            "category": TicketCategory.SOFTWARE,
            "priority": TicketPriority.LOW,
            "status": TicketStatus.NEW,
            "created_by": staff.id,
            "assigned_to": None,
        },
    ]

    for data in tickets_data:
        ticket = Ticket(**data)
        db.add(ticket)

    await db.commit()
    print(f"  ✅ Created {len(tickets_data)} sample tickets")


async def seed_comments(db, users):
    """Create sample comments on tickets."""
    print("\n💬 Creating sample comments...")

    # Get the first ticket
    result = await db.execute(select(Ticket).order_by(Ticket.id).limit(1))
    ticket = result.scalar_one_or_none()

    if not ticket:
        print("  ⚠️  No tickets found — skipping comments")
        return

    # Check if comments already exist
    result = await db.execute(
        select(Comment).where(Comment.ticket_id == ticket.id).limit(1)
    )
    if result.scalar_one_or_none():
        print("  ⚠️  Comments already exist — skipping")
        return

    tech = users["tech@kics.rw"]
    staff = users["staff@kics.rw"]

    comments_data = [
        {
            "ticket_id": ticket.id,
            "author_id": tech.id,
            "content": "Hi Jane, I'll come check the printer this afternoon. What time works for you?",
            "is_internal": False,
        },
        {
            "ticket_id": ticket.id,
            "author_id": staff.id,
            "content": "Anytime after 2 PM is fine. Thank you!",
            "is_internal": False,
        },
        {
            "ticket_id": ticket.id,
            "author_id": tech.id,
            "content": "Note: This printer has been having issues since last month. May need replacement.",
            "is_internal": True,
        },
    ]

    for data in comments_data:
        comment = Comment(**data)
        db.add(comment)

    await db.commit()
    print(f"  ✅ Created {len(comments_data)} sample comments")


async def main():
    """Main entry point."""
    print("=" * 60)
    print("🌱 KICS Ticketing System — Database Seeder")
    print("=" * 60)

    # Step 1: Create tables
    await create_tables()

    # Step 2: Seed data
    async with AsyncSessionLocal() as db:
        try:
            users = await seed_users(db)
            await seed_tickets(db, users)
            await seed_comments(db, users)
        except Exception as e:
            await db.rollback()
            print(f"\n❌ Error during seeding: {e}")
            raise

    print("\n" + "=" * 60)
    print("🎉 Seeding complete!")
    print("=" * 60)
    print("\n🔐 Login credentials:")
    print("   Admin:       admin@kics.rw  /  Admin@123")
    print("   Technician:  tech@kics.rw   /  Tech@123")
    print("   Staff:       staff@kics.rw  /  Staff@123")
    print("\n🚀 Start the server:")
    print("   python -m uvicorn app.main:app --reload")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())