import asyncio
import sys
import time
from pathlib import Path
from threading import Event

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import cpu_runtime


@pytest.mark.anyio
async def test_cpu_runtime_init_and_close_are_idempotent() -> None:
    await cpu_runtime.init_cpu_runtime()
    await cpu_runtime.init_cpu_runtime()

    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.close_cpu_runtime()


@pytest.mark.anyio
async def test_run_cpu_io_async_executes_and_tracks_queue_peaks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_workers", 1)
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_concurrency", 1)
    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.init_cpu_runtime()

    def _slow(label: str) -> str:
        time.sleep(0.03)
        return label

    first, second = await asyncio.gather(
        cpu_runtime.run_cpu_io_async(_slow, "a", operation="test.slow"),
        cpu_runtime.run_cpu_io_async(_slow, "b", operation="test.slow"),
    )

    assert {first, second} == {"a", "b"}
    runtime = cpu_runtime._cpu_runtime
    assert runtime is not None
    assert runtime.peak_queue_depth >= 1
    assert runtime.peak_in_flight == 1

    await cpu_runtime.close_cpu_runtime()


@pytest.mark.anyio
async def test_close_cpu_runtime_waits_for_running_task_and_is_safe_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_workers", 1)
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_concurrency", 1)
    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.init_cpu_runtime()

    started = Event()
    release = Event()

    def _blocking() -> str:
        started.set()
        release.wait(timeout=1)
        return "done"

    task = asyncio.create_task(cpu_runtime.run_cpu_io_async(_blocking))
    loop = asyncio.get_running_loop()
    await asyncio.wait_for(loop.run_in_executor(None, started.wait, 1), timeout=1)

    close_task = asyncio.create_task(cpu_runtime.close_cpu_runtime())
    assert not close_task.done()
    release.set()
    await close_task

    assert await task == "done"
    await cpu_runtime.close_cpu_runtime()


@pytest.mark.anyio
async def test_run_cpu_io_async_burst_keeps_event_loop_responsive_and_respects_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_workers", 3)
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_concurrency", 3)
    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.init_cpu_runtime()

    heartbeat_ticks = 0
    stop_heartbeat = asyncio.Event()

    async def _heartbeat() -> None:
        nonlocal heartbeat_ticks
        while not stop_heartbeat.is_set():
            heartbeat_ticks += 1
            await asyncio.sleep(0.005)

    def _slow_work(item: int) -> int:
        time.sleep(0.03)
        return item

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        burst = [
            cpu_runtime.run_cpu_io_async(_slow_work, i, operation="test.burst")
            for i in range(30)
        ]
        results = await asyncio.gather(*burst)
    finally:
        stop_heartbeat.set()
        await heartbeat_task

    assert sorted(results) == list(range(30))
    assert heartbeat_ticks > 1

    runtime = cpu_runtime._cpu_runtime
    assert runtime is not None
    assert runtime.peak_in_flight <= cpu_runtime.settings.cpu_runtime_max_concurrency
    assert runtime.peak_queue_depth >= 1

    await cpu_runtime.close_cpu_runtime()
