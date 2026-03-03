"""ARQ worker settings and handlers for background task processing."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from arq.cron import cron
from arq.worker import Retry, func

from .task_handlers import execute_task_by_name_async
from .config import settings
from .infra.runtime_lifecycle import build_cleanup_steps, build_startup_steps
from .logging import get_logger
from .services.routing_calibration_service import calibrate_routing_policy_thresholds_async

logger = get_logger("stubgraph.arq_worker")


async def _run_task_async(task_name: str, args: list[object]) -> None:
    try:
        await execute_task_by_name_async(task_name, args)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ARQ task failed", extra={"task_name": task_name})
        raise Retry(defer=1) from exc


async def run_scan(ctx: dict, job_id: str, project_id: int, org_id: int) -> None:
    _ = ctx
    await _run_task_async("stubgraph.scan", [job_id, project_id, org_id])


async def run_docs(ctx: dict, job_id: str, project_id: int, org_id: int) -> None:
    _ = ctx
    await _run_task_async("stubgraph.docs", [job_id, project_id, org_id])


async def run_task_job(
    ctx: dict,
    job_id: str,
    project_id: int,
    org_id: int,
    payload: dict,
) -> None:
    _ = ctx
    await _run_task_async("stubgraph.run_task", [job_id, project_id, org_id, payload])


async def run_mutation_indexing(
    ctx: dict,
    job_id: str,
    project_id: int,
    org_id: int,
    rel_paths: list[str],
    operation: str,
) -> None:
    _ = ctx
    await _run_task_async(
        "stubgraph.mutation_indexing",
        [job_id, project_id, org_id, rel_paths, operation],
    )


async def run_routing_calibration(ctx: dict) -> dict[str, object]:
    _ = ctx
    return await calibrate_routing_policy_thresholds_async()


async def on_startup(ctx: dict) -> None:
    _ = ctx
    for _, startup in build_startup_steps(role="worker_core"):
        await startup()


async def on_shutdown(ctx: dict) -> None:
    _ = ctx
    for _, cleanup in build_cleanup_steps(role="worker_core"):
        await cleanup()


def _build_worker_functions() -> list:
    return [
        func(run_scan, name="stubgraph.scan", max_tries=settings.arq_max_tries),
        func(run_docs, name="stubgraph.docs", max_tries=settings.arq_max_tries),
        func(run_task_job, name="stubgraph.run_task", max_tries=settings.arq_max_tries),
        func(
            run_mutation_indexing,
            name="stubgraph.mutation_indexing",
            max_tries=settings.arq_max_tries,
        ),
    ]


def _build_cron_jobs() -> list[object]:
    cron_enabled = os.getenv("STUBGRAPH_ARQ_ENABLE_CRON", "false").strip().lower() == "true"
    if not bool(settings.llm_routing_calibration_enabled) or not cron_enabled:
        return []
    interval = max(1, int(settings.llm_routing_calibration_interval_minutes))
    return [cron(run_routing_calibration, minute={m % 60 for m in range(0, 60, interval)})]


class WorkerSettings:
    functions = _build_worker_functions()
    cron_jobs = _build_cron_jobs()
    on_startup = on_startup
    on_shutdown = on_shutdown
    queue_name = os.getenv("STUBGRAPH_ARQ_QUEUE", settings.task_queue_default)
    max_jobs = settings.worker_runtime_concurrency
    job_timeout = settings.arq_job_timeout_seconds
    keep_result = settings.arq_keep_result_seconds
    poll_delay = settings.arq_poll_delay_seconds
    max_tries = settings.arq_max_tries
    health_check_interval = 60
