import json
import math
import time
import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.celery_app import celery_app
from app.config import settings
from app.logging_config import configure_logging, log
from app.ml.inference import MLScorer
from app.models import Transaction
from app.redis_client import (
    sync_redis_client,
    rules_cache_key,
    velocity_key,
    user_stats_key,
    user_geo_key,
    allowlist_key,
)

configure_logging()

# Celery workers run in their own process with no asyncio event loop, so we
# use a plain sync SQLAlchemy engine here rather than the async one FastAPI uses.
sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine)

# Loaded once per worker process at module import time - never
# re-instantiated per transaction. If the artifact is missing or fails to
# load, MLScorer degrades gracefully (score() always returns a safe
# "clean" result rather than raising), so a missing/broken model file
# never blocks transaction processing - it just means the system runs on
# rules alone until the artifact is fixed.
ml_scorer = MLScorer()
if not ml_scorer.is_ready:
    log.error("ml_model.load_failed", detail=getattr(ml_scorer, "_load_error", "unknown"))
else:
    log.info("ml_model.ready", version=ml_scorer._version)


def _load_rules(org_id: str) -> list[dict]:
    cached = sync_redis_client.get(rules_cache_key(org_id))
    if not cached:
        return []
    return json.loads(cached)


def _record_velocity(org_id: str, user_ref: str, country: str, window_seconds: int) -> tuple[int, set]:
    """Sliding-window velocity + geo-spread check using a Redis sorted set,
    keyed per org+user. Cheap O(log n) and self-expiring."""
    key = velocity_key(org_id, user_ref)
    now = time.time()
    member = f"{now}:{country}:{uuid.uuid4().hex[:6]}"

    pipe = sync_redis_client.pipeline()
    pipe.zadd(key, {member: now})
    pipe.zremrangebyscore(key, 0, now - window_seconds)
    pipe.zrange(key, 0, -1)
    pipe.expire(key, window_seconds * 2)
    _, _, members, _ = pipe.execute()

    countries = {m.split(":")[1] for m in members}
    return len(members), countries


def _rules_score(rules: list[dict], amount: float, tx_count: int, country_spread: int) -> tuple[float, dict]:
    score = 0.0
    reasons = {}

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        rtype = rule["rule_type"]
        weight = rule.get("weight", 1.0)
        threshold = rule["threshold"]

        if rtype == "velocity" and tx_count >= threshold:
            score += weight
            reasons["velocity"] = f"{tx_count} transactions in {rule['window_seconds']}s (limit {threshold})"
        elif rtype == "geo_spread" and country_spread >= threshold:
            score += weight
            reasons["geo_spread"] = f"{country_spread} countries in {rule['window_seconds']}s (limit {threshold})"
        elif rtype == "amount_threshold" and amount >= threshold:
            score += weight
            reasons["amount_threshold"] = f"amount {amount} >= {threshold}"

    return min(score, 1.0), reasons


def _fetch_and_update_lifetime_state(org_id: str, user_ref: str, country: str, amount: float, now: float) -> dict:
    """
    Fetches this user's lifetime stats (for amount_z_score, time_since_last_tx)
    and per-country history (for geo_country_rarity) BEFORE updating them -
    the exact fetch-then-update order the ML training replay assumed, so
    there is zero train/serve skew. Returns the derived ML features; updates
    Redis state as a side effect after computing them.
    """
    stats_key = user_stats_key(org_id, user_ref)
    geo_key = user_geo_key(org_id, user_ref)

    pipe = sync_redis_client.pipeline()
    pipe.hgetall(stats_key)
    pipe.hget(geo_key, country)
    stats, country_past_count = pipe.execute()

    total_tx = float(stats.get("total_tx", 0))
    sum_amt = float(stats.get("sum_amt", 0.0))
    sum_sq_amt = float(stats.get("sum_sq_amt", 0.0))
    last_tx = float(stats.get("last_tx")) if stats.get("last_tx") else None
    country_past_count = float(country_past_count or 0)

    if total_tx > 0:
        user_mean = sum_amt / total_tx
        variance = (sum_sq_amt / total_tx) - (user_mean ** 2)
        user_std = math.sqrt(variance) if variance > 0 else 1.0
    else:
        user_mean, user_std = 0.0, 1.0
    amount_z_score = (amount - user_mean) / (user_std if user_std > 0 else 1.0)

    geo_country_rarity = (total_tx - country_past_count) / total_tx if total_tx > 0 else 0.0

    time_since_last_tx = now - last_tx if last_tx is not None else 86400 * 30

    # --- update state for next time (mirrors the post-scoring writes) ---
    update_pipe = sync_redis_client.pipeline()
    update_pipe.hincrby(stats_key, "total_tx", 1)
    update_pipe.hincrbyfloat(stats_key, "sum_amt", amount)
    update_pipe.hincrbyfloat(stats_key, "sum_sq_amt", amount * amount)
    update_pipe.hset(stats_key, "last_tx", now)
    update_pipe.hincrby(geo_key, country, 1)
    update_pipe.execute()

    dt = datetime.fromtimestamp(now)
    return {
        "amount_log": math.log1p(amount),
        "amount_z_score": amount_z_score,
        "geo_country_rarity": geo_country_rarity,
        "time_hour_sin": math.sin(2 * math.pi * dt.hour / 24),
        "time_hour_cos": math.cos(2 * math.pi * dt.hour / 24),
        "time_dow": dt.weekday(),
        "time_since_last_tx": time_since_last_tx,
    }


@celery_app.task(name="app.tasks.score_transaction", bind=True, max_retries=3)
def score_transaction(self, envelope: dict):
    """
    Runs in a Celery worker, outside the request/response cycle. Two
    independent scoring engines run on every transaction:
      1. The rules engine (velocity / geo-spread / amount threshold),
         with per-org dynamic thresholds cached in Redis.
      2. The ML anomaly model, which catches patterns no rule covers.
    Neither is blended into the other - each can independently trigger a
    decision (an "OR-gate"), because diluting a real ML signal into a
    linear blend can make it too weak to ever matter (see docs/ML_DESIGN.md
    for why this changed from an earlier blended design).
    """
    try:
        org_id = envelope["org_id"]
        user_ref = envelope["user_ref"]
        country = envelope["country"]
        amount = envelope["amount"]
        now = datetime.fromisoformat(envelope["received_at"]).timestamp()

        # --- Manual override check first - bypasses everything else ---
        if sync_redis_client.get(allowlist_key(org_id, user_ref)):
            status_value, ml_result_tier, ml_score, rules_score = "clear", "clean", 0.0, 0.0
            reasons = {"manual_override": "User is on the temporary allowlist"}
            model_version, feature_dict = None, None
        else:
            rules = _load_rules(org_id)
            window = max((r["window_seconds"] for r in rules), default=120)
            tx_count, countries = _record_velocity(org_id, user_ref, country, window)
            rules_score, reasons = _rules_score(rules, amount, tx_count, len(countries))

            lifetime_features = _fetch_and_update_lifetime_state(org_id, user_ref, country, amount, now)
            feature_dict = {
                **lifetime_features,
                "velocity_120s": tx_count,
                "geo_countries_120s": len(countries),
            }
            ml_result = ml_scorer.score(feature_dict)
            ml_score, ml_result_tier, model_version = ml_result.probability, ml_result.tier, ml_result.model_version

            if rules_score >= 0.5:
                status_value = "flagged"
            elif ml_result_tier == "block":
                status_value = "flagged"
                reasons["ml_signal"] = f"ML anomaly probability {ml_score:.1%} - independent model signal, no rule matched"
            elif ml_result_tier == "challenge":
                status_value = "challenged"
                reasons["ml_signal"] = f"ML anomaly probability {ml_score:.1%} - elevated but below the block threshold"
            else:
                status_value = "clear"

        session = SyncSession()
        try:
            tx = Transaction(
                id=uuid.UUID(envelope["id"]),
                org_id=uuid.UUID(org_id),
                user_ref=user_ref,
                amount=amount,
                currency=envelope["currency"],
                country=country,
                merchant=envelope.get("merchant"),
                status=status_value,
                risk_score=rules_score,
                risk_reasons=reasons,
                ml_score=ml_score,
                ml_tier=ml_result_tier,
                ml_model_version=model_version,
                ml_features=feature_dict,
                scored_at=datetime.utcnow(),
                idempotency_key=envelope.get("idempotency_key"),
            )
            session.add(tx)
            try:
                session.commit()
            except IntegrityError:
                # Same idempotency key already scored (e.g. a worker crashed
                # after committing but before acking, so the task was
                # redelivered) - this transaction was already processed,
                # nothing further to do.
                session.rollback()
                log.info("transaction.duplicate_skipped", tx_id=envelope["id"])
                return

            payload = {
                "id": str(tx.id),
                "org_id": str(tx.org_id),
                "user_ref": tx.user_ref,
                "amount": tx.amount,
                "currency": tx.currency,
                "country": tx.country,
                "merchant": tx.merchant,
                "status": tx.status,
                "risk_score": tx.risk_score,
                "risk_reasons": tx.risk_reasons,
                "ml_score": tx.ml_score,
                "ml_tier": tx.ml_tier,
                "ml_model_version": tx.ml_model_version,
                "created_at": tx.created_at.isoformat(),
                "scored_at": tx.scored_at.isoformat(),
                "reviewed_status": tx.reviewed_status,
                "reviewed_by": tx.reviewed_by,
                "reviewed_at": None,
            }
        finally:
            session.close()

        # Broadcast on the org's own channel so tenants only ever see their
        # own transactions, never another org's live feed.
        sync_redis_client.publish(f"{settings.redis_pubsub_channel}:{org_id}", json.dumps(payload))
        log.info("transaction.scored", id=str(tx.id), status=status_value, rules_score=rules_score, ml_score=ml_score, ml_tier=ml_result_tier)

    except Exception as exc:
        log.error("transaction.score_failed", error=str(exc), tx_id=envelope.get("id"))
        raise self.retry(exc=exc, countdown=2**self.request.retries)
