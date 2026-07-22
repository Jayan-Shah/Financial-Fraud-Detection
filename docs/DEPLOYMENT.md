# Deployment Guide

Goal: a live URL you can put on your resume/LinkedIn, for free or near-free.

## Recommended combo (free tier, ~15 min)

| Piece | Service | Why |
|---|---|---|
| Postgres + Redis + backend + worker | [Railway](https://railway.app) | Reads your `docker-compose.yml`-style setup natively, free trial credit, easiest for multi-service Python apps |
| Frontend | [Vercel](https://vercel.com) or [Netlify](https://netlify.com) | Free static hosting, auto-deploys from GitHub on every push |

You can also run 100% on Railway (it can host the frontend as a static site
too) if you'd rather manage one dashboard instead of two.

### 1. Push to GitHub first (see below), then:

### 2. Backend + worker + Postgres + Redis on Railway
1. New Project → **Deploy from GitHub repo** → pick this repo.
2. Add a **Postgres** plugin and a **Redis** plugin (one click each).
3. Railway will detect `backend/Dockerfile` — set the service root directory
   to `backend/`.
4. Add a second service from the same repo for the Celery worker: same root
   directory (`backend/`), but override the start command to
   `sh -c "cd app/ml && python train_pipeline.py; cd ../.. && celery -A app.celery_app worker --loglevel=info"`
   (the ML model artifact isn't committed to git - see `.gitignore` - so it's
   trained once at container startup instead; it's deterministic with a fixed
   seed and takes under a minute, so this is a fine tradeoff for a portfolio
   deploy. If you'd rather not retrain on every deploy, train locally and
   `git add -f backend/app/ml/fraud_model_artifact.joblib` to commit it
   despite the gitignore rule, then drop the training step from the command.)
5. Set environment variables on both services (Railway auto-fills
   `DATABASE_URL`/`REDIS_URL` if you reference the plugins — otherwise copy
   the values from `backend/.env.example` and point them at Railway's
   Postgres/Redis connection strings). Set `JWT_SECRET` to a long random
   value — don't reuse the example.
6. On the backend service, set the start command to:
   `sh -c "alembic upgrade head && python -m app.seed && cd app/ml && python train_pipeline.py; cd ../.. && uvicorn app.main:app --host 0.0.0.0 --port $PORT"`
7. Deploy. Note the public URL Railway gives the backend service
   (something like `https://your-app.up.railway.app`).
8. Check the backend service's deploy logs for the line
   `Organization API key: sk_live_...` (printed by `python -m app.seed`) —
   you'll need it for the mock generator or any direct API testing.

### 3. Frontend on Vercel
1. New Project → import the same GitHub repo → set root directory to
   `frontend/`.
2. Build command: `npm run build`, output directory: `dist`.
3. Add a rewrite so `/api` and `/ws` point at your Railway backend URL
   instead of `localhost` — easiest is to add a `vercel.json` in
   `frontend/`:
   ```json
   {
     "rewrites": [
       { "source": "/api/:path*", "destination": "https://your-app.up.railway.app/api/:path*" },
       { "source": "/ws/:path*", "destination": "https://your-app.up.railway.app/ws/:path*" }
     ]
   }
   ```
   (Vercel doesn't proxy WebSockets through rewrites reliably — if `/ws`
   doesn't connect, point `websocketMiddleware.ts` directly at
   `wss://your-app.up.railway.app/ws/transactions` instead of
   `window.location.host` and skip the ws rewrite.)
4. Deploy. You now have a public frontend URL.

### 4. Turn on the mock generator
Add one more Railway service from `mock-data-generator/`, with
`TARGET_URL=https://your-app.up.railway.app/api/transactions/` and
`ORG_API_KEY=<the key from step 2.8>`. This keeps
live data flowing so the demo looks alive when someone opens the link.

## Fully local alternative (no cloud account needed)

```bash
git clone <your-repo-url>
cd fraud-detection-platform
docker compose -f infra/docker-compose.yml up --build
```

Then open http://localhost — log in with the seeded admin
(`admin@frauddetect.dev` / `ChangeMe123!` — **change this password before
ever deploying publicly**, see `backend/app/seed.py`).

## Publishing to GitHub

From the project root:

```bash
git init
git add .
git commit -m "Initial commit: real-time fraud detection platform"
git branch -M main
git remote add origin https://github.com/<your-username>/fraud-detection-platform.git
git push -u origin main
```

Then, on the repo's GitHub page: add a description, topics
(`fastapi`, `react`, `redux-toolkit`, `celery`, `websockets`, `fraud-detection`),
and pin it on your profile. Put the live Vercel URL in the repo's "About"
website field — that's the link recruiters click first.
