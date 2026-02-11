# backend/app/celery_app.py
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from .config import settings

celery_app = Celery("stubgraph", broker=settings.celery_broker_url)
celery_app.conf.task_default_queue = settings.celery_queue_default or "medium"
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_backend = None
celery_app.conf.task_routes = {
    "stubgraph.scan": {"queue": "medium"},
    "stubgraph.mutation_indexing": {"queue": "medium"},
    "stubgraph.docs": {"queue": "light"},
    "stubgraph.run_task": {"queue": "heavy"},
    "stubgraph.routing_calibration": {"queue": "light"},
}

if bool(getattr(settings, "llm_routing_calibration_enabled", False)):
    celery_app.conf.beat_schedule = {
        "routing-policy-calibration": {
            "task": "stubgraph.routing_calibration",
            "schedule": crontab(minute=f"*/{max(1, int(settings.llm_routing_calibration_interval_minutes))}"),
        }
    }
