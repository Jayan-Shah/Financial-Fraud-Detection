import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_role
from app.database import get_db
from app.models import FraudRule, User
from app.redis_client import async_redis, rules_cache_key
from app.schemas import FraudRuleIn, FraudRuleOut

router = APIRouter(prefix="/api/rules", tags=["rules"])


async def _refresh_cache(db: AsyncSession, org_id):
    """Rules table (Postgres) is the source of truth; Redis is a read-through
    cache that Celery workers hit on every transaction for low-latency
    scoring. Cache is per-org - each tenant has independent thresholds."""
    result = await db.execute(
        select(FraudRule).where(FraudRule.org_id == org_id, FraudRule.enabled.is_(True))
    )
    rules = [FraudRuleOut.model_validate(r).model_dump(mode="json") for r in result.scalars().all()]
    await async_redis.set(rules_cache_key(str(org_id)), json.dumps(rules))


@router.get("/", response_model=list[FraudRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("analyst", "compliance_admin")),
):
    result = await db.execute(select(FraudRule).where(FraudRule.org_id == user.org_id))
    return result.scalars().all()


@router.post("/", response_model=FraudRuleOut, status_code=201)
async def create_rule(
    payload: FraudRuleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("compliance_admin")),
):
    rule = FraudRule(**payload.model_dump(), org_id=user.org_id, updated_by=user.email)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await _refresh_cache(db, user.org_id)
    return rule


@router.put("/{rule_id}", response_model=FraudRuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    payload: FraudRuleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("compliance_admin")),
):
    """This is the endpoint that lets compliance managers adjust fraud
    strictness live - no redeploy, no engineer involved."""
    result = await db.execute(
        select(FraudRule).where(FraudRule.id == rule_id, FraudRule.org_id == user.org_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    for field, value in payload.model_dump().items():
        setattr(rule, field, value)
    rule.updated_by = user.email

    await db.commit()
    await db.refresh(rule)
    await _refresh_cache(db, user.org_id)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("compliance_admin")),
):
    result = await db.execute(
        select(FraudRule).where(FraudRule.id == rule_id, FraudRule.org_id == user.org_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()
    await _refresh_cache(db, user.org_id)
