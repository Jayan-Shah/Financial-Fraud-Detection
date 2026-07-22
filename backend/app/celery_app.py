import os
from celery import Celery

from app.config import settings

redis_url = os.getenv("REDIS_URL", settings.celery_broker_url)

# --- CELERY UPSTASH SSL FIX ---
# Celery strictly requires 'ssl_cert_reqs' when using secure 'rediss://' URLs
if redis_url and redis_url.startswith("rediss://") and "ssl_cert_reqs" not in redis_url:
    # Append the parameter (using ? if no other params exist, otherwise &)
    separator = "&" if "?" in redis_url else "?"
    redis_url += f"{separator}ssl_cert_reqs=CERT_NONE"
# ------------------------------

celery_app = Celery(
    "fraud_detection",
    broker=redis_url,
    backend=redis_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=4,
    task_acks_late=True,
)