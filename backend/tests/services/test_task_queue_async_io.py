import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.errors import BadRequestError, ExternalServiceError
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
async def test_idempotency_key_async_uses_cpu_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_run_cpu_io_async(fn, *args, operation=None, **kwargs):
        calls.append({"fn": fn, "args": args, "kwargs": kwargs, "operation": operation})
        return fn(*args, **kwargs)

    monkeypatch.setattr(task_queue, "run_cpu_io_async", _fake_run_cpu_io_async)

    payload = {"project_id": 42}
    key = await task_queue._idempotency_key_async("scan", 7, payload)

    assert key == task_queue._idempotency_key("scan", 7, payload)
    assert calls == [
        {
            "fn": task_queue._idempotency_key,
            "args": ("scan", 7, payload),
            "kwargs": {},
            "operation": "task_queue.idempotency_key",
        }
    ]


@pytest.mark.anyio
async def test_idempotency_key_async_concurrent_is_deterministic_and_keeps_loop_responsive() -> None:
    same_payload = {"project_id": 42, "filters": {"lang": "py", "paths": ["a", "b"]}}
    different_payload = {"project_id": 42, "filters": {"lang": "py", "paths": ["a", "c"]}}

    ticks = 0
    stop = asyncio.Event()

    async def _ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.001)

    ticker_task = asyncio.create_task(_ticker())
    try:
        same_a, same_b, different = await asyncio.gather(
            task_queue._idempotency_key_async("scan", 7, same_payload),
            task_queue._idempotency_key_async("scan", 7, same_payload),
            task_queue._idempotency_key_async("scan", 7, different_payload),
        )
    finally:
        stop.set()
        await ticker_task

    assert same_a == same_b
    assert different != same_a
    assert same_a == task_queue._idempotency_key("scan", 7, same_payload)
    assert different == task_queue._idempotency_key("scan", 7, different_payload)
    assert ticks > 0


@pytest.mark.anyio
async def test_submit_scan_async_uses_async_idempotency_key(monkeypatch):
    calls: list[tuple[int, int]] = []

    async def _fake_get_scan_idempotency_key_async(org_id: int, project_id: int) -> str:
        calls.append((org_id, project_id))
        return "scan-key"

    async def _fake_find_existing_job_async(session, org_id: int, idempotency_key: str):
        _ = (session, org_id)
        assert idempotency_key == "scan-key"
        return "existing-job-id", "running"

    monkeypatch.setattr(
        task_queue,
        "get_scan_idempotency_key_async",
        _fake_get_scan_idempotency_key_async,
    )
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_async", _fake_find_existing_job_async)

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

    async def _fake_find_existing_job_async(session, org_id: int, idempotency_key: str):
        assert idempotency_key == "docs-key"
        return ("existing-doc-job", "running")

    monkeypatch.setattr(task_queue, "_idempotency_key_async", _fake_idempotency_key_async)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_async", _fake_find_existing_job_async)

    result = await task_queue.submit_docs_async(project_id=99, org_id=5)

    assert result == ("existing-doc-job", "running")
    assert captured == {
        "kind": "docs",
        "org_id": 5,
        "payload": {"project_id": 99},
    }




@pytest.mark.anyio
async def test_submit_run_async_uses_string_idempotency_key_for_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_keys: list[str] = []

    async def _fake_idempotency_key_async(kind: str, org_id: int, payload: dict) -> str:
        _ = (kind, org_id, payload)
        return "run-key"

    async def _fake_find_existing_job_id_async(session, org_id: int, idempotency_key: str):
        _ = (session, org_id)
        captured_keys.append(idempotency_key)
        return "existing-run-job"

    monkeypatch.setattr(task_queue, "_idempotency_key_async", _fake_idempotency_key_async)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_id_async", _fake_find_existing_job_id_async)

    task_id = await task_queue.submit_run_async(project_id=21, org_id=3, payload={"q": "x"})

    assert task_id == "existing-run-job"
    assert captured_keys == ["run-key"]


@pytest.mark.anyio
async def test_submit_snapshot_import_async_uses_string_idempotency_key_for_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_keys: list[str] = []

    async def _fake_idempotency_key_async(kind: str, org_id: int, payload: dict) -> str:
        _ = (kind, org_id, payload)
        return "snapshot-key"

    async def _fake_find_existing_job_async(session, org_id: int, idempotency_key: str):
        _ = (session, org_id)
        captured_keys.append(idempotency_key)
        return "existing-snapshot-job", "running"

    monkeypatch.setattr(task_queue, "_idempotency_key_async", _fake_idempotency_key_async)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_async", _fake_find_existing_job_async)

    result = await task_queue.submit_snapshot_import_async(
        name="repo",
        archive_name="repo.zip",
        staged_path="/tmp/repo.zip",
        org_id=3,
    )

    assert result == ("existing-snapshot-job", "running")
    assert captured_keys == ["snapshot-key"]


@pytest.mark.anyio
async def test_submit_mutation_indexing_async_uses_string_idempotency_key_for_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_keys: list[str] = []

    async def _fake_idempotency_key_async(kind: str, org_id: int, payload: dict) -> str:
        _ = (kind, org_id, payload)
        return "mutation-key"

    async def _fake_find_existing_job_async(session, org_id: int, idempotency_key: str):
        _ = (session, org_id)
        captured_keys.append(idempotency_key)
        return "existing-mutation-job", "running"

    monkeypatch.setattr(task_queue, "_idempotency_key_async", _fake_idempotency_key_async)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_async", _fake_find_existing_job_async)

    result = await task_queue.submit_mutation_indexing_async(
        project_id=8,
        org_id=3,
        rel_paths=["repo/a.py"],
        operation="update_file",
    )

    assert result == ("existing-mutation-job", "running")
    assert captured_keys == ["mutation-key"]


@pytest.mark.anyio
async def test_submit_docs_async_returns_existing_status_after_integrity_race(monkeypatch):
    async def _fake_idempotency_key_async(kind: str, org_id: int, payload: dict) -> str:
        _ = (kind, org_id, payload)
        return "docs-key"

    async def _fake_find_existing_job_async(session, org_id: int, idempotency_key: str):
        _ = (session, org_id, idempotency_key)
        return ("existing-doc-job", "running")

    async def _fake_create_job_async(*args, **kwargs):
        _ = (args, kwargs)
        return ("existing-doc-job", False)

    monkeypatch.setattr(task_queue, "_idempotency_key_async", _fake_idempotency_key_async)
    monkeypatch.setattr(task_queue, "AsyncSessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr(task_queue, "_find_existing_job_async", _fake_find_existing_job_async)
    monkeypatch.setattr(task_queue, "_create_job_async", _fake_create_job_async)

    result = await task_queue.submit_docs_async(project_id=99, org_id=5)

    assert result == ("existing-doc-job", "running")

@pytest.mark.anyio
async def test_enqueue_with_error_mapping_uses_async_producer(monkeypatch):
    calls: list[dict[str, object]] = []

    class _Producer:
        async def enqueue_task_async(self, task_name, *, args, queue):
            calls.append({"task_name": task_name, "args": args, "queue": queue})

    monkeypatch.setattr(task_queue, "_async_task_producer", _Producer())

    await task_queue._enqueue_with_error_mapping_async(
        session=_FakeDbSession(),
        task_name="stubgraph.scan",
        args=["job-0", 1],
        queue="heavy",
        task_id="job-0",
    )

    assert calls == [{"task_name": "stubgraph.scan", "args": ["job-0", 1], "queue": "heavy"}]


@pytest.mark.anyio
async def test_async_task_producer_uses_async_transport_client(monkeypatch):
    calls: list[tuple[str, list[object], str]] = []

    class _Client:
        async def publish_async(self, *, task_name: str, args: list[object], queue: str) -> None:
            calls.append((task_name, args, queue))

    producer = task_queue._AsyncTaskProducer(client=_Client())
    await producer.enqueue_task_async("stubgraph.scan", args=["job-99"], queue="medium")

    assert calls == [("stubgraph.scan", ["job-99"], "medium")]


@pytest.mark.anyio
async def test_transport_client_enqueues_arq_job_via_runtime_client(monkeypatch):
    class _FakeArq:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...], str, str]] = []

        async def enqueue_job(self, task_name: str, *args: object, _job_id: str, _queue_name: str) -> None:
            self.calls.append((task_name, args, _job_id, _queue_name))

    fake_arq = _FakeArq()

    async def _fake_get_transport_client_async():
        return fake_arq

    monkeypatch.setattr(task_queue, "get_task_transport_redis_client_async", _fake_get_transport_client_async)

    client = task_queue._AsyncTaskTransportClient()
    await client.publish_async(task_name="stubgraph.scan", args=["job-7", 1, 2], queue="medium")

    assert fake_arq.calls == [
        ("stubgraph.scan", ("job-7", 1, 2), "job-7", "medium")
    ]


@pytest.mark.anyio
async def test_enqueue_error_mapping_timeout(monkeypatch):
    session = _FakeDbSession()

    async def _offloaded_enqueue(task, *, args, queue):
        _ = (task, args, queue)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(task_queue, "_ENQUEUE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _offloaded_enqueue)

    with pytest.raises(ExternalServiceError) as exc_ctx:
        await task_queue._enqueue_with_error_mapping_async(
            session=session,
            task_name="stubgraph.scan",
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

    with pytest.raises(ExternalServiceError) as exc_ctx:
        await task_queue._enqueue_with_error_mapping_async(
            session=session,
            task_name="stubgraph.scan",
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

    with pytest.raises(ExternalServiceError) as exc_ctx:
        await task_queue._enqueue_with_error_mapping_async(
            session=session,
            task_name="stubgraph.scan",
            args=["job-2"],
            queue="medium",
            task_id="job-2",
        )

    assert exc_ctx.value.context["enqueue_reason"] == "broker_error"


@pytest.mark.anyio
async def test_enqueue_retry_succeeds_after_transient_broker_error(monkeypatch):
    attempts = 0

    async def _flaky_enqueue(task_name, *, args, queue):
        nonlocal attempts
        _ = (task_name, args, queue)
        attempts += 1
        if attempts == 1:
            raise task_queue._AsyncTaskProducerError("temporary")

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _flaky_enqueue)

    with pytest.raises(ExternalServiceError):
        await task_queue._enqueue_with_error_mapping_async(
            session=_FakeDbSession(),
            task_name="stubgraph.scan",
            args=["job-r"],
            queue="medium",
            task_id="job-r",
        )

    await task_queue._enqueue_with_error_mapping_async(
        session=_FakeDbSession(),
        task_name="stubgraph.scan",
        args=["job-r"],
        queue="medium",
        task_id="job-r",
    )
    assert attempts == 2


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
async def test_guard_inflight_async_retries_after_reconcile(monkeypatch):
    eval_results = [(0, 2), (1, 2)]
    eval_calls: list[tuple[object, ...]] = []
    reconcile_calls = 0

    class _RedisClient:
        async def eval(self, script, numkeys, key, limit, job_id):
            eval_calls.append((script, numkeys, key, limit, job_id))
            return eval_results.pop(0)

    async def _fake_reconcile():
        nonlocal reconcile_calls
        reconcile_calls += 1

    monkeypatch.setattr(task_queue.settings, "task_queue_inflight_heavy_limit", 2)
    monkeypatch.setattr(task_queue, "get_async_redis_client", lambda: _RedisClient())
    monkeypatch.setattr(task_queue, "_reconcile_heavy_inflight_async", _fake_reconcile)

    await task_queue._guard_inflight_async(object(), "heavy", "job-1")

    assert len(eval_calls) == 2
    assert reconcile_calls == 1


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
async def test_submit_scan_async_keeps_single_session_for_enqueue_failure_updates(monkeypatch):
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
    monkeypatch.setattr(
        task_queue,
        "get_scan_idempotency_key_async",
        lambda *_args, **_kwargs: asyncio.sleep(0, result="scan-key"),
    )
    monkeypatch.setattr(task_queue, "_find_existing_job_async", _fake_find_existing)
    monkeypatch.setattr(task_queue, "_create_job_async", _fake_create_job)
    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _fake_enqueue)

    task_id = await task_queue.submit_scan_async(project_id=1, org_id=2)

    assert task_id == "scan-job"
    assert events == ["db_enter", "enqueue", "db_exit"]


@pytest.mark.anyio
async def test_get_task_transport_redis_client_async_uses_arq_pool(monkeypatch):
    class _FakeArq:
        pass

    fake_arq = _FakeArq()
    calls: list[str] = []

    async def _fake_get_arq_pool_async():
        calls.append("pool")
        return fake_arq

    monkeypatch.setattr(task_queue, "get_arq_pool_async", _fake_get_arq_pool_async)

    client = await task_queue.get_task_transport_redis_client_async()

    assert client is fake_arq
    assert calls == ["pool"]


@pytest.mark.anyio
async def test_get_task_transport_redis_client_async_does_not_use_sync_redis_runtime(monkeypatch):
    async def _fake_get_arq_pool_async():
        return object()

    monkeypatch.setattr(task_queue, "get_arq_pool_async", _fake_get_arq_pool_async)
    monkeypatch.setattr(
        task_queue,
        "get_async_redis_client",
        lambda: (_ for _ in ()).throw(AssertionError("sync redis runtime must not be used")),
    )

    await task_queue.get_task_transport_redis_client_async()
