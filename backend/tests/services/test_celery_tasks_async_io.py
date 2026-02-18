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
async def test_mutation_indexing_task_async_uses_async_indexer(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(celery_tasks, "_resolve_project_root_async", _fake_resolve_project_root_async)
    monkeypatch.setattr(celery_tasks, "run_mutation_indexing_async", _fake_run_mutation_indexing_async)
    monkeypatch.setattr(celery_tasks, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(celery_tasks.asyncio, "to_thread", _fail_to_thread)

    await celery_tasks._mutation_indexing_task_async("job-1", 1, 7, ["a.py"], "update")

    assert "index" in calls
