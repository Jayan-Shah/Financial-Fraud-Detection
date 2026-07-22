# Sentinel — Real-Time Fraud Intelligence Platform

A production-shaped, multi-tenant fraud detection system: transactions
stream in continuously, get scored by **two independent engines** (a
dynamic rules engine and a trained ML anomaly model), and land in a live,
virtualized dashboard — with a full analyst workflow (drill-down,
explainability, review, manual override) and compliance-controlled rule
thresholds that update live, no redeploy required.



## Why this exists

Most portfolio CRUD apps are request/response: click a button, wait, see
data. This one is built around continuous data flow instead — the harder,
more realistic problem for a payments/fraud system, where a burst of
transactions across several countries in two minutes has to get caught the
moment it happens, not in tomorrow's batch report. And a single rules
engine only catches fraud patterns someone already thought to write a rule
for — so this system pairs it with a trained ML model that catches
patterns no rule covers, and the two operate independently rather than
being diluted into one blended score (see `docs/ML_DESIGN.md` for why that
distinction matters).

## Features

**Detection**
- **Two independent scoring engines, OR-gated, not blended** — a dynamic
  rules engine (velocity / geo-spread / amount, tuned live by compliance)
  and a trained LightGBM anomaly model; either can independently trigger
  a decision, so a real ML signal never gets diluted into irrelevance
- **Three-tier decision engine**: `clear` → `challenged` (step-up auth) →
  `flagged` (block), plus a manual allowlist override that bypasses both
  engines entirely
- **Explainability on demand** — click any flagged/challenged transaction
  to see exactly which rule(s) fired and, via a separate on-demand call,
  the ML model's actual per-feature contributions (TreeSHAP-equivalent)

**Analyst workflow**
- **Live transaction feed** — thousands of scored transactions/sec worth
  of throughput without the UI freezing, via a virtualized grid
- **Analyst feedback loop** — mark a transaction Confirmed Fraud or False
  Positive; this is the human-in-the-loop signal a real system would feed
  back into retraining
- **Manual allowlist** — clear a user for 24h (or custom window),
  bypassing both engines, for confirmed false positives or VIPs
- **"Simulate Fraud Burst" button** — one click triggers a realistic
  multi-country burst server-side; no terminal or script needed for a demo
- **Reports dashboard** — flag/challenge rates, rules-vs-ML score
  distributions, review outcomes, transactions by country

**Platform**
- **Multi-tenant** — every user, transaction, rule, and allowlist entry
  belongs to an Organization; ingestion is authenticated by a per-org API
  key (separate from analyst JWT auth), and the live WebSocket feed is
  scoped so one tenant never sees another's data
- **JWT auth**, two roles (`analyst` read-only, `compliance_admin` can
  also edit rules), login rate limiting
- **Idempotency keys** on ingestion — a retried POST after a network blip
  doesn't get double-scored
- **Guest/demo login** — a one-click read-only sign-in, no credentials needed

## Stack

| Layer | Choice |
|---|---|
| API | FastAPI (async), Pydantic validation |
| Async work | Celery + Redis broker |
| Real-time push | WebSockets + per-org Redis pub/sub fan-out |
| Database | PostgreSQL + SQLAlchemy 2.0 (async) + Alembic migrations |
| ML | LightGBM, isotonic calibration, temporal-split training (`backend/app/ml/`) |
| Frontend | React + TypeScript + Redux Toolkit |
| Live grid | TanStack Virtual (renders 1,000s of rows without lag) |
| Charts / icons | Recharts, lucide-react |
| Auth | JWT (analyst) + API key (ingestion), role-based |
| Infra | Docker Compose, Nginx (reverse proxy + WS upgrade handling) |
| Logging | structlog (structured JSON logs) |
| CI | GitHub Actions — lint + test on every push |

## How a transaction actually moves through the system

1. **Ingestion** — `POST /api/transactions`, authenticated by an org API
   key, validates via Pydantic and returns `202 Accepted` immediately —
   never blocks on scoring.
2. **Async handoff** — dispatched to Celery over Redis.
3. **Two independent engines score it** in the worker:
   - The **rules engine** reads live per-org thresholds from a Redis
     cache and checks velocity/geo-spread/amount.
   - The **ML model** computes a feature vector (amount deviation from
     the user's own baseline, velocity, geo-rarity, time patterns) from
     Redis state and produces a calibrated fraud probability.
4. **OR-gate decision** — rules hard-stop, ML block, ML challenge, or
   clear, checked in that order (see `docs/ML_DESIGN.md`).
5. **Persisted + broadcast** — written to Postgres, published on the
   org's own Redis pub/sub channel.
6. **WebSocket relay** — authenticated by JWT (as a query param, since
   browsers can't attach headers to a WS upgrade), subscribes to the
   caller's org channel only.
7. **Redux middleware** dispatches incoming transactions straight into
   the store; a **virtualized grid** renders only the visible rows,
   keyed by position (not id) so the DOM is reused, not rebuilt, on
   every incoming row.
8. **Click any row** for rule + ML explainability, review actions, and
   the allowlist override.

Full architecture diagram: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
ML design and decision-engine rationale: [`docs/ML_DESIGN.md`](docs/ML_DESIGN.md).

## Project layout

```
backend/
  app/
    ml/            training pipeline, inference, and design notes for the ML layer
    routers/       auth, transactions, rules, websocket
    tasks.py       the Celery worker - rules + ML scoring, OR-gate decision
    models.py      Organization, User, Transaction, FraudRule, AllowlistEntry
  alembic/         migrations (0001 schema, 0002 review+idempotency, 0003 multi-tenancy+ML)
  tests/
frontend/
  src/
    components/    Sidebar, Overview, TransactionGrid, TransactionDetail, Reports, AdminDashboard
    features/      Redux slices (transactions, rules, auth)
    middleware/    the WebSocket-owning Redux middleware
infra/             docker-compose.yml wiring every service together
mock-data-generator/   fires synthetic transactions at the API
.github/workflows/     CI: lint + test on every push
docs/              architecture, ML design, and deployment guides
```

## Running it locally (Docker)

```bash
git clone https://github.com/<your-username>/fraud-detection-platform.git
cd fraud-detection-platform
docker compose -f infra/docker-compose.yml up --build
```

- Frontend: http://localhost
- Backend docs (Swagger): http://localhost:8000/docs
- Seeded logins (see `backend/app/seed.py`):
  - Compliance admin: `admin@frauddetect.dev` / `ChangeMe123!`
  - Read-only demo analyst: `demo@frauddetect.dev` / `demo-view-only`
    (also reachable via the "View Demo" button on the login screen)
  (**change the admin password before deploying publicly**)

**Note: the ML model artifact isn't built by Docker automatically** — see
"Training the ML model" below. Without it, the system runs on rules alone
(the ML layer fails open, logging a warning, never blocking scoring).

**To run the mock generator**, grab the org API key from the backend's
logs after it seeds (`docker compose logs backend | grep "API key"`),
put it in `infra/.env` as `ORG_API_KEY=...`, then
`docker compose up -d mock-generator`.

## Training the ML model

The trained artifact isn't committed (it's a regenerable build output, see
`.gitignore`) — train it once locally:

```bash
cd backend/app/ml
python3 -m venv venv
source  venv/bin/activate
pip install -r ../../requirements.txt
python train_pipeline.py
python test_inference.py   # confirms latency + sanity checks pass
```

This writes `fraud_model_artifact.joblib` into `backend/app/ml/`, where
the Celery worker expects to find it. **Restart the worker** after
training/retraining — the model loads once at process startup.

Full walkthrough of the training methodology, the four real bugs hit and
fixed along the way, and how to read the output: [`backend/app/ml/README.md`](backend/app/ml/README.md).

## Running it locally without Docker (dev mode)

```bash
cd infra
docker compose up -d postgres redis
```

Create `backend/.env` (gitignored):
```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/fraud_db
SYNC_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/fraud_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
JWT_SECRET=dev-secret-change-later
CORS_ORIGINS=http://localhost:5173
```

```bash
# backend - use a dedicated venv to avoid multi-Python/conda conflicts
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.seed          # prints the org's API key - save it
cd app/ml && python train_pipeline.py && cd ../..   # train the ML model
uvicorn app.main:app --reload

# celery worker (separate terminal, same venv)
celery -A app.celery_app worker --loglevel=info --pool=solo

# frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Mock generator (optional, separate terminal):
```bash
cd mock-data-generator
pip install -r requirements.txt
ORG_API_KEY=<the key seed.py printed> TARGET_URL=http://localhost:8000/api/transactions/ python3 generate.py
```

## Tests

```bash
cd backend && pytest
cd frontend && npm test
```

## Troubleshooting

- **ML model won't load / worker logs `ml_model.load_failed`** — you
  haven't trained it yet. See "Training the ML model" above. The system
  keeps running on rules alone until the artifact exists.
- **`401` on `POST /api/transactions`** — ingestion needs the
  `X-Org-Api-Key` header, not a JWT. Get the key from
  `python -m app.seed`'s output (or backend logs, in Docker).
- **`ValueError: password cannot be longer than 72 bytes` on login, or a
  bare 500 with `AttributeError: module 'bcrypt' has no attribute
  '__about__'`** — a version mismatch between `passlib` and newer
  `bcrypt` (4.1+). `requirements.txt` pins `bcrypt==4.0.1` to avoid this.
- **Already had this running before and just pulled these changes?** Run
  `alembic upgrade head` again — migration `0003` adds multi-tenancy, the
  ML columns, and the allowlist table, and backfills a default
  organization for any existing data so nothing breaks.
- **`could not translate host name "postgres"`** — that hostname only
  resolves *inside* the Docker Compose network. Running the app directly
  needs `backend/.env` pointing at `localhost`, not `postgres`.
- **`port is already allocated` on `5432`** — something else on your
  machine is already bound to it. Remap this project's Postgres to a
  different host port in `infra/docker-compose.yml` and update
  `backend/.env` to match (default here is already remapped to `5433`).

## Deploying it live + pushing to GitHub

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for a free-tier Railway +
Vercel walkthrough and the exact `git` commands to publish this repo.

## License

MIT — see [`LICENSE`](LICENSE).
