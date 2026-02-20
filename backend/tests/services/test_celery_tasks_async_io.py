import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import celery_tasks


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.mark.anyio
async def test_resolve_project_root_async_uses_async_normalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return None

        async def get(self, model, project_id):
            _ = model, project_id
            return type("Project", (), {"org_id": 7, "root_path": "/repo"})()

    async def _fake_normalize_project_root_async(root_path: str):
        assert root_path == "/repo"
        return Path("/normalized")

    monkeypatch.setattr(celery_tasks, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(
        celery_tasks,
        "_normalize_project_root_async",
        _fake_normalize_project_root_async,
    )
    monkeypatch.setattr(
        celery_tasks,
        "normalize_project_root",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("sync normalize_project_root must not be used")
        ),
    )

    result = await celery_tasks._resolve_project_root_async(project_id=1, org_id=7)

    assert result == Path("/normalized")


@pytest.mark.anyio
async def test_mutation_indexing_task_async_uses_async_indexer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_set_job_status_async(*_args, **_kwargs):
        calls.append("status")

    async def _fake_resolve_project_root_async(*_args, **_kwargs):
        return Path("/repo")

    class _Session:
        async def __aenter__(self):
            return "session"

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return None

    async def _fake_run_mutation_indexing_async(session, **kwargs):
        assert session == "session"
        assert kwargs["project_id"] == 1
        assert kwargs["org_id"] == 7
        assert kwargs["root"] == Path("/repo")
        assert kwargs["rel_paths"] == ["a.py"]
        calls.append("index")
        return {"aborted": False}

    async def _fail_to_thread(*_args, **_kwargs):
        raise AssertionError("asyncio.to_thread must not be used for async mutation scan path")

    monkeypatch.setattr(celery_tasks, "_set_job_status_async", _fake_set_job_status_async)
    monkeypatch.setattr(
        celery_tasks,
        "_resolve_project_root_async",
        _fake_resolve_project_root_async,
    )
    monkeypatch.setattr(
        celery_tasks,
        "run_mutation_indexing_async",
        _fake_run_mutation_indexing_async,
    )
    monkeypatch.setattr(celery_tasks, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(celery_tasks.asyncio, "to_thread", _fail_to_thread)

    await celery_tasks._mutation_indexing_task_async("job-1", 1, 7, ["a.py"], "update")

    assert "index" in calls


@pytest.mark.anyio
async def test_touch_inflight_async_initializes_redis_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Client:
        async def sadd(self, key: str, value: str) -> None:
            calls.append(f"sadd:{key}:{value}")

    async def _fake_init() -> None:
        calls.append("init")

    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", _fake_init)
    monkeypatch.setattr(celery_tasks, "get_async_redis_client", lambda: _Client())

    await celery_tasks._touch_inflight_async("job-1")

    assert calls == ["init", "sadd:stubgraph:queue:heavy:inflight:job-1"]


@pytest.mark.anyio
async def test_decrement_inflight_async_initializes_redis_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Client:
        async def srem(self, key: str, value: str) -> None:
            calls.append(f"srem:{key}:{value}")

    async def _fake_init() -> None:
        calls.append("init")

    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", _fake_init)
    monkeypatch.setattr(celery_tasks, "get_async_redis_client", lambda: _Client())

    await celery_tasks._decrement_inflight_async("job-2")

    assert calls == ["init", "srem:stubgraph:queue:heavy:inflight:job-2"]


def test_worker_process_init_runs_startup_steps_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_init_redis() -> None:
        calls.append("init_redis")

    async def _fake_init_db() -> None:
        calls.append("init_db")

    async def _fake_init_s3() -> None:
        calls.append("init_s3")

    async def _fake_init_fs() -> None:
        calls.append("init_fs")

    def _fake_openai() -> object:
        calls.append("openai")
        return object()

    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(celery_tasks, "init_async_db", _fake_init_db)
    monkeypatch.setattr(celery_tasks, "init_s3_runtime", _fake_init_s3)
    monkeypatch.setattr(celery_tasks, "init_fs_runtime", _fake_init_fs)
    monkeypatch.setattr(celery_tasks, "get_async_openai_client", _fake_openai)
    monkeypatch.setattr(celery_tasks.settings, "storage_backend", "s3")
    monkeypatch.setattr(celery_tasks.settings, "openai_api_key", "test-key")

    celery_tasks._on_worker_process_init()
    celery_tasks._on_worker_process_shutdown()

    assert calls == ["init_redis", "init_db", "init_fs", "init_s3", "openai"]


def test_worker_process_shutdown_cleanup_is_idempotent_and_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _ok(name: str) -> None:
        calls.append(name)

    async def _fail_redis() -> None:
        calls.append("close_redis")
        raise RuntimeError("redis boom")

    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", lambda: _ok("init_redis"))
    monkeypatch.setattr(celery_tasks, "init_async_db", lambda: _ok("init_db"))
    monkeypatch.setattr(celery_tasks.settings, "storage_backend", "local")
    monkeypatch.setattr(celery_tasks.settings, "openai_api_key", "")
    monkeypatch.setattr(celery_tasks, "close_s3_runtime", lambda: _ok("close_s3"))
    monkeypatch.setattr(celery_tasks, "close_redis_pool_async", _fail_redis)
    monkeypatch.setattr(celery_tasks, "close_async_openai_client", lambda: _ok("close_openai"))
    monkeypatch.setattr(celery_tasks, "close_fs_runtime", lambda: _ok("close_fs"))
    monkeypatch.setattr(celery_tasks, "close_async_db", lambda: _ok("close_db"))

    celery_tasks._on_worker_process_init()
    celery_tasks._on_worker_process_shutdown()
    celery_tasks._on_worker_process_shutdown()

    assert calls.count("close_s3") == 1
    assert calls.count("close_redis") == 1
    assert calls.count("close_openai") == 1
    assert calls.count("close_fs") == 1
    assert calls.count("close_db") == 1


def test_worker_process_init_cleans_up_partial_startup_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _init_redis() -> None:
        calls.append("init_redis")

    async def _init_db() -> None:
        calls.append("init_db")
        raise RuntimeError("db boom")

    async def _close_s3() -> None:
        calls.append("close_s3")

    async def _close_redis() -> None:
        calls.append("close_redis")

    async def _close_openai() -> None:
        calls.append("close_openai")

    async def _close_fs() -> None:
        calls.append("close_fs")

    async def _close_db() -> None:
        calls.append("close_db")

    monkeypatch.setattr(celery_tasks, "init_redis_pool_async", _init_redis)
    monkeypatch.setattr(celery_tasks, "init_async_db", _init_db)
    monkeypatch.setattr(celery_tasks.settings, "storage_backend", "local")
    monkeypatch.setattr(celery_tasks.settings, "openai_api_key", "")
    monkeypatch.setattr(celery_tasks, "close_s3_runtime", _close_s3)
    monkeypatch.setattr(celery_tasks, "close_redis_pool_async", _close_redis)
    monkeypatch.setattr(celery_tasks, "close_async_openai_client", _close_openai)
    monkeypatch.setattr(celery_tasks, "close_fs_runtime", _close_fs)
    monkeypatch.setattr(celery_tasks, "close_async_db", _close_db)

    with pytest.raises(RuntimeError, match="db boom"):
        celery_tasks._on_worker_process_init()

    assert calls == [
        "init_redis",
        "init_db",
        "close_s3",
        "close_redis",
        "close_openai",
        "close_fs",
        "close_db",
    ]


def test_task_entrypoints_use_native_async_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[str] = []

    def _fake_run_async(awaitable):
        recorded.append(awaitable.cr_code.co_name)
        awaitable.close()
        return {"updated": True}

    monkeypatch.setattr(celery_tasks, "_run_async", _fake_run_async)

    celery_tasks.scan_task("j", 1, 1)
    celery_tasks.docs_task("j", 1, 1)
    celery_tasks.run_task_job("j", 1, 1, {})
    celery_tasks.mutation_indexing_task("j", 1, 1, [], "op")
    result = celery_tasks.routing_calibration_task()

    assert recorded == [
        "_scan_task_async",
        "_docs_task_async",
        "_run_task_job_async",
        "_mutation_indexing_task_async",
        "calibrate_routing_policy_thresholds_async",
    ]
    assert result == {"updated": True}


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


@pytest.mark.anyio
async def test_set_job_status_async_sets_completed_at_and_triggers_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_calls: list[str] = []

    class _Job:
        def __init__(self) -> None:
            self.id = "job-1"
            self.queue = "default"
            self.status = "running"
            self.updated_at = None
            self.completed_at = None
            self.error = None
            self.result_json = None

    class _Session:
        def __init__(self, job):
            self._job = job

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return None

        async def get(self, _model, _job_id):
            return self._job

        def add(self, _job):
            return None

        async def commit(self):
            return None

    async def _fake_cleanup(_session):
        cleanup_calls.append("cleanup")

    job = _Job()
    monkeypatch.setattr(celery_tasks, "AsyncSessionLocal", lambda: _Session(job))
    monkeypatch.setattr(celery_tasks, "cleanup_completed_jobs_async", _fake_cleanup)

    await celery_tasks._set_job_status_async("job-1", "succeeded", org_id=1, result={"ok": True})

    assert job.status == "succeeded"
    assert job.completed_at is not None
    assert cleanup_calls == ["cleanup"]


@pytest.mark.anyio
async def test_set_job_status_async_failed_sets_completed_at_and_triggers_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_calls: list[str] = []

    class _Job:
        def __init__(self) -> None:
            self.id = "job-1"
            self.queue = "default"
            self.status = "running"
            self.updated_at = None
            self.completed_at = None
            self.error = None
            self.result_json = None

    class _Session:
        def __init__(self, job):
            self._job = job

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return None

        async def get(self, _model, _job_id):
            return self._job

        def add(self, _job):
            return None

        async def commit(self):
            return None

    async def _fake_cleanup(_session):
        cleanup_calls.append("cleanup")

    job = _Job()
    monkeypatch.setattr(celery_tasks, "AsyncSessionLocal", lambda: _Session(job))
    monkeypatch.setattr(celery_tasks, "cleanup_completed_jobs_async", _fake_cleanup)

    await celery_tasks._set_job_status_async("job-1", "failed", org_id=1, error="boom")

    assert job.status == "failed"
    assert job.completed_at is not None
    assert job.error == "boom"
    assert cleanup_calls == ["cleanup"]
