from __future__ import annotations

import base64
import binascii
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .async_db import AsyncSessionLocal
from .config import settings
from .infra.cpu_runtime import run_cpu_io_async
from .infra.fs_runtime import run_fs_io_async
from .infra.redis_client import get_async_redis_client, init_redis_pool_async
from .logging import get_logger
from .models import Project, TaskJob
from .services.docs_service import build_project_docs_async
from .services.project_service import create_project_from_snapshot_async
from .services.file_mutation_service import run_mutation_indexing_async
from .services.project_service import _scan_and_update_graph_async
from .services.routing_calibration_service import calibrate_routing_policy_thresholds_async
from .services.task_queue import cleanup_completed_jobs_async
from .services.task_service import TaskRequest, run_task_async
from .snapshots import (
    delete_snapshot_async,
    delete_staged_snapshot_upload_async,
    store_snapshot_upload_from_path_async,
)
from .utils import normalize_project_root

logger = get_logger("stubgraph.task_handlers")

_TASK_PAYLOAD_RAW_MAX_BYTES = 1_000_000
_TASK_PAYLOAD_BODY_MAX_BYTES = 5_000_000


def _task_payload_raw_max_bytes() -> int:
    return max(1, int(settings.task_payload_raw_max_bytes or _TASK_PAYLOAD_RAW_MAX_BYTES))


def _task_payload_body_max_bytes() -> int:
    return max(1, int(settings.task_payload_body_max_bytes or _TASK_PAYLOAD_BODY_MAX_BYTES))


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


async def _snapshot_import_task_async(
    job_id: str,
    name: str,
    archive_name: str,
    staged_path: str,
    org_id: int,
) -> None:
    await _set_job_status_async(job_id, "running", org_id=org_id)
    meta = None
    project = None

    async def _cleanup_snapshot_on_failure_async() -> None:
        if meta is None:
            return
        try:
            await delete_snapshot_async(meta)
        except Exception as cleanup_exc:  # noqa: BLE001
            logger.warning(
                "Snapshot cleanup failed after import error",
                extra={"job_id": job_id, "reason": str(cleanup_exc)},
            )

    try:
        meta = await store_snapshot_upload_from_path_async(staged_path, archive_name)
        async with AsyncSessionLocal() as session:
            project = await create_project_from_snapshot_async(session, name, meta, org_id)
    except asyncio.CancelledError as exc:
        logger.warning("Snapshot import task cancelled", extra={"job_id": job_id})
        await _cleanup_snapshot_on_failure_async()
        await _set_job_status_async(job_id, "failed", org_id=org_id, error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Snapshot import task failed", extra={"job_id": job_id})
        await _cleanup_snapshot_on_failure_async()
        await _set_job_status_async(job_id, "failed", org_id=org_id, error=str(exc))
        return
    finally:
        try:
            await delete_staged_snapshot_upload_async(staged_path)
        except Exception as cleanup_exc:  # noqa: BLE001
            logger.warning(
                "Staged snapshot cleanup failed",
                extra={"job_id": job_id, "reason": str(cleanup_exc)},
            )

    if meta is None or project is None:
        await _set_job_status_async(
            job_id,
            "failed",
            org_id=org_id,
            error="Snapshot import failed",
        )
        return

    await _set_job_status_async(
        job_id,
        "succeeded",
        org_id=org_id,
        result={
            "project_id": project.id,
            "name": project.name,
            "snapshot_label": meta.archive_name,
        },
    )


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
    "stubgraph.snapshot_import": _snapshot_import_task_async,
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


def _decode_task_payload(payload_raw: str | bytes) -> tuple[str, list[Any]]:
    max_raw_size = _task_payload_raw_max_bytes()
    if isinstance(payload_raw, bytes):
        if len(payload_raw) > max_raw_size:
            raise RuntimeError("Task payload exceeds raw size limit")
        try:
            payload_raw = payload_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("Task payload bytes must be valid UTF-8") from exc
    elif isinstance(payload_raw, str):
        if len(payload_raw.encode("utf-8")) > max_raw_size:
            raise RuntimeError("Task payload exceeds raw size limit")
    else:
        raise RuntimeError("Task payload must be str")

    payload = json.loads(payload_raw)
    if not isinstance(payload, dict):
        raise RuntimeError("Task payload root must be object")
    headers = payload.get("headers")
    properties = payload.get("properties")
    if headers is None:
        headers = {}
    if properties is None:
        properties = {}
    if not isinstance(headers, dict):
        raise RuntimeError("Task payload headers must be object")
    if not isinstance(properties, dict):
        raise RuntimeError("Task payload properties must be object")

    task_name = str(headers.get("task") or "")
    body = payload.get("body")
    body_encoding = properties.get("body_encoding")
    if not task_name:
        raise RuntimeError("Task payload missing task header")
    if not isinstance(body, str):
        raise RuntimeError("Task payload body must be str")
    if body_encoding == "base64":
        try:
            body_bytes = base64.b64decode(body.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise RuntimeError("Task payload body base64 is invalid") from exc
        if len(body_bytes) > _task_payload_body_max_bytes():
            raise RuntimeError("Task payload body exceeds decoded size limit")
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


async def _decode_task_payload_async(payload_raw: str | bytes) -> tuple[str, list[Any]]:
    return await run_cpu_io_async(
        _decode_task_payload,
        payload_raw,
        operation="task_handlers.decode_task_payload",
    )


async def consume_queued_task_payload_async(payload_raw: str | bytes) -> Any:
    task_name, args = await _decode_task_payload_async(payload_raw)
    return await execute_task_by_name_async(task_name, args)


async def consume_worker_queue_once_async(*, queue: str, timeout_seconds: int = 1) -> bool:
    await init_redis_pool_async()
    client = get_async_redis_client()
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
        operation="task_handlers.normalize_root",
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
