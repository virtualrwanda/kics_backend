"""
Seed SLA policies.
Run: python scripts/seed_sla.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal, engine, Base
from app.models import analytics  # noqa
from app.models.analytics import SLAPolicy


SLA_POLICIES = [
    {"priority": "urgent", "first_response_minutes": 15, "resolution_minutes": 120},
    {"priority": "high",   "first_response_minutes": 30, "resolution_minutes": 240},
    {"priority": "medium", "first_response_minutes": 120, "resolution_minutes": 480},
    {"priority": "low",    "first_response_minutes": 480, "resolution_minutes": 1440},
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        for policy_data in SLA_POLICIES:
            result = await db.execute(
                select(SLAPolicy).where(SLAPolicy.priority == policy_data["priority"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"⚠️  SLA for {policy_data['priority']} already exists")
                continue

            policy = SLAPolicy(**policy_data)
            db.add(policy)
            print(f"✅ Created SLA: {policy_data['priority']} "
                  f"(response: {policy_data['first_response_minutes']}m, "
                  f"resolution: {policy_data['resolution_minutes']}m)")

        await db.commit()
        print("\n🎉 SLA policies seeded!")


if __name__ == "__main__":
    asyncio.run(seed())