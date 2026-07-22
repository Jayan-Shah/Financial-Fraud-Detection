import os
from celery import Celery

from app.config import settings

# --- RENDER / UPSTASH REDIS FIX ---
# Grab the Upstash URL from Render's environment. 
# Using the same URL for both ensures we stay on Database 0 (required by Upstash Free Tier).
redis_url = os.getenv("REDIS_URL", settings.celery_broker_url)
# ----------------------------------

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