import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import task_queue


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.anyio
async def test_idempotency_key_async_uses_to_thread(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "idempotency-key"

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    key = await task_queue._idempotency_key_async("scan", 7, {"project_id": 42})

    assert key == "idempotency-key"
    assert captured["func"] is task_queue._idempotency_key
    assert captured["args"] == ("scan", 7, {"project_id": 42})
    assert captured["kwargs"] == {}


@pytest.mark.anyio
async def test_submit_scan_async_uses_async_idempotency_key(monkeypatch):
    calls: list[tuple[int, int]] = []

    async def _fake_get_scan_idempotency_key_async(org_id: int, project_id: int) -> str:
        calls.append((org_id, project_id))
        return "scan-key"

    async def _fake_find_existing_job_id_async(session, org_id: int, idempotency_key: str):
        assert idempotency_key == "scan-key"
        return "existing-job-id"

    monkeypatch.setattr(
        task_queue,
        "get_scan_idempotency_key_async",
        _fake_get_scan_idempotency_key_async,
    )
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_id_async", _fake_find_existing_job_id_async)

    task_id = await task_queue.submit_scan_async(project_id=42, org_id=7)

    assert task_id == "existing-job-id"
    assert calls == [(7, 42)]


@pytest.mark.anyio
async def test_submit_docs_async_uses_async_idempotency_key(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_idempotency_key_async(kind: str, org_id: int, payload: dict) -> str:
        captured["kind"] = kind
        captured["org_id"] = org_id
        captured["payload"] = payload
        return "docs-key"

    async def _fake_find_existing_job_id_async(session, org_id: int, idempotency_key: str):
        assert idempotency_key == "docs-key"
        return "existing-doc-job"

    monkeypatch.setattr(task_queue, "_idempotency_key_async", _fake_idempotency_key_async)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_id_async", _fake_find_existing_job_id_async)

    task_id = await task_queue.submit_docs_async(project_id=99, org_id=5)

    assert task_id == "existing-doc-job"
    assert captured == {
        "kind": "docs",
        "org_id": 5,
        "payload": {"project_id": 99},
    }


@pytest.mark.anyio
async def test_enqueue_celery_task_async_uses_to_thread(monkeypatch):
    calls: dict[str, object] = {}

    class _Task:
        def apply_async(self, *, args, queue):
            _ = (args, queue)
            return None

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return None

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    task = _Task()
    await task_queue._enqueue_celery_task_async(task, args=["a", "b"], queue="heavy")

    assert calls["func"] == task.apply_async
    assert calls["args"] == ()
    assert calls["kwargs"] == {"args": ["a", "b"], "queue": "heavy"}
