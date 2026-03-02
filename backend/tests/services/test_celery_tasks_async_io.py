import asyncio
import sys
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

    monkeypatch.setattr(
        celery_tasks,
        "build_startup_steps",
        lambda *, role: [
            ("init_redis", lambda: _record("init_redis")),
            ("init_db", lambda: _record("init_db")),
            ("init_fs", lambda: _record("init_fs")),
            ("init_cpu", lambda: _record("init_cpu")),
            ("init_external_io", lambda: _record("init_external_io")),
            ("init_s3", lambda: _record("init_s3")),
            ("init_openai", lambda: _record("init_openai")),
        ],
    )
    monkeypatch.setattr(
        celery_tasks,
        "build_cleanup_steps",
        lambda *, role: [
            ("close_s3", lambda: _record("close_s3")),
            ("close_redis", lambda: _record("close_redis")),
            ("close_openai", lambda: _record("close_openai")),
            ("close_fs", lambda: _record("close_fs")),
            ("close_cpu", lambda: _record("close_cpu")),
            ("close_external_io", lambda: _record("close_external_io")),
            ("close_db", lambda: _record("close_db")),
        ],
    )
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", False)
    monkeypatch.setattr(celery_tasks, "_worker_runner", None)

    celery_tasks._on_worker_process_init()
    celery_tasks._on_worker_process_shutdown()

    assert calls == [
        "init_redis",
        "init_db",
        "init_fs",
        "init_cpu",
        "init_external_io",
        "init_s3",
        "init_openai",
        "close_s3",
        "close_redis",
        "close_openai",
        "close_fs",
        "close_cpu",
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

    monkeypatch.setattr(
        celery_tasks,
        "build_startup_steps",
        lambda *, role: [
            ("init_redis", _init_redis),
            ("init_db", _init_db),
            ("init_fs", lambda: _record("init_fs")),
        ],
    )
    monkeypatch.setattr(
        celery_tasks,
        "build_cleanup_steps",
        lambda *, role: [
            ("close_s3", lambda: _record("close_s3")),
            ("close_redis", lambda: _record("close_redis")),
            ("close_openai", lambda: _record("close_openai")),
            ("close_fs", lambda: _record("close_fs")),
            ("close_cpu", lambda: _record("close_cpu")),
            ("close_external_io", lambda: _record("close_external_io")),
            ("close_db", lambda: _record("close_db")),
        ],
    )
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", False)
    monkeypatch.setattr(celery_tasks, "_worker_runner", None)

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
        "close_external_io",
        "close_db",
    ]


def test_worker_startup_failure_resets_runtime_started_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> None:
        raise RuntimeError("boom")

    async def _noop() -> None:
        return None

    monkeypatch.setattr(celery_tasks, "build_startup_steps", lambda *, role: [("boom", _boom)])
    monkeypatch.setattr(celery_tasks, "build_cleanup_steps", lambda *, role: [("noop", _noop)])
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", False)
    monkeypatch.setattr(celery_tasks, "_worker_runner", None)

    with pytest.raises(RuntimeError, match="boom"):
        celery_tasks._on_worker_process_init()

    assert celery_tasks._worker_runtime_started is False
    assert celery_tasks._worker_runner is None


def test_worker_process_shutdown_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _record(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(
        celery_tasks,
        "build_cleanup_steps",
        lambda *, role: [
            ("close_redis", lambda: _record("close_redis")),
            ("close_db", lambda: _record("close_db")),
        ],
    )
    monkeypatch.setattr(celery_tasks, "_worker_runtime_started", True)
    celery_tasks._run_async_entrypoint(_record, "startup", log_context="seed")

    celery_tasks._on_worker_process_shutdown()
    celery_tasks._on_worker_process_shutdown()

    assert calls == ["startup", "close_redis", "close_db"]
    assert celery_tasks._worker_runner is None


def test_run_async_entrypoint_reuses_worker_runner_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(celery_tasks, "_worker_runner", None)

    async def _value(value: int) -> int:
        return value

    first = celery_tasks._run_async_entrypoint(_value, 1, log_context="first")
    first_runner = celery_tasks._worker_runner
    second = celery_tasks._run_async_entrypoint(_value, 2, log_context="second")
    second_runner = celery_tasks._worker_runner

    assert first == 1
    assert second == 2
    assert first_runner is not None
    assert second_runner is first_runner

    celery_tasks._close_worker_runner()


def test_run_async_entrypoint_executes_coroutine() -> None:
    async def _value() -> int:
        return 42

    assert celery_tasks._run_async_entrypoint(_value, log_context="test") == 42
    celery_tasks._close_worker_runner()


def test_run_async_entrypoint_handles_cancelled_error() -> None:
    async def _cancelled() -> None:
        raise asyncio.CancelledError("cancelled")

    with pytest.raises(asyncio.CancelledError, match="cancelled"):
        celery_tasks._run_async_entrypoint(_cancelled, log_context="cancelled")
    celery_tasks._close_worker_runner()


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
