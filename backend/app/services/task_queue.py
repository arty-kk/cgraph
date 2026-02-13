# backend/app/services/task_queue.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from redis import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from ..async_db import AsyncSessionLocal
from ..config import settings
from ..errors import BadRequestError, ExternalServiceError
from ..infra.redis_client import async_redis_client
from ..logging import get_logger
from ..models import TaskJob
from ..utils import sha256_text


@dataclass
class TaskState:
    status: str
    result: Any | None = None
    error: str | None = None
    completed_at: datetime | None = None


logger = get_logger("stubgraph.task_queue")


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


async def _idempotency_key_async(kind: str, org_id: int, payload: dict) -> str:
    return await asyncio.to_thread(_idempotency_key, kind, org_id, payload)


async def get_scan_idempotency_key_async(org_id: int, project_id: int) -> str:
    return await _idempotency_key_async("scan", org_id, {"project_id": project_id})


async def _find_existing_job_id_async(
    session: AsyncSession, org_id: int, idempotency_key: str
) -> str | None:
    existing = (
        (
            await session.execute(
                select(TaskJob.id).where(
                    TaskJob.org_id == org_id,
                    TaskJob.idempotency_key == idempotency_key,
                    TaskJob.status.in_(("pending", "running")),
                )
            )
        )
        .scalars()
        .first()
    )
    if isinstance(existing, str) and existing:
        return existing
    return None


async def _find_existing_job_async(
    session: AsyncSession, org_id: int, idempotency_key: str
) -> tuple[str, str] | None:
    row = (
        await session.execute(
            select(TaskJob.id, TaskJob.status).where(
                TaskJob.org_id == org_id,
                TaskJob.idempotency_key == idempotency_key,
                TaskJob.status.in_(("pending", "running")),
            )
        )
    ).first()
    if isinstance(row, (tuple, list)) and len(row) >= 2:
        task_id, status = row[0], row[1]
        if isinstance(task_id, str) and task_id and status in {"pending", "running"}:
            return task_id, status
    return None


async def _create_job_async(
    session: AsyncSession,
    kind: str,
    *,
    org_id: int,
    queue: str,
    idempotency_key: str | None = None,
    task_id: str | None = None,
) -> tuple[str, bool]:
    _ = kind
    task_id = task_id or uuid4().hex
    now = datetime.now(timezone.utc)
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
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if idempotency_key:
            existing = await _find_existing_job_id_async(session, org_id, idempotency_key)
            if existing:
                return existing, False
        raise
    return task_id, True


async def _guard_inflight_async(
    session: AsyncSession,
    queue: str,
    job_id: str | None = None,
) -> None:
    if queue != "heavy":
        return
    limit = settings.task_queue_inflight_heavy_limit
    if limit is None:
        return
    if not job_id:
        raise BadRequestError("Job id is required for inflight guard")

    try:
        async with async_redis_client() as client:
            key = "stubgraph:queue:heavy:inflight"
            active_rows = list(
                (
                    await session.execute(
                        select(TaskJob.id).where(
                            TaskJob.queue == "heavy",
                            TaskJob.status.in_(("pending", "running")),
                        )
                    )
                )
                .scalars()
                .all()
            )
            active_ids = {row for row in active_rows if isinstance(row, str) and row}

            existing_ids = await client.smembers(key)
            zombies = set(existing_ids) - active_ids
            missing = active_ids - set(existing_ids)
            if zombies:
                await client.srem(key, *zombies)
            if missing:
                await client.sadd(key, *missing)
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
            added, _count = await client.eval(lua, 1, key, int(limit), job_id)
            if int(added) != 1:
                raise BadRequestError("Превышен лимит одновременных heavy задач")
    except RedisError as exc:
        logger.warning(
            "In-flight queue check failed",
            extra={
                "queue": queue,
                "limit": limit,
                "reason": str(exc),
            },
        )
        raise ExternalServiceError(
            "Не удалось проверить лимит очереди",
            context={"queue": queue},
        ) from exc


async def _release_inflight_async(queue: str, job_id: str) -> None:
    if queue != "heavy":
        return
    try:
        async with async_redis_client() as client:
            key = "stubgraph:queue:heavy:inflight"
            await client.srem(key, job_id)
    except RedisError as exc:
        logger.warning("Failed to release inflight job", extra={"reason": str(exc)})


async def submit_run_async(project_id: int, org_id: int, payload: dict) -> str:
    idempotency_key = await _idempotency_key_async(
        "run_task",
        org_id,
        {"project_id": project_id, "payload": payload},
    )

    task_id = uuid4().hex
    async with AsyncSessionLocal() as session:
        existing = await _find_existing_job_id_async(session, org_id, idempotency_key)
        if existing:
            return existing

        await _guard_inflight_async(session, "heavy", task_id)
        try:
            task_id, created = await _create_job_async(
                session,
                "run_task",
                org_id=org_id,
                queue="heavy",
                idempotency_key=idempotency_key,
                task_id=task_id,
            )
        except Exception:
            await _release_inflight_async("heavy", task_id)
            raise

        if not created:
            await _release_inflight_async("heavy", task_id)
            return task_id

        from ..celery_tasks import run_task_job

        try:
            run_task_job.apply_async(
                args=[task_id, project_id, org_id, payload],
                queue="heavy",
            )
        except Exception as exc:
            await _release_inflight_async("heavy", task_id)
            now = datetime.now(timezone.utc)
            try:
                job = await session.get(TaskJob, task_id)
                if job:
                    job.status = "failed"
                    job.error = str(exc)
                    job.completed_at = now
                    job.updated_at = now
                    session.add(job)
                    await session.commit()
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


async def submit_scan_async(project_id: int, org_id: int) -> str:
    idempotency_key = await get_scan_idempotency_key_async(org_id, project_id)
    async with AsyncSessionLocal() as session:
        existing = await _find_existing_job_id_async(session, org_id, idempotency_key)
        if existing:
            return existing

        task_id, created = await _create_job_async(
            session,
            "scan",
            org_id=org_id,
            queue="medium",
            idempotency_key=idempotency_key,
        )
        if created:
            from ..celery_tasks import scan_task

            try:
                scan_task.apply_async(args=[task_id, project_id, org_id], queue="medium")
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue task",
                    extra={
                        "task_id": task_id,
                        "queue": "medium",
                        "project_id": project_id,
                        "org_id": org_id,
                        "reason": str(exc),
                    },
                )
                now = datetime.now(timezone.utc)
                try:
                    job = await session.get(TaskJob, task_id)
                    if job:
                        job.status = "failed"
                        job.error = str(exc)
                        job.completed_at = now
                        job.updated_at = now
                        session.add(job)
                        await session.commit()
                except Exception as update_exc:
                    logger.warning(
                        "Failed to persist enqueue failure status",
                        extra={"task_id": task_id, "reason": str(update_exc)},
                    )
                raise ExternalServiceError(
                    "Не удалось отправить задачу в очередь",
                    context={"task_id": task_id, "queue": "medium"},
                ) from exc
        return task_id


async def submit_docs_async(project_id: int, org_id: int) -> str:
    payload = {"project_id": project_id}
    idempotency_key = await _idempotency_key_async("docs", org_id, payload)
    async with AsyncSessionLocal() as session:
        existing = await _find_existing_job_id_async(session, org_id, idempotency_key)
        if existing:
            return existing

        task_id, created = await _create_job_async(
            session,
            "docs",
            org_id=org_id,
            queue="light",
            idempotency_key=idempotency_key,
        )
        if created:
            from ..celery_tasks import docs_task

            try:
                docs_task.apply_async(args=[task_id, project_id, org_id], queue="light")
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue task",
                    extra={
                        "task_id": task_id,
                        "queue": "light",
                        "project_id": project_id,
                        "org_id": org_id,
                        "reason": str(exc),
                    },
                )
                now = datetime.now(timezone.utc)
                try:
                    job = await session.get(TaskJob, task_id)
                    if job:
                        job.status = "failed"
                        job.error = str(exc)
                        job.completed_at = now
                        job.updated_at = now
                        session.add(job)
                        await session.commit()
                except Exception as update_exc:
                    logger.warning(
                        "Failed to persist enqueue failure status",
                        extra={"task_id": task_id, "reason": str(update_exc)},
                    )
                raise ExternalServiceError(
                    "Не удалось отправить задачу в очередь",
                    context={"task_id": task_id, "queue": "light"},
                ) from exc
        return task_id


async def submit_mutation_indexing_async(
    project_id: int,
    org_id: int,
    rel_paths: list[str],
    operation: str,
) -> tuple[str, str]:
    payload = {
        "project_id": project_id,
        "rel_paths": [str(path) for path in rel_paths],
        "operation": str(operation),
    }
    idempotency_key = await _idempotency_key_async("mutation_indexing", org_id, payload)

    async with AsyncSessionLocal() as session:
        existing = await _find_existing_job_async(session, org_id, idempotency_key)
        if existing:
            return existing

        task_id, created = await _create_job_async(
            session,
            "mutation_indexing",
            org_id=org_id,
            queue="medium",
            idempotency_key=idempotency_key,
        )
        if created:
            from ..celery_tasks import mutation_indexing_task

            try:
                mutation_indexing_task.apply_async(
                    args=[task_id, project_id, org_id, payload["rel_paths"], payload["operation"]],
                    queue="medium",
                )
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue task",
                    extra={
                        "task_id": task_id,
                        "queue": "medium",
                        "project_id": project_id,
                        "org_id": org_id,
                        "reason": str(exc),
                    },
                )
                now = datetime.now(timezone.utc)
                try:
                    job = await session.get(TaskJob, task_id)
                    if job:
                        job.status = "failed"
                        job.error = str(exc)
                        job.completed_at = now
                        job.updated_at = now
                        session.add(job)
                        await session.commit()
                except Exception as update_exc:
                    logger.warning(
                        "Failed to persist enqueue failure status",
                        extra={"task_id": task_id, "reason": str(update_exc)},
                    )
                raise ExternalServiceError(
                    "Не удалось отправить задачу в очередь",
                    context={"task_id": task_id, "queue": "medium"},
                ) from exc
    return task_id, "pending"


async def cleanup_completed_jobs_async(session: AsyncSession) -> None:
    ttl_seconds = settings.task_queue_completed_ttl_seconds
    max_completed = settings.task_queue_max_completed
    if ttl_seconds is None and max_completed is None:
        return

    deleted_count = 0
    now = datetime.now(timezone.utc)
    if ttl_seconds is not None:
        cutoff = now - timedelta(seconds=ttl_seconds)
        result = await session.execute(
            delete(TaskJob).where(
                TaskJob.status.in_(("succeeded", "failed")),
                TaskJob.completed_at < cutoff,
            )
        )
        if result.rowcount and result.rowcount > 0:
            deleted_count += result.rowcount
    if max_completed is not None:
        ids_to_delete = (
            await session.execute(
                select(TaskJob.id)
                .where(TaskJob.status.in_(("succeeded", "failed")))
                .order_by(TaskJob.completed_at.desc())
                .offset(max_completed)
            )
        ).scalars().all()
        if ids_to_delete:
            result = await session.execute(delete(TaskJob).where(TaskJob.id.in_(ids_to_delete)))
            if result.rowcount and result.rowcount > 0:
                deleted_count += result.rowcount
    await session.commit()

    logger.info("Completed task cleanup finished", extra={"deleted_count": deleted_count})
