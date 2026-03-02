# backend/app/celery_tasks.py
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .async_db import AsyncSessionLocal
from .infra.fs_runtime import run_fs_io_async
from .infra.redis_client import get_async_redis_client, init_redis_pool_async
from .logging import get_logger
from .models import Project, TaskJob
from .services.docs_service import build_project_docs_async
from .services.file_mutation_service import run_mutation_indexing_async
from .services.project_service import _scan_and_update_graph_async
from .services.routing_calibration_service import calibrate_routing_policy_thresholds_async
from .services.task_queue import cleanup_completed_jobs_async, get_task_transport_redis_client_async
from .services.task_service import TaskRequest, run_task_async
from .utils import normalize_project_root

logger = get_logger("stubgraph.celery")


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


async def _docs_task_async(job_id: str, project_id: int, org_id: int) -> None:
    await _set_job_status_async(job_id, "running", org_id=org_id)
    try:
        result = await build_project_docs_async(project_id, org_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Docs task failed", extra={"job_id": job_id})
        await _set_job_status_async(job_id, "failed", org_id=org_id, error=str(exc))
        return
    await _set_job_status_async(job_id, "succeeded", org_id=org_id, result=result)


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


async def _routing_calibration_task_async() -> dict:
    try:
        return await calibrate_routing_policy_thresholds_async()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Routing calibration task failed")
        return {"updated": False, "reason": "error", "error": str(exc)}


_TASK_DISPATCH: dict[str, Any] = {
    "stubgraph.scan": _scan_task_async,
    "stubgraph.docs": _docs_task_async,
    "stubgraph.run_task": _run_task_job_async,
    "stubgraph.mutation_indexing": _mutation_indexing_task_async,
}


async def execute_task_by_name_async(task_name: str, args: list[Any]) -> Any:
    if task_name == "stubgraph.routing_calibration":
        return await _routing_calibration_task_async()
    handler = _TASK_DISPATCH.get(task_name)
    if handler is None:
        raise RuntimeError(f"Unsupported task: {task_name}")
    await handler(*args)
    return None


def _decode_task_payload(payload_raw: str) -> tuple[str, list[Any]]:
    payload = json.loads(payload_raw)
    task_name = str(payload.get("headers", {}).get("task") or "")
    body = payload.get("body")
    body_encoding = payload.get("properties", {}).get("body_encoding")
    if not task_name:
        raise RuntimeError("Task payload missing task header")
    if not isinstance(body, str):
        raise RuntimeError("Task payload body must be str")
    if body_encoding == "base64":
        body_bytes = base64.b64decode(body.encode("ascii"))
        body_data = json.loads(body_bytes.decode("utf-8"))
    else:
        body_data = json.loads(body)
    if isinstance(body_data, list) and len(body_data) == 3 and isinstance(body_data[1], dict):
        args = body_data[0]
    else:
        args = body_data
    if not isinstance(args, list):
        raise RuntimeError("Task payload args must be list")
    return task_name, args


async def consume_queued_task_payload_async(payload_raw: str) -> Any:
    task_name, args = _decode_task_payload(payload_raw)
    return await execute_task_by_name_async(task_name, args)


async def consume_worker_queue_once_async(*, queue: str, timeout_seconds: int = 1) -> bool:
    client = await get_task_transport_redis_client_async()
    item = await client.brpop(queue, timeout=timeout_seconds)
    if item is None:
        return False
    _, payload_raw = item
    await consume_queued_task_payload_async(payload_raw)
    return True


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
