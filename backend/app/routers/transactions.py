import random
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, get_org_from_api_key
from app.celery_app import celery_app
from app.database import get_db
from app.logging_config import log
from app.ml.inference import MLScorer
from app.models import AllowlistEntry, Organization, Transaction, User
from app.redis_client import async_redis, allowlist_key
from app.schemas import AllowlistIn, ReviewIn, TransactionIn, TransactionOut

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24  # 24h - matches how long a client might reasonably retry
IDEMPOTENCY_KEY_PREFIX = "idempotency:ingest:"

BURST_COUNTRIES = ["US", "GB", "DE", "NG", "IN", "BR", "SG", "AU", "FR", "CA", "MX", "JP"]

_explain_scorer: MLScorer | None = None


def _get_explain_scorer() -> MLScorer:
    # Separate lazily-loaded instance from the Celery worker's ml_scorer -
    # this process (FastAPI) is not the worker, and explain() is only ever
    # called on-demand from here, never in the ingestion hot path.
    global _explain_scorer
    if _explain_scorer is None:
        _explain_scorer = MLScorer()
    return _explain_scorer


@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def ingest_transaction(
    payload: TransactionIn,
    org: Organization = Depends(get_org_from_api_key),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """
    High-speed ingestion endpoint. Authenticated by an org-scoped API key
    (not analyst JWT auth - the caller here is a payment gateway, not a
    human). Validates via Pydantic, hands the transaction to Celery's
    Redis-backed broker, and returns 202 immediately - scoring happens
    asynchronously in a worker (see app/tasks.py).

    An `Idempotency-Key` header protects against double-processing if the
    client retries after a network blip, without knowing whether the first
    attempt landed - standard practice for payment APIs.
    """
    if idempotency_key:
        cache_key = f"{IDEMPOTENCY_KEY_PREFIX}{org.id}:{idempotency_key}"
        existing_id = await async_redis.get(cache_key)
        if existing_id:
            log.info("transaction.idempotent_replay", idempotency_key=idempotency_key, tx_id=existing_id)
            return {"accepted": True, "id": existing_id, "idempotent_replay": True}

    tx_id = str(uuid.uuid4())
    envelope = {
        "id": tx_id,
        "org_id": str(org.id),
        "user_ref": payload.user_ref,
        "amount": payload.amount,
        "currency": payload.currency,
        "country": payload.country,
        "merchant": payload.merchant,
        "received_at": datetime.utcnow().isoformat(),
        "idempotency_key": idempotency_key,
    }

    if idempotency_key:
        await async_redis.set(f"{IDEMPOTENCY_KEY_PREFIX}{org.id}:{idempotency_key}", tx_id, ex=IDEMPOTENCY_TTL_SECONDS)

    celery_app.send_task("app.tasks.score_transaction", args=[envelope])
    log.info("transaction.ingested", tx_id=tx_id, org_id=str(org.id), user_ref=payload.user_ref)
    return {"accepted": True, "id": tx_id}


@router.get("/", response_model=list[TransactionOut])
async def list_transactions(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Transaction)
        .where(Transaction.org_id == user.org_id)
        .order_by(desc(Transaction.created_at))
        .limit(limit)
    )
    return result.scalars().all()


@router.patch("/{transaction_id}/review", response_model=TransactionOut)
async def review_transaction(
    transaction_id: uuid.UUID,
    payload: ReviewIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Analyst feedback loop: lets a human confirm a flagged transaction as
    real fraud, dismiss it as a false positive, or reset it to unreviewed.
    """
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.org_id == user.org_id)
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    tx.reviewed_status = payload.status
    tx.reviewed_by = user.email if payload.status != "unreviewed" else None
    tx.reviewed_at = datetime.utcnow() if payload.status != "unreviewed" else None

    await db.commit()
    await db.refresh(tx)
    return tx


@router.get("/{transaction_id}/ml-explain")
async def explain_transaction(
    transaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    On-demand only - NOT part of the ingestion hot path. Reconstructs the
    exact feature vector used at scoring time (stored on the row) and runs
    LightGBM's native pred_contrib for a per-feature explanation of why
    the ML layer scored this transaction the way it did.
    """
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.org_id == user.org_id)
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if not tx.ml_features:
        return {"available": False, "reason": "No ML features recorded for this transaction (e.g. allowlisted)."}

    scorer = _get_explain_scorer()
    if not scorer.is_ready:
        return {"available": False, "reason": "ML model is not currently loaded on this server."}

    contributions = scorer.explain(tx.ml_features, top_n=5)
    return {
        "available": True,
        "ml_score": tx.ml_score,
        "ml_tier": tx.ml_tier,
        "model_version": tx.ml_model_version,
        "top_contributing_features": contributions,
        "raw_features": tx.ml_features,
    }


@router.post("/allowlist", status_code=status.HTTP_201_CREATED)
async def allowlist_user(
    payload: AllowlistIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Manual override for customer support / compliance to clear a user (a
    VIP, or a confirmed false positive) for a window of time, bypassing
    rules and ML entirely. Writes to Postgres for audit, and to Redis for
    the fast lookup the Celery worker actually checks.
    """
    expires_at = datetime.utcnow() + timedelta(hours=payload.hours)

    existing = await db.execute(
        select(AllowlistEntry).where(
            AllowlistEntry.org_id == user.org_id, AllowlistEntry.user_ref == payload.user_ref
        )
    )
    entry = existing.scalar_one_or_none()
    if entry:
        entry.expires_at = expires_at
        entry.created_by = user.email
        entry.created_at = datetime.utcnow()
    else:
        entry = AllowlistEntry(
            org_id=user.org_id,
            user_ref=payload.user_ref,
            created_by=user.email,
            expires_at=expires_at,
        )
        db.add(entry)

    await db.commit()

    await async_redis.set(
        allowlist_key(str(user.org_id), payload.user_ref), "1", ex=payload.hours * 3600
    )

    log.info("user.allowlisted", user_ref=payload.user_ref, by=user.email, hours=payload.hours)
    return {"user_ref": payload.user_ref, "expires_at": expires_at.isoformat()}


@router.post("/simulate-burst", status_code=status.HTTP_202_ACCEPTED)
async def simulate_burst(user: User = Depends(get_current_user)):
    """
    Fires a synthetic fraud burst server-side - one throwaway user
    transacting from several different countries in rapid succession -
    so the live feed and flag counter visibly react within a couple of
    seconds. Exists purely so a demo doesn't require a terminal or the
    mock generator; not part of the real ingestion path.
    """
    burst_user = f"demo_burst_{uuid.uuid4().hex[:6]}"
    countries = random.sample(BURST_COUNTRIES, k=len(BURST_COUNTRIES))

    for country in countries:
        envelope = {
            "id": str(uuid.uuid4()),
            "org_id": str(user.org_id),
            "user_ref": burst_user,
            "amount": round(random.uniform(5, 40), 2),
            "currency": "USD",
            "country": country,
            "merchant": "Demo Simulation",
            "received_at": datetime.utcnow().isoformat(),
            "idempotency_key": None,
        }
        celery_app.send_task("app.tasks.score_transaction", args=[envelope])

    log.info("transaction.burst_simulated", user_ref=burst_user, count=len(countries))
    return {"accepted": True, "simulated_user": burst_user, "count": len(countries)}
