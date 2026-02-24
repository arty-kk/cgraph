import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.errors import BadRequestError, ExternalServiceError
from app.infra import celery_producer_runtime
from app.services import task_queue


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False




class _AsyncSessionCtx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
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


class _FakeJob:
    status = "pending"
    error = None
    completed_at = None
    updated_at = None


class _FakeDbSession:
    def __init__(self):
        self.job = _FakeJob()
        self.commits = 0

    async def get(self, model, task_id):
        _ = (model, task_id)
        return self.job

    def add(self, job):
        _ = job

    async def commit(self):
        self.commits += 1


@pytest.mark.anyio
async def test_idempotency_key_async_runs_inline() -> None:
    key = await task_queue._idempotency_key_async("scan", 7, {"project_id": 42})

    assert key == task_queue._idempotency_key("scan", 7, {"project_id": 42})


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
async def test_enqueue_with_error_mapping_uses_async_producer(monkeypatch):
    calls: list[dict[str, object]] = []

    class _Producer:
        async def enqueue_task_async(self, task, *, args, queue):
            calls.append({"task": task, "args": args, "queue": queue})

    monkeypatch.setattr(task_queue, "_async_task_producer", _Producer())

    marker = object()
    await task_queue._enqueue_with_error_mapping_async(
        task=marker,
        args=["job-0", 1],
        queue="heavy",
        task_id="job-0",
    )

    assert calls == [{"task": marker, "args": ["job-0", 1], "queue": "heavy"}]


@pytest.mark.anyio
async def test_async_celery_producer_offloads_sync_send(monkeypatch):
    events: list[str] = []

    def _fake_send_task(name, *, args, queue):
        events.append(f"send:{name}:{queue}:{args[0]}")

    async def _fake_run(fn, *args, **kwargs):
        events.append("offload_called")
        assert fn is _fake_send_task
        assert not any(evt.startswith("send:") for evt in events)
        result = fn(*args, **kwargs)
        events.append("offload_completed")
        return result

    monkeypatch.setattr(task_queue.celery_app, "send_task", _fake_send_task)
    monkeypatch.setattr(celery_producer_runtime, "run_celery_producer_io_async", _fake_run)
    monkeypatch.setattr(task_queue, "run_celery_producer_io_async", _fake_run)

    producer = task_queue._AsyncCeleryProducer()
    task = type("_Task", (), {"name": "stubgraph.scan"})()
    await producer.enqueue_task_async(task, args=["job-99"], queue="medium")

    assert events == [
        "offload_called",
        "send:stubgraph.scan:medium:job-99",
        "offload_completed",
    ]


@pytest.mark.anyio
async def test_enqueue_error_mapping_timeout(monkeypatch):
    session = _FakeDbSession()

    async def _offloaded_enqueue(task, *, args, queue):
        _ = (task, args, queue)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(task_queue, "_ENQUEUE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _offloaded_enqueue)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _AsyncSessionCtx(session))

    with pytest.raises(ExternalServiceError) as exc_ctx:
        await task_queue._enqueue_with_error_mapping_async(
            task=object(),
            args=["job-1"],
            queue="medium",
            task_id="job-1",
        )

    assert exc_ctx.value.context["enqueue_reason"] == "timeout"
    assert session.commits == 1


@pytest.mark.anyio
async def test_enqueue_error_mapping_cancellation(monkeypatch):
    session = _FakeDbSession()

    async def _cancelled_enqueue(task, *, args, queue):
        _ = (task, args, queue)
        raise asyncio.CancelledError()

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _cancelled_enqueue)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _AsyncSessionCtx(session))

    with pytest.raises(ExternalServiceError) as exc_ctx:
        await task_queue._enqueue_with_error_mapping_async(
            task=object(),
            args=["job-cancel"],
            queue="medium",
            task_id="job-cancel",
        )

    assert exc_ctx.value.context["enqueue_reason"] == "internal_enqueue_failure"
    assert session.commits == 1


@pytest.mark.anyio
async def test_enqueue_error_mapping_broker_error(monkeypatch):
    session = _FakeDbSession()

    async def _broken_enqueue(task, *, args, queue):
        _ = (task, args, queue)
        raise task_queue._AsyncTaskProducerError("broker down")

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _broken_enqueue)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _AsyncSessionCtx(session))

    with pytest.raises(ExternalServiceError) as exc_ctx:
        await task_queue._enqueue_with_error_mapping_async(
            task=object(),
            args=["job-2"],
            queue="medium",
            task_id="job-2",
        )

    assert exc_ctx.value.context["enqueue_reason"] == "broker_error"


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
        _ = task
        enqueue_calls.append({"args": args, "queue": queue})

    monkeypatch.setattr(task_queue, "uuid4", lambda: _UUID())
    monkeypatch.setattr(task_queue, "_idempotency_key_async", _fake_idempotency)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_id_async", _fake_find_existing)
    monkeypatch.setattr(task_queue, "_create_job_async", _fake_create_job)
    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _fake_enqueue)
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


@pytest.mark.anyio
async def test_submit_scan_async_releases_db_session_before_enqueue(monkeypatch):
    events: list[str] = []

    class _Session:
        pass

    class _Ctx:
        async def __aenter__(self):
            events.append("db_enter")
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            events.append("db_exit")
            return False

    async def _fake_find_existing(*_args, **_kwargs):
        return None

    async def _fake_create_job(*_args, **_kwargs):
        return "scan-job", True

    async def _fake_enqueue(_task, *, args, queue):
        _ = (args, queue)
        events.append("enqueue")

    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _Ctx())
    monkeypatch.setattr(task_queue, "get_scan_idempotency_key_async", lambda *_args, **_kwargs: asyncio.sleep(0, result="scan-key"))
    monkeypatch.setattr(task_queue, "_find_existing_job_id_async", _fake_find_existing)
    monkeypatch.setattr(task_queue, "_create_job_async", _fake_create_job)
    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _fake_enqueue)

    task_id = await task_queue.submit_scan_async(project_id=1, org_id=2)

    assert task_id == "scan-job"
    assert events == ["db_enter", "db_exit", "enqueue"]
