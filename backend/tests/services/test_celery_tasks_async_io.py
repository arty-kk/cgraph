import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import celery_tasks


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_fs_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(celery_tasks, "run_fs_io_async", _fake_fs_runtime)

    result = await celery_tasks._normalize_project_root_async("/repo")

    assert result == Path("/repo")
    assert calls["func"] is celery_tasks.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {"operation": "celery.normalize_root"}


def test_worker_process_init_and_shutdown_use_async_resource_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _record(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", lambda: _record("init_redis"))
    monkeypatch.setattr(celery_tasks, "init_async_db", lambda: _record("init_db"))
    monkeypatch.setattr(celery_tasks, "init_fs_runtime", lambda: _record("init_fs"))
    monkeypatch.setattr(celery_tasks, "init_cpu_runtime", lambda: _record("init_cpu"))
    monkeypatch.setattr(
        celery_tasks,
        "init_celery_producer_runtime",
        lambda: _record("init_celery_producer"),
    )
    monkeypatch.setattr(
        celery_tasks,
        "init_external_io_runtime",
        lambda: _record("init_external_io"),
    )
    monkeypatch.setattr(celery_tasks, "init_s3_runtime", lambda: _record("init_s3"))
    monkeypatch.setattr(
        celery_tasks,
        "init_async_openai_client",
        lambda: _record("init_openai"),
    )

    monkeypatch.setattr(celery_tasks, "close_s3_runtime", lambda: _record("close_s3"))
    monkeypatch.setattr(celery_tasks, "close_redis_pool_async", lambda: _record("close_redis"))
    monkeypatch.setattr(celery_tasks, "close_async_openai_client", lambda: _record("close_openai"))
    monkeypatch.setattr(celery_tasks, "close_fs_runtime", lambda: _record("close_fs"))
    monkeypatch.setattr(celery_tasks, "close_cpu_runtime", lambda: _record("close_cpu"))
    monkeypatch.setattr(
        celery_tasks,
        "close_celery_producer_runtime",
        lambda: _record("close_celery_producer"),
    )
    monkeypatch.setattr(
        celery_tasks,
        "close_external_io_runtime",
        lambda: _record("close_external_io"),
    )
    monkeypatch.setattr(celery_tasks, "close_async_db", lambda: _record("close_db"))

    monkeypatch.setattr(celery_tasks.settings, "storage_backend", "s3")
    monkeypatch.setattr(celery_tasks.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", False)

    celery_tasks._on_worker_process_init()
    celery_tasks._on_worker_process_shutdown()

    assert calls == [
        "init_redis",
        "init_db",
        "init_fs",
        "init_cpu",
        "init_celery_producer",
        "init_external_io",
        "init_s3",
        "init_openai",
        "close_s3",
        "close_redis",
        "close_openai",
        "close_fs",
        "close_cpu",
        "close_celery_producer",
        "close_external_io",
        "close_db",
    ]


def test_worker_process_init_cleans_up_partial_startup_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _init_redis() -> None:
        calls.append("init_redis")

    async def _init_db() -> None:
        calls.append("init_db")
        raise RuntimeError("db boom")

    async def _record(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", _init_redis)
    monkeypatch.setattr(celery_tasks, "init_async_db", _init_db)
    monkeypatch.setattr(celery_tasks, "init_fs_runtime", lambda: _record("init_fs"))
    monkeypatch.setattr(celery_tasks, "init_cpu_runtime", lambda: _record("init_cpu"))
    monkeypatch.setattr(
        celery_tasks,
        "init_celery_producer_runtime",
        lambda: _record("init_celery_producer"),
    )
    monkeypatch.setattr(
        celery_tasks,
        "init_external_io_runtime",
        lambda: _record("init_external_io"),
    )
    monkeypatch.setattr(celery_tasks.settings, "storage_backend", "local")
    monkeypatch.setattr(celery_tasks.settings, "openai_api_key", "")

    monkeypatch.setattr(celery_tasks, "close_s3_runtime", lambda: _record("close_s3"))
    monkeypatch.setattr(celery_tasks, "close_redis_pool_async", lambda: _record("close_redis"))
    monkeypatch.setattr(celery_tasks, "close_async_openai_client", lambda: _record("close_openai"))
    monkeypatch.setattr(celery_tasks, "close_fs_runtime", lambda: _record("close_fs"))
    monkeypatch.setattr(celery_tasks, "close_cpu_runtime", lambda: _record("close_cpu"))
    monkeypatch.setattr(
        celery_tasks,
        "close_celery_producer_runtime",
        lambda: _record("close_celery_producer"),
    )
    monkeypatch.setattr(
        celery_tasks,
        "close_external_io_runtime",
        lambda: _record("close_external_io"),
    )
    monkeypatch.setattr(celery_tasks, "close_async_db", lambda: _record("close_db"))
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", False)

    with pytest.raises(RuntimeError, match="db boom"):
        celery_tasks._on_worker_process_init()

    assert calls == [
        "init_redis",
        "init_db",
        "close_s3",
        "close_redis",
        "close_openai",
        "close_fs",
        "close_cpu",
        "close_celery_producer",
        "close_external_io",
        "close_db",
    ]


def test_task_entrypoints_use_single_persistent_loop_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_loops: list[int] = []

    async def _scan(*_args, **_kwargs) -> None:
        seen_loops.append(id(asyncio.get_running_loop()))

    async def _docs(*_args, **_kwargs) -> None:
        seen_loops.append(id(asyncio.get_running_loop()))

    async def _run_task(*_args, **_kwargs) -> None:
        seen_loops.append(id(asyncio.get_running_loop()))

    async def _mutation(*_args, **_kwargs) -> None:
        seen_loops.append(id(asyncio.get_running_loop()))

    async def _calibration() -> dict:
        seen_loops.append(id(asyncio.get_running_loop()))
        return {"updated": True}

    async def _noop() -> None:
        return None

    monkeypatch.setattr(celery_tasks, "_scan_task_async", _scan)
    monkeypatch.setattr(celery_tasks, "_docs_task_async", _docs)
    monkeypatch.setattr(celery_tasks, "_run_task_job_async", _run_task)
    monkeypatch.setattr(celery_tasks, "_mutation_indexing_task_async", _mutation)
    monkeypatch.setattr(celery_tasks, "calibrate_routing_policy_thresholds_async", _calibration)
    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", _noop)
    monkeypatch.setattr(celery_tasks, "init_async_db", _noop)
    monkeypatch.setattr(celery_tasks, "init_fs_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "init_cpu_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "init_celery_producer_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "init_external_io_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_s3_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_redis_pool_async", _noop)
    monkeypatch.setattr(celery_tasks, "close_async_openai_client", _noop)
    monkeypatch.setattr(celery_tasks, "close_fs_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_cpu_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_celery_producer_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_external_io_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_async_db", _noop)
    monkeypatch.setattr(celery_tasks.settings, "storage_backend", "local")
    monkeypatch.setattr(celery_tasks.settings, "openai_api_key", "")
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", False)

    celery_tasks._on_worker_process_init()
    celery_tasks.scan_task("j", 1, 1)
    celery_tasks.docs_task("j", 1, 1)
    celery_tasks.run_task_job("j", 1, 1, {})
    celery_tasks.mutation_indexing_task("j", 1, 1, [], "op")
    result = celery_tasks.routing_calibration_task()
    celery_tasks._on_worker_process_shutdown()

    assert result == {"updated": True}
    assert len(seen_loops) == 5
    assert len(set(seen_loops)) == 1


def test_runtime_not_reinitialized_between_sequential_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _record(name: str) -> None:
        calls.append(name)

    async def _scan(*_args, **_kwargs) -> None:
        calls.append("scan")

    async def _docs(*_args, **_kwargs) -> None:
        calls.append("docs")

    async def _noop() -> None:
        return None

    monkeypatch.setattr(celery_tasks, "_scan_task_async", _scan)
    monkeypatch.setattr(celery_tasks, "_docs_task_async", _docs)
    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", _noop)
    monkeypatch.setattr(celery_tasks, "init_async_db", _noop)
    monkeypatch.setattr(celery_tasks, "init_fs_runtime", lambda: _record("init_fs"))
    monkeypatch.setattr(celery_tasks, "init_cpu_runtime", lambda: _record("init_cpu"))
    monkeypatch.setattr(celery_tasks, "init_celery_producer_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "init_external_io_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_s3_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_redis_pool_async", _noop)
    monkeypatch.setattr(celery_tasks, "close_async_openai_client", _noop)
    monkeypatch.setattr(celery_tasks, "close_fs_runtime", lambda: _record("close_fs"))
    monkeypatch.setattr(celery_tasks, "close_cpu_runtime", lambda: _record("close_cpu"))
    monkeypatch.setattr(celery_tasks, "close_celery_producer_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_external_io_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_async_db", _noop)
    monkeypatch.setattr(celery_tasks.settings, "storage_backend", "local")
    monkeypatch.setattr(celery_tasks.settings, "openai_api_key", "")
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", False)

    celery_tasks._on_worker_process_init()
    celery_tasks.scan_task("job-1", 1, 1)
    celery_tasks.docs_task("job-2", 1, 1)
    celery_tasks._on_worker_process_shutdown()

    assert calls.count("init_fs") == 1
    assert calls.count("init_cpu") == 1
    assert calls.count("close_fs") == 1
    assert calls.count("close_cpu") == 1
    assert calls.count("scan") == 1
    assert calls.count("docs") == 1


def test_concurrent_tasks_share_single_runtime_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    seen_loops: set[int] = set()

    async def _record(name: str) -> None:
        calls.append(name)

    async def _scan(*_args, **_kwargs) -> None:
        await asyncio.sleep(0)
        seen_loops.add(id(asyncio.get_running_loop()))

    async def _noop() -> None:
        return None

    monkeypatch.setattr(celery_tasks, "_scan_task_async", _scan)
    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", _noop)
    monkeypatch.setattr(celery_tasks, "init_async_db", _noop)
    monkeypatch.setattr(celery_tasks, "init_fs_runtime", lambda: _record("init_fs"))
    monkeypatch.setattr(celery_tasks, "init_cpu_runtime", lambda: _record("init_cpu"))
    monkeypatch.setattr(celery_tasks, "init_celery_producer_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "init_external_io_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_s3_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_redis_pool_async", _noop)
    monkeypatch.setattr(celery_tasks, "close_async_openai_client", _noop)
    monkeypatch.setattr(celery_tasks, "close_fs_runtime", lambda: _record("close_fs"))
    monkeypatch.setattr(celery_tasks, "close_cpu_runtime", lambda: _record("close_cpu"))
    monkeypatch.setattr(celery_tasks, "close_celery_producer_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_external_io_runtime", _noop)
    monkeypatch.setattr(celery_tasks, "close_async_db", _noop)
    monkeypatch.setattr(celery_tasks.settings, "storage_backend", "local")
    monkeypatch.setattr(celery_tasks.settings, "openai_api_key", "")
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", False)

    celery_tasks._on_worker_process_init()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(celery_tasks.scan_task, f"job-{idx}", 1, 1) for idx in range(40)]
        for future in futures:
            future.result()
    celery_tasks._on_worker_process_shutdown()

    assert calls.count("init_fs") == 1
    assert calls.count("init_cpu") == 1
    assert calls.count("close_fs") == 1
    assert calls.count("close_cpu") == 1
    assert len(seen_loops) == 1


def test_dispatch_task_uses_registered_celery_task(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Task:
        def apply_async(self, *, args, queue):
            captured["args"] = args
            captured["queue"] = queue

    monkeypatch.setitem(celery_tasks.celery_app.tasks, "stubgraph.scan", _Task())

    celery_tasks.dispatch_task(task_name="stubgraph.scan", args=["job-1", 1, 2], queue="medium")

    assert captured == {"args": ["job-1", 1, 2], "queue": "medium"}


@pytest.mark.anyio
async def test_scan_task_async_marks_failed_when_business_coroutine_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses: list[str] = []

    async def _fake_set_job_status_async(_job_id: str, status: str, **_kwargs) -> None:
        statuses.append(status)

    async def _boom(_project_id: int, _org_id: int) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(celery_tasks, "_set_job_status_async", _fake_set_job_status_async)
    monkeypatch.setattr(celery_tasks, "_scan_and_update_graph_async", _boom)

    await celery_tasks._scan_task_async("job", 1, 1)

    assert statuses == ["running", "failed"]
