import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.errors import BadRequestError
from app.services import task_queue


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeRedisClient:
    def __init__(self, *, eval_result=(1, 1)):
        self.eval_result = eval_result
        self.eval_calls: list[tuple[object, ...]] = []

    async def eval(self, script, numkeys, key, limit, job_id):
        self.eval_calls.append((script, numkeys, key, limit, job_id))
        return self.eval_result

    async def scard(self, key):
        _ = key
        return 0

    async def srem(self, key, value):
        _ = (key, value)

    async def delete(self, key):
        _ = key

    async def sadd(self, key, *values):
        _ = (key, values)


class _FakeRedisContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

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


@pytest.mark.anyio
async def test_guard_inflight_async_does_not_materialize_task_ids(monkeypatch):
    client = _FakeRedisClient(eval_result=(1, 1))

    class _Session:
        execute_calls = 0

        async def execute(self, statement):
            _ = statement
            self.execute_calls += 1
            raise AssertionError("_guard_inflight_async must not query TaskJob ids")

    session = _Session()
    monkeypatch.setattr(task_queue.settings, "task_queue_inflight_heavy_limit", 2)
    monkeypatch.setattr(task_queue, "get_async_redis_client", lambda: client)

    await task_queue._guard_inflight_async(session, "heavy", "job-1")

    assert session.execute_calls == 0
    assert len(client.eval_calls) == 1


@pytest.mark.anyio
async def test_guard_inflight_async_raises_bad_request_when_limit_exhausted(monkeypatch):
    client = _FakeRedisClient(eval_result=(0, 2))
    monkeypatch.setattr(task_queue.settings, "task_queue_inflight_heavy_limit", 2)
    monkeypatch.setattr(task_queue, "get_async_redis_client", lambda: client)

    with pytest.raises(BadRequestError):
        await task_queue._guard_inflight_async(object(), "heavy", "job-1")


@pytest.mark.anyio
async def test_submit_run_async_enqueues_when_quota_available(monkeypatch):
    client = _FakeRedisClient(eval_result=(1, 1))
    enqueue_calls: list[dict[str, object]] = []

    class _UUID:
        hex = "job-1"

    async def _fake_idempotency(*args, **kwargs):
        _ = (args, kwargs)
        return "idempotency-key"

    async def _fake_find_existing(*args, **kwargs):
        _ = (args, kwargs)
        return None

    async def _fake_create_job(*args, **kwargs):
        _ = (args, kwargs)
        return "job-1", True

    async def _fake_enqueue(task, *, args, queue):
        enqueue_calls.append({"task": task, "args": args, "queue": queue})

    monkeypatch.setattr(task_queue, "uuid4", lambda: _UUID())
    monkeypatch.setattr(task_queue, "_idempotency_key_async", _fake_idempotency)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_id_async", _fake_find_existing)
    monkeypatch.setattr(task_queue, "_create_job_async", _fake_create_job)
    monkeypatch.setattr(task_queue, "_enqueue_celery_task_async", _fake_enqueue)
    monkeypatch.setattr(task_queue.settings, "task_queue_inflight_heavy_limit", 2)
    monkeypatch.setattr(task_queue, "get_async_redis_client", lambda: client)

    task_id = await task_queue.submit_run_async(project_id=12, org_id=99, payload={"a": 1})

    assert task_id == "job-1"
    assert len(client.eval_calls) == 1
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["args"] == ["job-1", 12, 99, {"a": 1}]
    assert enqueue_calls[0]["queue"] == "heavy"


@pytest.mark.anyio
async def test_guard_inflight_async_uses_shared_client_concurrently(monkeypatch):
    client = _FakeRedisClient(eval_result=(1, 1))
    get_client_calls = 0

    def _get_client():
        nonlocal get_client_calls
        get_client_calls += 1
        return client

    monkeypatch.setattr(task_queue.settings, "task_queue_inflight_heavy_limit", 3)
    monkeypatch.setattr(task_queue, "get_async_redis_client", _get_client)

    await asyncio.gather(
        task_queue._guard_inflight_async(object(), "heavy", "job-1"),
        task_queue._guard_inflight_async(object(), "heavy", "job-2"),
    )

    assert get_client_calls == 2
    assert [call[4] for call in client.eval_calls] == ["job-1", "job-2"]
