import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import task_handlers
from app.async_db import AsyncSessionLocal
from app.errors import ExternalServiceError
from app.infra import redis_client
from app.models import TaskJob
from app.services import task_queue
from app.services.task_queue import submit_run_async, submit_scan_async
from tests.services.db_helpers import ensure_async_postgres  # noqa: F401


class _FakeRedisClient:
    def __init__(self):
        self.members: set[str] = set()

    async def eval(self, script, numkeys, key, limit, job_id):
        _ = (script, numkeys, key)
        if len(self.members) >= int(limit):
            return 0, len(self.members)
        self.members.add(job_id)
        return 1, len(self.members)

    async def srem(self, key, value):
        _ = key
        self.members.discard(value)

    async def scard(self, key):
        _ = key
        return len(self.members)

    async def delete(self, key):
        _ = key
        self.members.clear()

    async def sadd(self, key, *values):
        _ = key
        self.members.update(values)


@pytest.mark.anyio
@pytest.mark.usefixtures("ensure_async_postgres")
async def test_parallel_submit_is_idempotent_and_non_blocking(monkeypatch):
    async def _fake_enqueue(_task, *, args, queue):
        _ = (args, queue)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _fake_enqueue)

    started = time.monotonic()
    run_id, scan_id = await asyncio.wait_for(
        asyncio.gather(
            submit_run_async(project_id=11, org_id=77, payload={"a": 1}),
            submit_scan_async(project_id=11, org_id=77),
        ),
        timeout=2,
    )
    elapsed = time.monotonic() - started

    run_id_repeat, scan_id_repeat = await asyncio.wait_for(
        asyncio.gather(
            submit_run_async(project_id=11, org_id=77, payload={"a": 1}),
            submit_scan_async(project_id=11, org_id=77),
        ),
        timeout=2,
    )

    assert elapsed < 1
    assert run_id_repeat == run_id
    assert scan_id_repeat == scan_id


@pytest.mark.anyio
@pytest.mark.usefixtures("ensure_async_postgres")
async def test_high_concurrency_submit_scan_not_serialized(monkeypatch):
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def _slow_async_enqueue(_task, *, args, queue):
        nonlocal active, peak
        _ = (args, queue)
        async with lock:
            active += 1
            peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)
        finally:
            async with lock:
                active -= 1

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _slow_async_enqueue)

    started = time.monotonic()
    task_ids = await asyncio.wait_for(
        asyncio.gather(*[submit_scan_async(project_id=1000 + i, org_id=77) for i in range(40)]),
        timeout=6,
    )
    elapsed = time.monotonic() - started

    assert len(set(task_ids)) == 40
    assert elapsed < 2.5
    assert peak > 1


@pytest.mark.anyio
@pytest.mark.usefixtures("ensure_async_postgres")
async def test_submit_run_async_rolls_back_status_and_inflight_on_enqueue_error(monkeypatch):
    redis_client = _FakeRedisClient()
    monkeypatch.setattr(task_queue, "get_async_redis_client", lambda: redis_client)
    monkeypatch.setattr(task_queue.settings, "task_queue_inflight_heavy_limit", 1)

    async def _boom_enqueue(_task, *, args, queue):
        _ = (args, queue)
        raise task_queue._AsyncTaskProducerError("broker exploded")

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _boom_enqueue)

    with pytest.raises(ExternalServiceError) as exc_ctx:
        await submit_run_async(project_id=99, org_id=42, payload={"fail": True})

    err = exc_ctx.value
    task_id = err.context["task_id"]
    assert err.context["queue"] == "heavy"
    assert err.context["enqueue_reason"] == "broker_error"

    async with AsyncSessionLocal() as session:
        job = await session.get(TaskJob, task_id)

    assert job is not None
    assert job.status == "failed"
    assert job.error == "broker exploded"
    assert isinstance(job.completed_at, datetime)
    assert job.completed_at.tzinfo == timezone.utc
    assert task_id not in redis_client.members


@pytest.mark.anyio
@pytest.mark.usefixtures("ensure_async_postgres")
async def test_parallel_submit_scan_burst_keeps_loop_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = 0
    stop = asyncio.Event()

    async def _slow_async_publish(_task_name, *, args, queue):
        _ = (args, queue)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _slow_async_publish)

    async def _ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    ticker_task = asyncio.create_task(_ticker())
    started = time.monotonic()
    try:
        task_ids = await asyncio.wait_for(
            asyncio.gather(*[submit_scan_async(project_id=3000 + i, org_id=88) for i in range(20)]),
            timeout=5,
        )
    finally:
        stop.set()
        await ticker_task

    elapsed = time.monotonic() - started
    assert len(set(task_ids)) == 20
    assert ticks > 10
    assert elapsed < 2


@pytest.mark.anyio
@pytest.mark.usefixtures("ensure_async_postgres")
async def test_submit_run_to_execute_updates_job_status(monkeypatch):
    async def _immediate_enqueue(task_name, *, args, queue):
        _ = queue
        if task_name == "stubgraph.run_task":
            await task_handlers.execute_task_by_name_async("stubgraph.run_task", list(args))

    async def _fake_run_task_async(_project_id, _org_id, _request):
        return {"ok": True}

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _immediate_enqueue)
    monkeypatch.setattr(task_handlers, "run_task_async", _fake_run_task_async)
    monkeypatch.setattr(task_handlers, "_touch_inflight_async", lambda _job_id: asyncio.sleep(0))
    monkeypatch.setattr(task_handlers, "_decrement_inflight_async", lambda _job_id: asyncio.sleep(0))

    task_id = await submit_run_async(project_id=1, org_id=42, payload={"query": "x"})

    async with AsyncSessionLocal() as session:
        job = await session.get(TaskJob, task_id)

    assert job is not None
    assert job.status == "succeeded"


@pytest.mark.anyio
async def test_task_queue_transport_reuses_single_arq_pool_client(monkeypatch):
    class _FakeArq:
        def __init__(self) -> None:
            self.published: list[tuple[str, tuple[object, ...], str, str]] = []

        async def enqueue_job(self, task_name: str, *args: object, _job_id: str, _queue_name: str) -> None:
            self.published.append((task_name, args, _job_id, _queue_name))

    fake_arq = _FakeArq()

    async def _fake_get_arq_pool_async():
        return fake_arq

    monkeypatch.setattr(task_queue, "get_arq_pool_async", _fake_get_arq_pool_async)
    client = task_queue._AsyncTaskTransportClient()
    await client.publish_async(task_name="stubgraph.scan", args=["job-1", 1], queue="medium")

    assert len(fake_arq.published) == 1


@pytest.mark.anyio
async def test_task_queue_transport_mass_publish_uses_single_arq_pool(monkeypatch):
    class _FakeArq:
        def __init__(self) -> None:
            self.published = 0

        async def enqueue_job(self, task_name: str, *args: object, _job_id: str, _queue_name: str) -> None:
            _ = (task_name, args, _job_id, _queue_name)
            self.published += 1

    fake_arq = _FakeArq()

    async def _fake_get_arq_pool_async():
        return fake_arq

    monkeypatch.setattr(task_queue, "get_arq_pool_async", _fake_get_arq_pool_async)
    transport = task_queue._AsyncTaskTransportClient()
    await asyncio.gather(
        *[
            transport.publish_async(
                task_name="stubgraph.scan",
                args=[f"job-{idx}", idx],
                queue="medium",
            )
            for idx in range(200)
        ]
    )

    assert fake_arq.published == 200
