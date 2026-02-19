import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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
    def _fake_run(*, args, queue):
        _ = (args, queue)
        time.sleep(0.05)

    def _fake_scan(*, args, queue):
        _ = (args, queue)
        time.sleep(0.05)

    with patch("app.celery_tasks.run_task_job.apply_async", side_effect=_fake_run), patch(
        "app.celery_tasks.scan_task.apply_async", side_effect=_fake_scan
    ):
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
async def test_submit_run_async_rolls_back_status_and_inflight_on_enqueue_error(monkeypatch):
    redis_client = _FakeRedisClient()
    monkeypatch.setattr(task_queue, "get_async_redis_client", lambda: redis_client)
    monkeypatch.setattr(task_queue.settings, "task_queue_inflight_heavy_limit", 1)

    with patch("app.celery_tasks.run_task_job.apply_async", side_effect=RuntimeError("broker exploded")):
        with pytest.raises(ExternalServiceError) as exc_ctx:
            await submit_run_async(project_id=99, org_id=42, payload={"fail": True})

    err = exc_ctx.value
    task_id = err.context["task_id"]
    assert err.context["queue"] == "heavy"

    async with AsyncSessionLocal() as session:
        job = await session.get(TaskJob, task_id)

    assert job is not None
    assert job.status == "failed"
    assert job.error == "broker exploded"
    assert isinstance(job.completed_at, datetime)
    assert job.completed_at.tzinfo == timezone.utc
    assert task_id not in redis_client.members
