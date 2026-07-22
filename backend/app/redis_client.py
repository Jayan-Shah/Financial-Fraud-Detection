import redis.asyncio as aioredis
import redis as sync_redis

from app.config import settings

# Async client - used by FastAPI (ingestion, websocket subscriber)
async_redis = aioredis.from_url(settings.redis_url, decode_responses=True)

# Sync client - used by Celery workers (no event loop there)
sync_redis_client = sync_redis.from_url(settings.redis_url, decode_responses=True)

TRANSACTION_QUEUE = "queue:transactions:ingest"

# Rules cache is per-org, not global - each tenant has its own thresholds.
def rules_cache_key(org_id: str) -> str:
    return f"cache:fraud_rules:{org_id}"

# Sliding-window velocity/geo-spread tracking (existing rules engine).
def velocity_key(org_id: str, user_ref: str) -> str:
    return f"velocity:org:{org_id}:user:{user_ref}"

# Lifetime per-user stats (running mean/std of amount, last tx time) - feeds
# the ML feature computation (amount_z_score, time_since_last_tx). Separate
# from the sliding-window key above since these never expire/trim.
def user_stats_key(org_id: str, user_ref: str) -> str:
    return f"stats:org:{org_id}:user:{user_ref}"

# Lifetime per-user country counts - feeds geo_country_rarity.
def user_geo_key(org_id: str, user_ref: str) -> str:
    return f"geo:org:{org_id}:user:{user_ref}"

# Manual override - customer support / compliance clearing a user for a
# window of time, bypassing rules and ML entirely.
def allowlist_key(org_id: str, user_ref: str) -> str:
    return f"allowlist:org:{org_id}:user:{user_ref}"

# Login brute-force protection.
def login_attempts_key(email: str) -> str:
    return f"login_attempts:{email.lower()}"

IDEMPOTENCY_KEY_PREFIX = "idempotency:ingest:"
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
