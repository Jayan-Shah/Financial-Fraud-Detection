# Architecture

## Transaction lifecycle

```
payment gateway ──POST /api/transactions (X-Org-Api-Key)──▶ FastAPI (Pydantic validation)
                                                                    │
                                                          celery_app.send_task()
                                                                    ▼
                                                          Redis (Celery broker, db1)
                                                                    │
                                                                    ▼
                                                            Celery worker:
                                                    ┌───────────────┴────────────────┐
                                                    ▼                                 ▼
                                         RULES ENGINE                      ML ENGINE
                                    read live per-org thresholds      read/update per-user
                                    from Redis cache; check           lifetime stats + geo
                                    velocity/geo/amount                history in Redis;
                                                    │                  compute feature vector;
                                                    │                  score via LightGBM
                                                    └───────────────┬────────────────┘
                                                                    ▼
                                                     OR-GATE DECISION (see below)
                                                                    │
                                                    write result to Postgres
                                                                    │
                                                    PUBLISH to org's Redis pub/sub channel
                                                    "transactions.scored:{org_id}"
                                                                    │
                                                                    ▼
                                                    FastAPI /ws/transactions?token=<jwt>
                                                    (subscribes to caller's org channel only)
                                                                    │
                                                                    ▼
                                                    Browser WebSocket ──▶ Redux middleware
                                                                    │
                                                                    ▼
                                                    transactionsSlice.transactionReceived
                                                                    │
                                                                    ▼
                                                    TanStack-virtualized grid (React)
```

The API never touches scoring logic or the database in the request path —
it validates and hands off. That's what keeps `POST /api/transactions`
fast enough to sustain high throughput without falling behind.

## The OR-gate decision engine

Two scoring engines run on every transaction, independently:

```
1. Manual allowlist override (Redis key, org+user scoped) -> CLEAR, skip everything else
2. Rules score >= 0.5                                       -> FLAGGED
3. ML tier == "block"  (independent of rules)                -> FLAGGED
4. ML tier == "challenge"                                     -> CHALLENGED
5. Otherwise                                                   -> CLEAR
```

This is deliberately **not** a linear blend of the two scores. See
[`ML_DESIGN.md`](ML_DESIGN.md) for why a blend would risk diluting a real
ML signal into irrelevance, and how the `challenge`/`block` thresholds are
actually derived (from validation data, not guessed).

## Multi-tenancy

Every `User`, `Transaction`, `FraudRule`, and `AllowlistEntry` belongs to
exactly one `Organization`. Two different authentication mechanisms exist
for two different kinds of caller:

- **Analyst JWT auth** — a human logging into the dashboard. The JWT
  carries `role` and `org_id` claims; every query in the API is scoped by
  `current_user.org_id`, so one tenant's analyst can never see another
  tenant's transactions, rules, or reviews.
- **Org API key** — the ingestion endpoint's caller is a payment gateway
  or merchant system sending a transaction stream, not a human. It
  authenticates with a long-lived, org-scoped API key
  (`X-Org-Api-Key` header) instead.

The live WebSocket feed is scoped the same way: each org has its own
Redis pub/sub channel (`transactions.scored:{org_id}`), and the JWT
passed as a WebSocket query param determines which channel a given
connection subscribes to.

The Redis rules cache, velocity-tracking sorted sets, per-user lifetime
stats, and allowlist entries are all keyed by org as well — see
`app/redis_client.py` for the exact key scheme.

## Why Postgres AND Redis for rules

Postgres is the source of truth for `fraud_rules` — durable, queryable,
auditable. Redis holds a per-org JSON snapshot of the *enabled* rules that
Celery workers read on every transaction, because hitting Postgres per
transaction at throughput would be wasteful. Every write from the admin
dashboard (`PUT /api/rules/{id}`) writes to Postgres *and* refreshes the
Redis snapshot in the same request — so the next transaction scored uses
the new threshold, with no deploy and no restart.

## The ML layer's Redis state

Separate from the rules-engine's sliding-window sorted set
(`velocity:org:{org_id}:user:{user_ref}`), two more per-user Redis
structures feed the ML feature computation:

- `stats:org:{org_id}:user:{user_ref}` (hash) — lifetime transaction
  count, sum, and sum-of-squares (for a running mean/std, i.e.
  `amount_z_score`), and the last transaction's timestamp
- `geo:org:{org_id}:user:{user_ref}` (hash) — lifetime count per country
  (for `geo_country_rarity`)

Both are read *before* being updated in `_fetch_and_update_lifetime_state`
— the same fetch-then-update order the offline training replay assumes,
which is what keeps train/serve skew at zero. See
[`ML_DESIGN.md`](ML_DESIGN.md) for the full reasoning.

## Explainability: fast path vs. slow path

`MLScorer.score()` runs on every transaction and only returns a
probability + tier — kept fast (single-digit milliseconds). Full
per-feature explanation (`MLScorer.explain()`, LightGBM's native
`pred_contrib`) is **never** computed during scoring; it's exposed only
via `GET /api/transactions/{id}/ml-explain`, called on demand when an
analyst opens a transaction's detail view. The exact feature vector used
at scoring time is stored on the row (`Transaction.ml_features`)
specifically so this reconstructs real inputs, not a drifted
approximation from current state.

## Auth model

Two analyst roles: `analyst` (view live feed, reports, rules, review
transactions, use the allowlist) and `compliance_admin` (also
create/update/delete rules). Login is rate-limited (5 failed attempts
locks an email for 15 minutes, tracked in Redis).

## What's deliberately out of scope for v1

- Model versioning via MLflow, automated drift detection, scheduled
  retraining, and shadow deployment (real practices, discussed in
  `ML_DESIGN.md`, not built)
- Historical analytics beyond the client-side session buffer (Reports
  aggregates the last 5,000 buffered transactions, not the full
  historical table)
- Org self-service signup/management UI — organizations are created via
  the seed script or directly in the database
- Horizontal Celery worker autoscaling

These are natural "here's what I'd do next" talking points, not gaps to
hide.
