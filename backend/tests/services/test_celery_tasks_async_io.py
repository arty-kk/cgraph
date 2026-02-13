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
