"""
Run once after migrations: `python -m app.seed`
Creates a demo organization (or reuses the one migration 0003's backfill
already created), a compliance admin login, a read-only demo analyst
login, and a starter set of fraud rules - so the dashboard and scoring
pipeline have something to work with out of the box.
"""
import asyncio
import json

from sqlalchemy import select

from app.auth import hash_password
from app.database import AsyncSessionLocal
from app.models import FraudRule, Organization, User
from app.redis_client import async_redis, rules_cache_key
from app.schemas import FraudRuleOut

DEFAULT_ADMIN_EMAIL = "admin@frauddetect.dev"
DEFAULT_ADMIN_PASSWORD = "ChangeMe123!"

DEMO_ANALYST_EMAIL = "demo@frauddetect.dev"
DEMO_ANALYST_PASSWORD = "demo-view-only"

STARTER_RULES = [
    dict(name="Velocity Check", rule_type="velocity", threshold=10, window_seconds=120, weight=0.4,
         description="Flags a user firing 10+ transactions inside a 2-minute window."),
    dict(name="Geo Spread Check", rule_type="geo_spread", threshold=3, window_seconds=120, weight=0.4,
         description="Flags a user transacting from 3+ different countries inside a 2-minute window."),
    dict(name="High Amount", rule_type="amount_threshold", threshold=5000, window_seconds=120, weight=0.2,
         description="Flags any single transaction over $5,000."),
]


async def seed():
    async with AsyncSessionLocal() as db:
        # Migration 0003's backfill always creates one org for existing
        # data - reuse it if present rather than creating a second one.
        result = await db.execute(select(Organization).order_by(Organization.created_at).limit(1))
        org = result.scalar_one_or_none()
        if not org:
            org = Organization(name="Demo Fintech Co")
            db.add(org)
            await db.flush()
            print(f"Created organization: {org.name}")
        else:
            print(f"Using existing organization: {org.name}")

        result = await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        if not result.scalar_one_or_none():
            db.add(User(
                org_id=org.id,
                email=DEFAULT_ADMIN_EMAIL,
                hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD),
                role="compliance_admin",
            ))
            print(f"Created admin user: {DEFAULT_ADMIN_EMAIL} / {DEFAULT_ADMIN_PASSWORD}")

        result = await db.execute(select(User).where(User.email == DEMO_ANALYST_EMAIL))
        if not result.scalar_one_or_none():
            db.add(User(
                org_id=org.id,
                email=DEMO_ANALYST_EMAIL,
                hashed_password=hash_password(DEMO_ANALYST_PASSWORD),
                role="analyst",
            ))
            print(f"Created demo analyst user: {DEMO_ANALYST_EMAIL} / {DEMO_ANALYST_PASSWORD}")

        for rule_kwargs in STARTER_RULES:
            result = await db.execute(
                select(FraudRule).where(FraudRule.org_id == org.id, FraudRule.name == rule_kwargs["name"])
            )
            if not result.scalar_one_or_none():
                db.add(FraudRule(**rule_kwargs, org_id=org.id, updated_by="seed"))

        await db.commit()

        result = await db.execute(select(FraudRule).where(FraudRule.org_id == org.id, FraudRule.enabled.is_(True)))
        rules = [FraudRuleOut.model_validate(r).model_dump(mode="json") for r in result.scalars().all()]
        await async_redis.set(rules_cache_key(str(org.id)), json.dumps(rules))

        print(f"\nOrganization API key (use for X-Org-Api-Key header on POST /api/transactions):")
        print(f"  {org.api_key}")
        print("\nSeed complete. Rules cache warmed.")


if __name__ == "__main__":
    asyncio.run(seed())
