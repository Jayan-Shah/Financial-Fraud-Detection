<div align="center">

# 🛡️ Sentinel
### Real-Time Fraud Intelligence Platform

A production-shaped, multi-tenant fraud detection system that streams transactions through **two independent scoring engines** — a live, compliance-tunable rules engine and a trained ML anomaly model — and surfaces every decision in a real-time analyst dashboard.

[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows)
[![Python](https://img.shields.io/badge/Python-FastAPI-009688?logo=fastapi&logoColor=white)](backend)
[![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=white)](frontend)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Live Demo](#) · [Quick Start](#-quick-start) · [Architecture](#-architecture) · [Docs](#-documentation)

</div>

---

## 📌 Why This Exists

Most portfolio projects are simple request/response CRUD apps — click a button, wait, see data. **Sentinel is built around continuous data flow instead**, because that's the harder and more realistic problem in payments and fraud: a burst of transactions across several countries in two minutes has to be caught the moment it happens, not in tomorrow's batch report.

It also reflects a real production decision: a single rules engine only catches fraud patterns someone already thought to write a rule for. So Sentinel pairs it with a **trained ML model** that catches patterns no rule covers — and the two engines operate **independently**, never diluted into one blended score. *(Full reasoning in [`docs/ML_DESIGN.md`](docs/ML_DESIGN.md).)*

---

## ✨ Features

### 🔍 Detection
| Feature | Detail |
|---|---|
| **Dual scoring engines** | A dynamic **rules engine** (velocity / geo-spread / amount, tuned live by compliance) + a trained **LightGBM anomaly model** — either can independently trigger a decision |
| **Three-tier decisions** | `clear` → `challenged` (step-up auth) → `flagged` (block), plus a manual **allowlist override** that bypasses both engines |
| **On-demand explainability** | Click any flagged/challenged transaction to see which rule(s) fired, and pull the ML model's per-feature contributions (TreeSHAP-equivalent) |

### 👩‍💻 Analyst Workflow
- **Live transaction feed** — thousands of scored transactions/sec via a virtualized grid, without freezing the UI
- **Feedback loop** — mark a transaction *Confirmed Fraud* / *False Positive*, the human-in-the-loop signal a real system would feed back into retraining
- **Manual allowlist** — clear a user for 24h (or custom window) for confirmed false positives or VIPs
- **"Simulate Fraud Burst"** — one click triggers a realistic multi-country burst server-side, no terminal needed for a demo
- **Reports dashboard** — flag/challenge rates, rules-vs-ML score distributions, review outcomes, transactions by country

### 🏗️ Platform
- **Multi-tenant** — every user, transaction, rule, and allowlist entry belongs to an Organization; ingestion uses a per-org API key; the WebSocket feed is scoped so no tenant ever sees another's data
- **JWT auth**, two roles (`analyst` read-only, `compliance_admin` can edit rules), with login rate limiting
- **Idempotency keys** on ingestion — a retried POST after a network blip is never double-scored
- **Guest/demo login** — one-click read-only sign-in, no credentials required

---

## 🧱 Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI (async), Pydantic validation |
| **Async work** | Celery + Redis broker |
| **Real-time push** | WebSockets + per-org Redis pub/sub fan-out |
| **Database** | PostgreSQL + SQLAlchemy 2.0 (async) + Alembic migrations |
| **ML** | LightGBM, isotonic calibration, temporal-split training (`backend/app/ml/`) |
| **Frontend** | React + TypeScript + Redux Toolkit |
| **Live grid** | TanStack Virtual (renders 1,000s of rows without lag) |
| **Charts / icons** | Recharts, lucide-react |
| **Auth** | JWT (analyst) + API key (ingestion), role-based |
| **Infra** | Docker Compose, Nginx (reverse proxy + WS upgrade handling) |
| **Logging** | structlog (structured JSON logs) |
| **CI** | GitHub Actions — lint + test on every push |

---

## 🏛️ Architecture

```mermaid
flowchart LR
    subgraph Client["🖥️ Frontend"]
        UI[React + Redux Toolkit]
        Grid[Virtualized Transaction Grid]
        WSClient[WebSocket Middleware]
    end

    subgraph API["⚙️ FastAPI Backend"]
        Ingest["POST /api/transactions<br/>(API key auth)"]
        WSServer["WebSocket Relay<br/>(JWT auth)"]
    end

    subgraph Async["🔄 Async Layer"]
        Redis[(Redis<br/>Broker + Cache + PubSub)]
        Celery[Celery Worker]
    end

    subgraph Engines["🧠 Scoring Engines"]
        Rules["Rules Engine<br/>velocity / geo / amount"]
        ML["LightGBM Model<br/>calibrated fraud probability"]
    end

    subgraph Store["🗄️ Persistence"]
        PG[(PostgreSQL)]
    end

    Ingest -->|"202 Accepted<br/>(never blocks)"| Celery
    Celery <--> Redis
    Celery --> Rules
    Celery --> ML
    Rules -->|OR-gate decision| PG
    ML -->|OR-gate decision| PG
    PG --> Redis
    Redis -->|"org-scoped pub/sub"| WSServer
    WSServer --> WSClient
    WSClient --> UI
    UI --> Grid

    style Rules fill:#fde68a,stroke:#b45309
    style ML fill:#bfdbfe,stroke:#1d4ed8
    style PG fill:#d1fae5,stroke:#047857
```

📄 Full architecture diagram & rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
🧠 ML design & decision-engine logic: [`docs/ML_DESIGN.md`](docs/ML_DESIGN.md)

---

## 🔁 How a Transaction Actually Moves Through the System

```mermaid
sequenceDiagram
    participant C as Ingestion Client
    participant API as FastAPI
    participant Q as Celery / Redis
    participant R as Rules Engine
    participant M as ML Model
    participant DB as PostgreSQL
    participant WS as WebSocket Relay
    participant UI as Analyst Dashboard

    C->>API: POST /api/transactions (org API key)
    API-->>C: 202 Accepted (immediate, non-blocking)
    API->>Q: Dispatch job

    par Independent scoring
        Q->>R: Read live thresholds (Redis cache)
        R-->>Q: velocity / geo-spread / amount check
    and
        Q->>M: Build feature vector from Redis state
        M-->>Q: Calibrated fraud probability
    end

    Q->>Q: OR-gate decision<br/>(rules hard-stop → ML block → ML challenge → clear)
    Q->>DB: Persist transaction + decision
    Q->>WS: Publish on org's Redis pub/sub channel
    WS->>UI: Push to subscribed org (JWT-scoped)
    UI->>UI: Redux middleware → virtualized grid update

    Note over UI: Analyst clicks row →<br/>rule explainability + on-demand SHAP + review actions
```

**Step-by-step:**
1. **Ingestion** — `POST /api/transactions`, authenticated by an org API key, validated via Pydantic, returns `202 Accepted` immediately — never blocks on scoring.
2. **Async handoff** — dispatched to Celery over Redis.
3. **Two engines score it independently** in the worker — rules reads live per-org thresholds from Redis; ML builds a feature vector (amount deviation from baseline, velocity, geo-rarity, time patterns) and returns a calibrated probability.
4. **OR-gate decision** — checked in order: rules hard-stop → ML block → ML challenge → clear.
5. **Persisted + broadcast** — written to Postgres, published on the org's own Redis pub/sub channel.
6. **WebSocket relay** — JWT-authenticated (as a query param, since browsers can't attach headers to a WS upgrade), scoped to the caller's org channel only.
7. **Redux middleware** dispatches incoming transactions into the store; a **virtualized grid** renders only visible rows, keyed by position (not id), so the DOM is reused rather than rebuilt on every incoming row.
8. **Click any row** for rule + ML explainability, review actions, and the allowlist override.

---

## 🎯 Decision Engine Logic

```mermaid
flowchart TD
    Start(["Transaction Scored"]) --> RuleCheck{"Rules Engine:<br/>hard-stop triggered?"}
    RuleCheck -->|Yes| Flagged["🚫 FLAGGED<br/>(blocked)"]
    RuleCheck -->|No| MLCheck1{"ML Model:<br/>block threshold?"}
    MLCheck1 -->|Yes| Flagged
    MLCheck1 -->|No| MLCheck2{"ML Model:<br/>challenge threshold?"}
    MLCheck2 -->|Yes| Challenged["⚠️ CHALLENGED<br/>(step-up auth)"]
    MLCheck2 -->|No| Clear["✅ CLEAR"]

    Allowlist["🔓 Manual Allowlist"] -.->|bypasses both engines| Clear

    style Flagged fill:#fecaca,stroke:#b91c1c
    style Challenged fill:#fde68a,stroke:#b45309
    style Clear fill:#bbf7d0,stroke:#15803d
    style Allowlist fill:#e0e7ff,stroke:#4338ca
```

---

## 📁 Project Layout

```
backend/
├── app/
│   ├── ml/            # training pipeline, inference, design notes for the ML layer
│   ├── routers/        # auth, transactions, rules, websocket
│   ├── tasks.py         # Celery worker — rules + ML scoring, OR-gate decision
│   └── models.py       # Organization, User, Transaction, FraudRule, AllowlistEntry
├── alembic/            # migrations (0001 schema, 0002 review+idempotency, 0003 multi-tenancy+ML)
└── tests/

frontend/
└── src/
    ├── components/     # Sidebar, Overview, TransactionGrid, TransactionDetail, Reports, AdminDashboard
    ├── features/       # Redux slices (transactions, rules, auth)
    └── middleware/      # the WebSocket-owning Redux middleware

infra/                  # docker-compose.yml wiring every service together
mock-data-generator/    # fires synthetic transactions at the API
.github/workflows/      # CI: lint + test on every push
docs/                   # architecture, ML design, and deployment guides
```

---

## 🚀 Quick Start (Docker)

```bash
git clone https://github.com/<your-username>/fraud-detection-platform.git
cd fraud-detection-platform
docker compose -f infra/docker-compose.yml up --build
```

| Resource | URL |
|---|---|
| Frontend | http://localhost |
| Backend docs (Swagger) | http://localhost:8000/docs |

**Seeded logins** (see [`backend/app/seed.py`](backend/app/seed.py)):

| Role | Email | Password |
|---|---|---|
| Compliance admin | `admin@frauddetect.dev` | `ChangeMe123!` |
| Read-only demo analyst | `demo@frauddetect.dev` | `demo-view-only` (or click **"View Demo"** on the login screen) |

> ⚠️ **Change the admin password before deploying publicly.**

> ℹ️ **Note:** the ML model artifact isn't built by Docker automatically — see [Training the ML Model](#-training-the-ml-model) below. Without it, the system runs on rules alone (the ML layer *fails open*, logging a warning, never blocking scoring).

**To run the mock generator**, grab the org API key from the backend's logs after it seeds:
```bash
docker compose logs backend | grep "API key"
```
Put it in `infra/.env` as `ORG_API_KEY=...`, then:
```bash
docker compose up -d mock-generator
```

---

## 🧠 Training the ML Model

The trained artifact isn't committed (it's a regenerable build output — see `.gitignore`). Train it once locally:

```bash
cd backend/app/ml
python3 -m venv venv
source venv/bin/activate
pip install -r ../../requirements.txt
python train_pipeline.py
python test_inference.py   # confirms latency + sanity checks pass
```

This writes `fraud_model_artifact.joblib` into `backend/app/ml/`, where the Celery worker expects to find it.

> ⚠️ **Restart the worker** after training/retraining — the model loads once at process startup.

📄 Full training methodology, the four real bugs hit and fixed along the way, and how to read the output: [`backend/app/ml/README.md`](backend/app/ml/README.md)

---

## 🛠️ Running Without Docker (Dev Mode)

**1. Start infra dependencies**
```bash
cd infra
docker compose up -d postgres redis
```

**2. Create `backend/.env`** (gitignored)
```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/fraud_db
SYNC_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/fraud_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
JWT_SECRET=dev-secret-change-later
CORS_ORIGINS=http://localhost:5173
```

**3. Backend** — use a dedicated venv to avoid multi-Python/conda conflicts
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.seed          # prints the org's API key — save it
cd app/ml && python train_pipeline.py && cd ../..   # train the ML model
uvicorn app.main:app --reload
```

**4. Celery worker** (separate terminal, same venv)
```bash
celery -A app.celery_app worker --loglevel=info --pool=solo
```

**5. Frontend** (separate terminal)
```bash
cd frontend
npm install
npm run dev
```

**6. Mock generator** (optional, separate terminal)
```bash
cd mock-data-generator
pip install -r requirements.txt
ORG_API_KEY=<the key seed.py printed> TARGET_URL=http://localhost:8000/api/transactions/ python3 generate.py
```

---

## 🧪 Tests

```bash
cd backend && pytest
cd frontend && npm test
```

CI runs lint + tests on every push via GitHub Actions — see [`.github/workflows`](.github/workflows).

---

## 🩹 Troubleshooting

| Symptom | Fix |
|---|---|
| **ML model won't load** / worker logs `ml_model.load_failed` | You haven't trained it yet — see [Training the ML Model](#-training-the-ml-model). The system keeps running on rules alone until the artifact exists. |
| **`401` on `POST /api/transactions`** | Ingestion needs the `X-Org-Api-Key` header, not a JWT. Get the key from `python -m app.seed`'s output (or backend logs, in Docker). |
| **`ValueError: password cannot be longer than 72 bytes`**, or a bare `500` with `AttributeError: module 'bcrypt' has no attribute '__about__'` | Version mismatch between `passlib` and newer `bcrypt` (4.1+). `requirements.txt` pins `bcrypt==4.0.1` to avoid this. |
| **Already had this running and just pulled changes?** | Run `alembic upgrade head` again — migration `0003` adds multi-tenancy, ML columns, and the allowlist table, and backfills a default organization so nothing breaks. |
| **`could not translate host name "postgres"`** | That hostname only resolves *inside* the Docker Compose network. Running the app directly needs `backend/.env` pointing at `localhost`, not `postgres`. |
| **`port is already allocated` on `5432`** | Something else is already bound to it. Remap this project's Postgres to a different host port in `infra/docker-compose.yml` and update `backend/.env` to match (default here is already remapped to `5433`). |

---

## 📚 Documentation

| Doc | Covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full system architecture diagram |
| [`docs/ML_DESIGN.md`](docs/ML_DESIGN.md) | Why the two engines stay independent, decision-engine rationale |
| [`backend/app/ml/README.md`](backend/app/ml/README.md) | ML training methodology, bugs hit & fixed, reading the output |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Free-tier Railway + Vercel deployment walkthrough |

---

## 🚢 Deploying It Live

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for a free-tier Railway + Vercel walkthrough and the exact `git` commands to publish this repo.

---

## 📄 License

MIT — see [`LICENSE`](LICENSE).

---

<div align="center">

*Built to demonstrate real-time, event-driven system design — not just another CRUD app.*

</div>
