# backend/app/services/task_queue.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from redis import RedisError
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select

from ..config import settings
from ..db import get_session
from ..errors import BadRequestError, ExternalServiceError
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
        idempotency_key = get_scan_idempotency_key(org_id, project_id)
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
        task_id = uuid4().hex
        _guard_inflight("heavy", task_id)
        try:
            task_id, created = _create_job(
                "run_task",
                org_id=org_id,
                queue="heavy",
                idempotency_key=idempotency_key,
                task_id=task_id,
            )
        except Exception:
            _release_inflight("heavy", task_id)
            raise
        if not created:
            _release_inflight("heavy", task_id)
        if created:
            from ..celery_tasks import run_task_job

            try:
                run_task_job.apply_async(
                    args=[task_id, project_id, org_id, payload],
                    queue="heavy",
                )
            except Exception as exc:
                _release_inflight("heavy", task_id)
                now = datetime.now(timezone.utc)
                try:
                    with get_session() as session:
                        job = session.get(TaskJob, task_id)
                        if job:
                            job.status = "failed"
                            job.error = str(exc)
                            job.completed_at = now
                            job.updated_at = now
                            session.add(job)
                            session.commit()
                except Exception as update_exc:
                    logger.warning(
                        "Failed to persist enqueue failure status",
                        extra={"task_id": task_id, "reason": str(update_exc)},
                    )
                raise ExternalServiceError(
                    "Не удалось отправить задачу в очередь",
                    context={"task_id": task_id, "queue": "heavy"},
                ) from exc
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
    task_id: str | None = None,
) -> tuple[str, bool]:
    task_id = task_id or uuid4().hex
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
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if idempotency_key:
                existing = session.exec(
                    select(TaskJob.id).where(
                        TaskJob.org_id == org_id,
                        TaskJob.idempotency_key == idempotency_key,
                        TaskJob.status.in_(("pending", "running")),
                    )
                ).first()
                if isinstance(existing, str) and existing:
                    return existing, False
                if (
                    isinstance(existing, (tuple, list))
                    and existing
                    and isinstance(existing[0], str)
                ):
                    return existing[0], False
            raise
    return task_id, True


task_queue = TaskQueue()
logger = get_logger("stubgraph.task_queue")


def _guard_inflight(queue: str, job_id: str | None = None) -> None:
    if queue != "heavy":
        return
    limit = settings.task_queue_inflight_heavy_limit
    if limit is None:
        return
    if not job_id:
        raise BadRequestError("Job id is required for inflight guard")
    try:
        client = get_redis_client()
        key = "stubgraph:queue:heavy:inflight"
        with get_session() as session:
            active_rows = session.exec(
                select(TaskJob.id).where(
                    TaskJob.queue == "heavy",
                    TaskJob.status.in_(("pending", "running")),
                )
            ).all()
        active_ids: set[str] = set()
        for row in active_rows:
            if isinstance(row, str):
                active_ids.add(row)
            elif isinstance(row, (tuple, list)) and row and isinstance(row[0], str):
                active_ids.add(row[0])
        existing_ids = client.smembers(key)
        zombies = set(existing_ids) - active_ids
        missing = active_ids - set(existing_ids)
        if zombies:
            client.srem(key, *zombies)
        if missing:
            client.sadd(key, *missing)
        lua = """
        local set_key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local job_id = ARGV[2]
        local count = redis.call("SCARD", set_key)
        if count >= limit then
            return {0, count}
        end
        redis.call("SADD", set_key, job_id)
        count = redis.call("SCARD", set_key)
        return {1, count}
        """
        added, _count = client.eval(lua, 1, key, int(limit), job_id)
        if int(added) != 1:
            raise BadRequestError("Превышен лимит одновременных heavy задач")
    except RedisError as exc:
        logger.warning("In-flight queue check failed", extra={"reason": str(exc)})
        raise ExternalServiceError(
            "Не удалось проверить лимит heavy-задач: Redis недоступен",
            context={"queue": "heavy", "limit": limit},
        ) from exc


def _release_inflight(queue: str, job_id: str) -> None:
    if queue != "heavy":
        return
    try:
        client = get_redis_client()
        key = "stubgraph:queue:heavy:inflight"
        client.srem(key, job_id)
    except RedisError as exc:
        logger.warning("Failed to release inflight job", extra={"reason": str(exc)})


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


def get_scan_idempotency_key(org_id: int, project_id: int) -> str:
    return _idempotency_key("scan", org_id, {"project_id": project_id})


def cleanup_completed_jobs() -> None:
    ttl_seconds = settings.task_queue_completed_ttl_seconds
    max_completed = settings.task_queue_max_completed
    if ttl_seconds is None and max_completed is None:
        return

    deleted_count = 0
    now = datetime.now(timezone.utc)
    with get_session() as session:
        if ttl_seconds is not None:
            cutoff = now - timedelta(seconds=ttl_seconds)
            result = session.exec(
                delete(TaskJob).where(
                    TaskJob.status.in_(("succeeded", "failed")),
                    TaskJob.completed_at < cutoff,
                )
            )
            if result.rowcount and result.rowcount > 0:
                deleted_count += result.rowcount
        if max_completed is not None:
            ids_to_delete = session.exec(
                select(TaskJob.id)
                .where(TaskJob.status.in_(("succeeded", "failed")))
                .order_by(TaskJob.completed_at.desc())
                .offset(max_completed)
            ).all()
            if ids_to_delete:
                result = session.exec(delete(TaskJob).where(TaskJob.id.in_(ids_to_delete)))
                if result.rowcount and result.rowcount > 0:
                    deleted_count += result.rowcount
        session.commit()

    logger.info("Completed task cleanup finished", extra={"deleted_count": deleted_count})
