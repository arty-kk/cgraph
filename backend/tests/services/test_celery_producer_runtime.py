import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import celery_producer_runtime


def _sleep_and_return(delay_s: float, value: int) -> int:
    time.sleep(delay_s)
    return value


@pytest.mark.anyio
async def test_run_celery_producer_io_async_keeps_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(celery_producer_runtime.settings, "task_queue_producer_workers", 2)
    monkeypatch.setattr(celery_producer_runtime.settings, "task_queue_producer_concurrency", 2)
    await celery_producer_runtime.close_celery_producer_runtime()
    await celery_producer_runtime.init_celery_producer_runtime()

    ticks = 0
    stop = asyncio.Event()

    async def _ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    ticker_task = asyncio.create_task(_ticker())
    try:
        results = await asyncio.gather(
            celery_producer_runtime.run_celery_producer_io_async(_sleep_and_return, 0.05, 1),
            celery_producer_runtime.run_celery_producer_io_async(_sleep_and_return, 0.05, 2),
            celery_producer_runtime.run_celery_producer_io_async(_sleep_and_return, 0.05, 3),
        )
    finally:
        stop.set()
        await ticker_task

    assert sorted(results) == [1, 2, 3]
    assert ticks > 1

    await celery_producer_runtime.close_celery_producer_runtime()


@pytest.mark.anyio
async def test_celery_producer_runtime_reinit_on_other_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(celery_producer_runtime.settings, "task_queue_producer_workers", 1)
    monkeypatch.setattr(celery_producer_runtime.settings, "task_queue_producer_concurrency", 1)

    await celery_producer_runtime.close_celery_producer_runtime()
    await celery_producer_runtime.init_celery_producer_runtime()
    runtime_first = celery_producer_runtime._producer_runtime
    assert runtime_first is not None

    worker_result: dict[str, int] = {}

    def _run_in_thread() -> None:
        worker_result["value"] = asyncio.run(
            celery_producer_runtime.run_celery_producer_io_async(_sleep_and_return, 0.01, 41)
        )

    thread = threading.Thread(target=_run_in_thread)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert worker_result["value"] == 41

    await celery_producer_runtime.run_celery_producer_io_async(_sleep_and_return, 0.01, 42)
    runtime_final = celery_producer_runtime._producer_runtime
    assert runtime_final is not None
    assert runtime_final.loop is asyncio.get_running_loop()

    await celery_producer_runtime.close_celery_producer_runtime()


@pytest.mark.anyio
async def test_celery_producer_runtime_bounded_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(celery_producer_runtime.settings, "task_queue_producer_workers", 2)
    monkeypatch.setattr(celery_producer_runtime.settings, "task_queue_producer_concurrency", 2)
    await celery_producer_runtime.close_celery_producer_runtime()

    lock = threading.Lock()
    in_flight = 0
    peak_in_flight = 0

    def _slow_publish(delay_s: float) -> None:
        nonlocal in_flight, peak_in_flight
        with lock:
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)
        try:
            time.sleep(delay_s)
        finally:
            with lock:
                in_flight -= 1

    started = time.monotonic()
    await asyncio.gather(
        *[
            celery_producer_runtime.run_celery_producer_io_async(_slow_publish, 0.04)
            for _ in range(10)
        ]
    )
    elapsed = time.monotonic() - started

    assert peak_in_flight <= 2
    assert elapsed >= 0.16

    await celery_producer_runtime.close_celery_producer_runtime()
