# backend/app/services/task_queue.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from redis import RedisError
from sqlmodel import select

from ..config import settings
from ..db import get_session
from ..errors import BadRequestError
from ..infra.redis_client import get_redis_client
from ..logging import get_logger
from ..models import TaskJob
from ..utils import sha256_text


@dataclass
class TaskState:
    status: str
    result: Any | None = None
    error: str | None = None
    completed_at: datetime | None = None


class TaskQueue:
    def submit_scan(self, project_id: int, org_id: int) -> str:
        payload = {"project_id": project_id}
        idempotency_key = _idempotency_key("scan", org_id, payload)
        existing = _find_existing_job_id(org_id, idempotency_key)
        if existing:
            return existing
        _guard_inflight("medium")
        task_id, created = _create_job(
            "scan",
            org_id=org_id,
            queue="medium",
            idempotency_key=idempotency_key,
        )
        if created:
            from ..celery_tasks import scan_task

            scan_task.apply_async(args=[task_id, project_id, org_id], queue="medium")
        return task_id

    def submit_docs(self, project_id: int, org_id: int) -> str:
        payload = {"project_id": project_id}
        idempotency_key = _idempotency_key("docs", org_id, payload)
        existing = _find_existing_job_id(org_id, idempotency_key)
        if existing:
            return existing
        _guard_inflight("light")
        task_id, created = _create_job(
            "docs",
            org_id=org_id,
            queue="light",
            idempotency_key=idempotency_key,
        )
        if created:
            from ..celery_tasks import docs_task

            docs_task.apply_async(args=[task_id, project_id, org_id], queue="light")
        return task_id

    def submit_run(self, project_id: int, org_id: int, payload: dict) -> str:
        normalized_payload = _normalize_payload(payload)
        idempotency_key = _idempotency_key(
            "run_task",
            org_id,
            {"project_id": project_id, "payload": normalized_payload},
        )
        existing = _find_existing_job_id(org_id, idempotency_key)
        if existing:
            return existing
        _guard_inflight("heavy")
        task_id, created = _create_job(
            "run_task",
            org_id=org_id,
            queue="heavy",
            idempotency_key=idempotency_key,
        )
        if created:
            from ..celery_tasks import run_task_job

            run_task_job.apply_async(
                args=[task_id, project_id, org_id, payload],
                queue="heavy",
            )
        return task_id

    def get(self, task_id: str) -> TaskState | None:
        with get_session() as session:
            job = session.get(TaskJob, task_id)
        if not job:
            return None
        result = None
        if isinstance(job.result_json, str) and job.result_json:
            try:
                result = json.loads(job.result_json)
            except Exception:
                result = None
        return TaskState(
            status=job.status,
            result=result,
            error=job.error,
            completed_at=job.completed_at,
        )


def _create_job(
    kind: str,
    *,
    org_id: int,
    queue: str,
    idempotency_key: str | None = None,
) -> tuple[str, bool]:
    task_id = uuid4().hex
    now = datetime.now(timezone.utc)
    with get_session() as session:
        job = TaskJob(
            id=task_id,
            org_id=org_id,
            status="pending",
            queue=queue,
            idempotency_key=idempotency_key,
            result_json=None,
            error=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        session.add(job)
        session.commit()
    return task_id, True


task_queue = TaskQueue()
logger = get_logger("stubgraph.task_queue")


def _guard_inflight(queue: str) -> None:
    if queue != "heavy":
        return
    limit = settings.task_queue_inflight_heavy_limit
    if limit is None:
        return
    try:
        client = get_redis_client()
        key = "stubgraph:queue:heavy:inflight"
        count = client.incr(key)
        if count == 1:
            client.expire(key, 60 * 10)
        if count > int(limit):
            client.decr(key)
            raise BadRequestError("Превышен лимит одновременных heavy задач")
    except RedisError as exc:
        logger.warning("In-flight queue check failed", extra={"reason": str(exc)})


def _find_existing_job_id(org_id: int, idempotency_key: str) -> str | None:
    with get_session() as session:
        existing = session.exec(
            select(TaskJob.id).where(
                TaskJob.org_id == org_id,
                TaskJob.idempotency_key == idempotency_key,
                TaskJob.status.in_(("pending", "running")),
            )
        ).first()
    if isinstance(existing, str) and existing:
        return existing
    if isinstance(existing, (tuple, list)) and existing and isinstance(existing[0], str):
        return existing[0]
    return None


def _normalize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalize_payload(value[k]) for k in sorted(value)}
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, (list, tuple)):
        return [_normalize_payload(v) for v in value]
    return value


def _idempotency_key(kind: str, org_id: int, payload: dict) -> str:
    raw = json.dumps(
        {
            "kind": kind,
            "org_id": org_id,
            "payload": _normalize_payload(payload),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(raw)
