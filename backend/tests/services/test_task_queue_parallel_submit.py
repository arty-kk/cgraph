import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal
from app.errors import ExternalServiceError
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
