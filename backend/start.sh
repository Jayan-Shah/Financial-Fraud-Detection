#!/bin/sh
set -e

echo "==> Running database migrations..."
alembic upgrade head

echo "==> Seeding database..."
python -m app.seed

echo "==> Starting Celery worker in background..."
celery -A app.celery_app worker --loglevel=info &

echo "==> Starting FastAPI web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}