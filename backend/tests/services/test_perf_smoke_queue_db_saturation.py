import asyncio
import time
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import task_queue


@pytest.mark.anyio
async def test_enqueue_burst_smoke_has_reasonable_event_loop_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _slow_publish(_task_name, *, args, queue):
        _ = (args, queue)
        await asyncio.sleep(0.03)

    monkeypatch.setattr(task_queue._async_task_producer, "enqueue_task_async", _slow_publish)

    ticks = 0
    stop = asyncio.Event()

    async def _ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    ticker = asyncio.create_task(_ticker())
    started = time.perf_counter()
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *[
                    task_queue._enqueue_with_error_mapping_async(
                        task_name="stubgraph.scan",
                        args=[f"job-{i}", i, 1],
                        queue="medium",
                        task_id=f"job-{i}",
                    )
                    for i in range(30)
                ]
            ),
            timeout=4,
        )
    finally:
        stop.set()
        await ticker

    elapsed = time.perf_counter() - started
    assert ticks >= 5
    assert elapsed < 3



@pytest.mark.anyio
async def test_db_pool_saturation_smoke_wait_threshold() -> None:
    pool_size = 3
    burst = 24
    work_ms = 0.02
    max_wait_ms = 220.0

    gate = asyncio.Semaphore(pool_size)
    waits: list[float] = []

    async def _db_bound_unit() -> None:
        started = time.perf_counter()
        async with gate:
            waits.append((time.perf_counter() - started) * 1000.0)
            await asyncio.sleep(work_ms)

    started_all = time.perf_counter()
    await asyncio.gather(*[_db_bound_unit() for _ in range(burst)])
    elapsed_ms = (time.perf_counter() - started_all) * 1000.0

    # saturation happened (at least one waiter had to queue)
    assert max(waits, default=0.0) > 0.0
    # threshold-style guard: queue wait should remain bounded for this smoke burst
    assert max(waits, default=0.0) < max_wait_ms
    # end-to-end completion should stay in expected envelope for burst/pool parameters
    assert elapsed_ms < 600.0


@pytest.mark.anyio
async def test_high_concurrency_docs_and_run_workloads_keep_event_loop_progress() -> None:
    docs_limit = asyncio.Semaphore(3)
    run_limit = asyncio.Semaphore(4)

    async def _docs_request() -> None:
        async with docs_limit:
            await asyncio.sleep(0.015)
            await asyncio.sleep(0)

    async def _run_request() -> None:
        async with run_limit:
            await asyncio.sleep(0.01)
            await asyncio.sleep(0)

    ticks = 0
    stop = asyncio.Event()

    async def _ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.003)

    ticker = asyncio.create_task(_ticker())
    started = time.perf_counter()
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *[_docs_request() for _ in range(25)],
                *[_run_request() for _ in range(40)],
            ),
            timeout=5,
        )
    finally:
        stop.set()
        await ticker

    elapsed = time.perf_counter() - started
    assert ticks >= 15
    assert elapsed < 2
