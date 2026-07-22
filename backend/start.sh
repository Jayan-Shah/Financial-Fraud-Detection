#!/bin/sh
set -e

echo "==> Configuring DB URL for Alembic migrations..."
# Create a synchronous connection string by stripping out '+asyncpg'
SYNC_DB_URL=$(echo $DATABASE_URL | sed 's/+asyncpg//')

# Inject the Render Neon URL into alembic.ini (overwriting the local 'postgres' one)
sed -i "s|^sqlalchemy\.url.*|sqlalchemy.url = ${SYNC_DB_URL}|" alembic.ini

echo "==> Running database migrations..."
alembic upgrade head

echo "==> Seeding database..."
python -m app.seed

echo "==> Training ML model pipeline..."
cd app/ml && python train_pipeline.py && cd ../..

echo "==> Starting Celery worker in background..."
celery -A app.celery_app worker --loglevel=info &

echo "==> Starting FastAPI web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}