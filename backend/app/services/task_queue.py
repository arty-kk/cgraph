# backend/app/services/task_queue.py
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import redis.asyncio as redis_async
from kombu.serialization import dumps
from redis import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func
from sqlmodel import delete, select

from ..async_db import AsyncSessionLocal
from ..config import settings
from ..errors import BadRequestError, ExternalServiceError
from ..infra.redis_client import get_async_redis_client
from ..logging import get_logger
from ..models import TaskJob
from ..utils import sha256_text


logger = get_logger("stubgraph.task_queue")

_HEAVY_INFLIGHT_KEY = "stubgraph:queue:heavy:inflight"
_ENQUEUE_TIMEOUT_SECONDS = 10.0
_ENQUEUE_REASON_KEY = "enqueue_reason"

_producer_redis_client: redis_async.Redis | None = None
_producer_runtime_guard: asyncio.Lock | None = None
_producer_runtime_guard_loop: asyncio.AbstractEventLoop | None = None


def _get_producer_runtime_guard() -> asyncio.Lock:
    global _producer_runtime_guard
    global _producer_runtime_guard_loop
    current_loop = asyncio.get_running_loop()
    if _producer_runtime_guard is None or _producer_runtime_guard_loop is not current_loop:
        _producer_runtime_guard = asyncio.Lock()
        _producer_runtime_guard_loop = current_loop
    return _producer_runtime_guard


def _validate_broker_url() -> str:
    broker_url = str(settings.celery_broker_url or "").strip()
    parsed_broker = urlparse(broker_url)
    scheme = parsed_broker.scheme.lower()
    if not scheme.startswith("redis"):
        raise RuntimeError(
            f"STUBGRAPH_CELERY_BROKER_URL must use redis:// scheme, got: {scheme or 'empty'}"
        )
    return broker_url


class _AsyncTaskProducerError(Exception):
    """Transport-level async producer enqueue failure."""


class _AsyncTaskTransportClient:
    async def publish_async(self, *, task_name: str, args: list[Any], queue: str) -> None:
        from ..celery_app import celery_app

        client = _producer_redis_client
        if client is None:
            await init_task_producer_runtime_async()
            client = _producer_redis_client
        if client is None:
            raise _AsyncTaskProducerError("task queue producer runtime is not initialized")

        message = celery_app.amqp.as_task_v2(
            task_id=str(args[0]) if args else uuid4().hex,
            name=task_name,
            args=args,
            kwargs={},
            root_id=str(args[0]) if args else None,
            ignore_result=True,
            argsrepr=repr(args),
            kwargsrepr="{}",
            origin="stubgraph.task_queue",
        )
        content_type, content_encoding, body = dumps(message.body, serializer="json")
        body_encoded = (
            base64.b64encode(body).decode("ascii") if isinstance(body, bytes) else str(body)
        )
        payload = {
            "body": body_encoded,
            "content-type": content_type,
            "content-encoding": content_encoding,
            "headers": message.headers,
            "properties": {
                **message.properties,
                "body_encoding": "base64" if isinstance(body, bytes) else "utf-8",
                "delivery_info": {"exchange": "", "routing_key": queue},
                "delivery_mode": 2,
                "priority": 0,
            },
        }
        await client.lpush(queue, json.dumps(payload, ensure_ascii=False))


class _AsyncTaskProducer:
    def __init__(self, client: _AsyncTaskTransportClient | None = None) -> None:
        self._client = client or _AsyncTaskTransportClient()

    async def enqueue_task_async(self, task_name: str, *, args: list[Any], queue: str) -> None:
        try:
            if not task_name:
                raise RuntimeError("Celery task name is required")
            await self._client.publish_async(task_name=task_name, args=args, queue=queue)
        except Exception as exc:  # noqa: BLE001
            raise _AsyncTaskProducerError(str(exc)) from exc




async def init_task_producer_runtime_async() -> None:
    global _producer_redis_client
    if _producer_redis_client is not None:
        return

    broker_url = _validate_broker_url()
    guard = _get_producer_runtime_guard()
    async with guard:
        if _producer_redis_client is not None:
            return
        _producer_redis_client = redis_async.Redis.from_url(broker_url, decode_responses=True)


async def close_task_producer_runtime_async() -> None:
    global _producer_redis_client
    guard = _get_producer_runtime_guard()
    async with guard:
        client = _producer_redis_client
        _producer_redis_client = None
    if client is not None:
        await client.aclose()


_async_task_producer = _AsyncTaskProducer()


def _classify_enqueue_failure(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, _AsyncTaskProducerError):
        return "broker_error"
    return "internal_enqueue_failure"


async def _mark_enqueue_failure_async(
    session: AsyncSession,
    task_id: str,
    exc: BaseException,
) -> None:
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
    except Exception as update_exc:  # noqa: BLE001
        logger.warning(
            "Failed to persist enqueue failure status",
            extra={"task_id": task_id, "reason": str(update_exc)},
        )


async def _enqueue_with_error_mapping_async(
    *,
    session: AsyncSession | None = None,
    task_name: str,
    args: list[Any],
    queue: str,
    task_id: str,
) -> None:
    try:
        await asyncio.wait_for(
            _async_task_producer.enqueue_task_async(task_name, args=args, queue=queue),
            timeout=_ENQUEUE_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError as exc:
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise
        reason = _classify_enqueue_failure(exc)
        if session is not None:
            await _mark_enqueue_failure_async(session, task_id, exc)
        else:
            logger.warning(
                "Failed to persist enqueue failure status: session is unavailable",
                extra={"task_id": task_id},
            )
        raise ExternalServiceError(
            "Не удалось отправить задачу в очередь",
            context={"task_id": task_id, "queue": queue, _ENQUEUE_REASON_KEY: reason},
        ) from exc
    except Exception as exc:
        reason = _classify_enqueue_failure(exc)
        if session is not None:
            await _mark_enqueue_failure_async(session, task_id, exc)
        else:
            logger.warning(
                "Failed to persist enqueue failure status: session is unavailable",
                extra={"task_id": task_id},
            )
        raise ExternalServiceError(
            "Не удалось отправить задачу в очередь",
            context={"task_id": task_id, "queue": queue, _ENQUEUE_REASON_KEY: reason},
        ) from exc


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
    return _idempotency_key(kind, org_id, payload)


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
    _ = session
    if queue != "heavy":
        return
    limit = settings.task_queue_inflight_heavy_limit
    if limit is None:
        return
    if not job_id:
        raise BadRequestError("Job id is required for inflight guard")

    try:
        client = get_async_redis_client()
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

        async def _try_add_inflight() -> tuple[int, int]:
            added_raw, count_raw = await client.eval(
                lua,
                1,
                _HEAVY_INFLIGHT_KEY,
                int(limit),
                job_id,
            )
            return int(added_raw), int(count_raw)

        added, _ = await _try_add_inflight()
        if added != 1:
            try:
                await _reconcile_heavy_inflight_async()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Heavy inflight reconciliation failed",
                    extra={"reason": str(exc)},
                )
            added, _ = await _try_add_inflight()

        if added != 1:
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
        client = get_async_redis_client()
        await client.srem(_HEAVY_INFLIGHT_KEY, job_id)
    except RedisError as exc:
        logger.warning("Failed to release inflight job", extra={"reason": str(exc)})


async def _reconcile_heavy_inflight_async() -> None:
    async with AsyncSessionLocal() as session:
        db_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TaskJob)
                    .where(
                        TaskJob.queue == "heavy",
                        TaskJob.status.in_(("pending", "running")),
                    )
                )
            ).scalar_one()
            or 0
        )
        client = get_async_redis_client()
        redis_count = int(await client.scard(_HEAVY_INFLIGHT_KEY))
        if redis_count == db_count:
            return

        active_ids = list(
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
        await client.delete(_HEAVY_INFLIGHT_KEY)
        if active_ids:
            await client.sadd(_HEAVY_INFLIGHT_KEY, *active_ids)


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
        try:
            await _enqueue_with_error_mapping_async(
                session=session,
                task_name="stubgraph.run_task",
                args=[task_id, project_id, org_id, payload],
                queue="heavy",
                task_id=task_id,
            )
        except ExternalServiceError:
            await _release_inflight_async("heavy", task_id)
            raise
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
        if not created:
            return task_id
        await _enqueue_with_error_mapping_async(
            session=session,
            task_name="stubgraph.scan",
            args=[task_id, project_id, org_id],
            queue="medium",
            task_id=task_id,
        )
    return task_id


async def submit_docs_async(project_id: int, org_id: int) -> tuple[str, str]:
    payload = {"project_id": project_id}
    idempotency_key = await _idempotency_key_async("docs", org_id, payload)
    async with AsyncSessionLocal() as session:
        existing = await _find_existing_job_async(session, org_id, idempotency_key)
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
            await _enqueue_with_error_mapping_async(
                session=session,
                task_name="stubgraph.docs",
                args=[task_id, project_id, org_id],
                queue="light",
                task_id=task_id,
            )
            return task_id, "pending"

    async with AsyncSessionLocal() as session:
        existing = await _find_existing_job_async(session, org_id, idempotency_key)
        if existing:
            return existing
    return task_id, "pending"


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
            await _enqueue_with_error_mapping_async(
                session=session,
                task_name="stubgraph.mutation_indexing",
                args=[task_id, project_id, org_id, payload["rel_paths"], payload["operation"]],
                queue="medium",
                task_id=task_id,
            )
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
