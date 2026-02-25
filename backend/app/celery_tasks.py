# backend/app/celery_tasks.py
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, TypeVar

from celery.signals import worker_process_init, worker_process_shutdown

from .async_db import AsyncSessionLocal, close_async_db, init_async_db
from .celery_app import celery_app
from .config import settings
from .infra.cpu_runtime import close_cpu_runtime, init_cpu_runtime
from .infra.external_io_runtime import close_external_io_runtime, init_external_io_runtime
from .infra.fs_runtime import close_fs_runtime, init_fs_runtime, run_fs_io_async
from .infra.redis_client import (
    close_redis_pool_async,
    get_async_redis_client,
    init_redis_pool_async,
)
from .llm.client import close_async_openai_client, init_async_openai_client
from .logging import get_logger
from .models import Project, TaskJob
from .s3_runtime import close_s3_runtime, init_s3_runtime
from .services.docs_service import build_project_docs_async
from .services.file_mutation_service import run_mutation_indexing_async
from .services.project_service import _scan_and_update_graph_async
from .services.routing_calibration_service import calibrate_routing_policy_thresholds_async
from .services.task_queue import cleanup_completed_jobs_async
from .services.task_service import TaskRequest, run_task_async
from .utils import normalize_project_root

logger = get_logger("stubgraph.celery")

_worker_runtime_started = False
T = TypeVar("T")


def _run_async_entrypoint(
    coro: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    log_context: str,
) -> T:
    try:
        return asyncio.run(coro(*args))
    except Exception:  # noqa: BLE001
        logger.exception("Celery async entrypoint failed", extra={"entrypoint": log_context})
        raise


async def _startup_worker_resources_async() -> None:
    startup_steps: list[tuple[str, Any]] = [
        ("init_redis_pool_async", init_redis_pool_async),
        ("init_async_db", init_async_db),
        ("init_fs_runtime", init_fs_runtime),
        ("init_cpu_runtime", init_cpu_runtime),
        ("init_external_io_runtime", init_external_io_runtime),
    ]
    if (settings.storage_backend or "local").strip().lower() == "s3":
        startup_steps.append(("init_s3_runtime", init_s3_runtime))

    for name, startup in startup_steps:
        await startup()
        logger.info("Celery worker startup step completed", extra={"step": name})

    if settings.openai_api_key:
        await init_async_openai_client()
        logger.info(
            "Celery worker startup step completed",
            extra={"step": "init_async_openai_client"},
        )


async def _cleanup_worker_resources_async() -> None:
    cleanup_steps: list[tuple[str, Any]] = [
        ("close_s3_runtime", close_s3_runtime),
        ("close_redis_pool_async", close_redis_pool_async),
        ("close_async_openai_client", close_async_openai_client),
        ("close_fs_runtime", close_fs_runtime),
        ("close_cpu_runtime", close_cpu_runtime),
        ("close_external_io_runtime", close_external_io_runtime),
        ("close_async_db", close_async_db),
    ]
    for name, cleanup in cleanup_steps:
        try:
            await cleanup()
        except Exception:  # noqa: BLE001
            logger.exception("Celery cleanup failed", extra={"step": name})


@worker_process_init.connect
def _on_worker_process_init(**_kwargs: Any) -> None:
    global _worker_runtime_started
    if _worker_runtime_started:
        return
    try:
        _run_async_entrypoint(
            _startup_worker_resources_async,
            log_context="worker_process_init.startup",
        )
        _worker_runtime_started = True
    except Exception:  # noqa: BLE001
        logger.exception("Celery worker startup failed")
        try:
            _run_async_entrypoint(
                _cleanup_worker_resources_async,
                log_context="worker_process_init.cleanup_after_failure",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Celery worker cleanup after startup failure failed")
        finally:
            _worker_runtime_started = False
        raise


@worker_process_shutdown.connect
def _on_worker_process_shutdown(**_kwargs: Any) -> None:
    global _worker_runtime_started
    if not _worker_runtime_started:
        return
    try:
        _run_async_entrypoint(
            _cleanup_worker_resources_async,
            log_context="worker_process_shutdown.cleanup",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Celery worker cleanup failed")
    finally:
        _worker_runtime_started = False


async def _set_job_status_async(
    job_id: str,
    status: str,
    *,
    org_id: int | None = None,
    result: Any | None = None,
    error: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        job = await session.get(TaskJob, job_id)
        if not job:
            if org_id is None:
                raise RuntimeError("org_id обязателен для создания задачи")
            job = TaskJob(id=job_id, org_id=org_id, status=status)
            session.add(job)
        job.status = status
        job.updated_at = now
        if status == "running" and job.queue == "heavy":
            await _touch_inflight_async(job.id)
        if status in {"succeeded", "failed"}:
            job.completed_at = now
            if job.queue == "heavy":
                await _decrement_inflight_async(job.id)
        if error is not None:
            job.error = error
        if result is not None:
            job.result_json = json.dumps(result, ensure_ascii=False)
        session.add(job)
        await session.commit()
        if status in {"succeeded", "failed"}:
            await cleanup_completed_jobs_async(session)


async def _scan_task_async(job_id: str, project_id: int, org_id: int) -> None:
    await _set_job_status_async(job_id, "running", org_id=org_id)
    try:
        result = await _scan_and_update_graph_async(project_id, org_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scan task failed", extra={"job_id": job_id})
        await _set_job_status_async(job_id, "failed", org_id=org_id, error=str(exc))
        return
    await _set_job_status_async(job_id, "succeeded", org_id=org_id, result=result)


@celery_app.task(name="stubgraph.scan")
def scan_task(job_id: str, project_id: int, org_id: int) -> None:
    _run_async_entrypoint(_scan_task_async, job_id, project_id, org_id, log_context="scan_task")


async def _docs_task_async(job_id: str, project_id: int, org_id: int) -> None:
    await _set_job_status_async(job_id, "running", org_id=org_id)
    try:
        result = await build_project_docs_async(project_id, org_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Docs task failed", extra={"job_id": job_id})
        await _set_job_status_async(job_id, "failed", org_id=org_id, error=str(exc))
        return
    await _set_job_status_async(job_id, "succeeded", org_id=org_id, result=result)


@celery_app.task(name="stubgraph.docs")
def docs_task(job_id: str, project_id: int, org_id: int) -> None:
    _run_async_entrypoint(_docs_task_async, job_id, project_id, org_id, log_context="docs_task")


async def _run_task_job_async(job_id: str, project_id: int, org_id: int, payload: dict) -> None:
    await _set_job_status_async(job_id, "running", org_id=org_id)
    try:
        provided = payload.get("provided_fields")
        if isinstance(provided, list):
            payload["provided_fields"] = set(provided)
        request = TaskRequest(**payload)
        result = await run_task_async(project_id, org_id, request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Run task failed", extra={"job_id": job_id})
        await _set_job_status_async(job_id, "failed", org_id=org_id, error=str(exc))
        return
    await _set_job_status_async(job_id, "succeeded", org_id=org_id, result=result)


@celery_app.task(name="stubgraph.run_task")
def run_task_job(job_id: str, project_id: int, org_id: int, payload: dict) -> None:
    _run_async_entrypoint(
        _run_task_job_async,
        job_id,
        project_id,
        org_id,
        payload,
        log_context="run_task_job",
    )


async def _mutation_indexing_task_async(
    job_id: str,
    project_id: int,
    org_id: int,
    rel_paths: list[str],
    operation: str,
) -> None:
    await _set_job_status_async(job_id, "running", org_id=org_id)
    root = await _resolve_project_root_async(project_id, org_id)
    try:
        str_paths = [str(path) for path in rel_paths]
        async with AsyncSessionLocal() as session:
            result = await run_mutation_indexing_async(
                session,
                project_id=project_id,
                org_id=org_id,
                root=root,
                rel_paths=str_paths,
            )
        result["operation"] = str(operation)
        result["rel_paths"] = str_paths
        if result.get("aborted"):
            await _set_job_status_async(
                job_id,
                "failed",
                org_id=org_id,
                error="Mutation indexing aborted",
                result=result,
            )
            return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Mutation indexing task failed", extra={"job_id": job_id})
        await _set_job_status_async(job_id, "failed", org_id=org_id, error=str(exc))
        return
    await _set_job_status_async(job_id, "succeeded", org_id=org_id, result=result)


@celery_app.task(name="stubgraph.mutation_indexing")
def mutation_indexing_task(
    job_id: str,
    project_id: int,
    org_id: int,
    rel_paths: list[str],
    operation: str,
) -> None:
    _run_async_entrypoint(
        _mutation_indexing_task_async,
        job_id,
        project_id,
        org_id,
        rel_paths,
        operation,
        log_context="mutation_indexing_task",
    )


@celery_app.task(name="stubgraph.routing_calibration")
def routing_calibration_task() -> dict:
    try:
        return _run_async_entrypoint(
            calibrate_routing_policy_thresholds_async,
            log_context="routing_calibration_task",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Routing calibration task failed")
        return {"updated": False, "reason": "error", "error": str(exc)}


async def _resolve_project_root_async(project_id: int, org_id: int) -> Path:
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if not project or project.org_id != org_id:
            raise RuntimeError("Проект не найден")
        return await _normalize_project_root_async(project.root_path)


async def _normalize_project_root_async(root_path: str) -> Path:
    return await run_fs_io_async(
        normalize_project_root,
        root_path,
        operation="celery.normalize_root",
    )


async def _touch_inflight_async(job_id: str) -> None:
    key = "stubgraph:queue:heavy:inflight"
    await init_redis_pool_async()
    client = get_async_redis_client()
    await client.sadd(key, job_id)


async def _decrement_inflight_async(job_id: str) -> None:
    key = "stubgraph:queue:heavy:inflight"
    await init_redis_pool_async()
    client = get_async_redis_client()
    await client.srem(key, job_id)
