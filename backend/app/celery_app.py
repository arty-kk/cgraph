#backend/app/celery_app.py
from __future__ import annotations

from celery import Celery

from .config import settings

celery_app = Celery("stubgraph", broker=settings.celery_broker_url)
celery_app.conf.task_default_queue = settings.celery_queue_default or "medium"
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_backend = None
celery_app.conf.task_routes = {
    "stubgraph.scan": {"queue": "medium"},
    "stubgraph.docs": {"queue": "light"},
    "stubgraph.run_task": {"queue": "heavy"},
}
