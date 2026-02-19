import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import celery_tasks


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(celery_tasks.asyncio, "to_thread", _fake_to_thread)

    result = await celery_tasks._normalize_project_root_async("/repo")

    assert result == Path("/repo")
    assert calls["func"] is celery_tasks.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {}


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


def test_worker_shutdown_cleanup_calls_all_close_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_close_redis() -> None:
        calls.append("close_redis")

    async def _fake_close_openai() -> None:
        calls.append("close_openai")

    async def _fake_close_db() -> None:
        calls.append("close_db")

    monkeypatch.setattr(celery_tasks, "close_redis_pool_async", _fake_close_redis)
    monkeypatch.setattr(celery_tasks, "close_async_openai_client", _fake_close_openai)
    monkeypatch.setattr(celery_tasks, "close_async_db", _fake_close_db)

    celery_tasks._on_worker_shutdown()

    assert calls == ["close_redis", "close_openai", "close_db"]
