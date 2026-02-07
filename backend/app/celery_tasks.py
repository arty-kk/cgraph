# backend/app/celery_tasks.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from redis import RedisError

from .celery_app import celery_app
from .db import get_session
from .infra.redis_client import get_redis_client
from .logging import get_logger
from .models import TaskJob
from .services.docs_service import build_project_docs
from .services.project_service import _scan_and_update_graph
from .services.task_service import TaskRequest, run_task

logger = get_logger("stubgraph.celery")


def _set_job_status(
    job_id: str,
    status: str,
    *,
    org_id: int | None = None,
    result: Any | None = None,
    error: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        job = session.get(TaskJob, job_id)
        if not job:
            if org_id is None:
                raise RuntimeError("org_id обязателен для создания задачи")
            job = TaskJob(id=job_id, org_id=org_id, status=status)
            session.add(job)
        job.status = status
        job.updated_at = now
        if status == "running":
            _touch_inflight(job.queue, job.id)
        if status in {"succeeded", "failed"}:
            job.completed_at = now
            _decrement_inflight(job.queue, job.id)
        if error is not None:
            job.error = error
        if result is not None:
            job.result_json = json.dumps(result, ensure_ascii=False)
        session.add(job)
        session.commit()


@celery_app.task(name="stubgraph.scan")
def scan_task(job_id: str, project_id: int, org_id: int) -> None:
    _set_job_status(job_id, "running", org_id=org_id)
    try:
        result = _scan_and_update_graph(project_id, org_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scan task failed", extra={"job_id": job_id})
        _set_job_status(job_id, "failed", org_id=org_id, error=str(exc))
        return
    _set_job_status(job_id, "succeeded", org_id=org_id, result=result)


@celery_app.task(name="stubgraph.docs")
def docs_task(job_id: str, project_id: int, org_id: int) -> None:
    _set_job_status(job_id, "running", org_id=org_id)
    try:
        result = build_project_docs(project_id, org_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Docs task failed", extra={"job_id": job_id})
        _set_job_status(job_id, "failed", org_id=org_id, error=str(exc))
        return
    _set_job_status(job_id, "succeeded", org_id=org_id, result=result)


@celery_app.task(name="stubgraph.run_task")
def run_task_job(job_id: str, project_id: int, org_id: int, payload: dict) -> None:
    _set_job_status(job_id, "running", org_id=org_id)
    try:
        provided = payload.get("provided_fields")
        if isinstance(provided, list):
            payload["provided_fields"] = set(provided)
        request = TaskRequest(**payload)
        result = run_task(project_id, org_id, request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Run task failed", extra={"job_id": job_id})
        _set_job_status(job_id, "failed", org_id=org_id, error=str(exc))
        return
    _set_job_status(job_id, "succeeded", org_id=org_id, result=result)


def _touch_inflight(queue: str, job_id: str) -> None:
    if queue != "heavy":
        return
    try:
        client = get_redis_client()
        key = "stubgraph:queue:heavy:inflight"
        client.sadd(key, job_id)
    except RedisError as exc:
        logger.warning("Failed to refresh inflight job state", extra={"reason": str(exc)})


def _decrement_inflight(queue: str, job_id: str) -> None:
    if queue != "heavy":
        return
    try:
        client = get_redis_client()
        key = "stubgraph:queue:heavy:inflight"
        client.srem(key, job_id)
    except RedisError as exc:
        logger.warning("Failed to decrement inflight counter", extra={"reason": str(exc)})
