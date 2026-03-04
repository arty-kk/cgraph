import asyncio
import sys
import threading
import time
from pathlib import Path
from threading import Event

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import fs_runtime


@pytest.mark.anyio
async def test_fs_runtime_init_and_close_are_idempotent() -> None:
    await fs_runtime.init_fs_runtime()
    await fs_runtime.init_fs_runtime()

    await fs_runtime.close_fs_runtime()
    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_run_fs_io_async_executes_and_tracks_queue_peaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_workers", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_concurrency", 1)
    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

    def _slow(label: str) -> str:
        time.sleep(0.03)
        return label

    first, second = await asyncio.gather(
        fs_runtime.run_fs_io_async(_slow, "a", operation="test.slow"),
        fs_runtime.run_fs_io_async(_slow, "b", operation="test.slow"),
    )

    assert {first, second} == {"a", "b"}
    runtime = fs_runtime._fs_runtime
    assert runtime is not None
    assert runtime.peak_queue_depth >= 1
    assert runtime.peak_in_flight == 1

    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_close_fs_runtime_waits_for_running_task_and_is_safe_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_workers", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_concurrency", 1)
    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

    started = Event()
    release = Event()

    def _blocking() -> str:
        started.set()
        release.wait(timeout=1)
        return "done"

    task = asyncio.create_task(fs_runtime.run_fs_io_async(_blocking))
    await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=1)

    close_task = asyncio.create_task(fs_runtime.close_fs_runtime())
    assert not close_task.done()
    release.set()
    await close_task

    assert await task == "done"
    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_run_fs_io_async_cancellation_releases_queue_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_workers", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_concurrency", 1)
    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

    release = Event()

    def _blocking() -> str:
        release.wait(timeout=1)
        return "done"

    holder = asyncio.create_task(fs_runtime.run_fs_io_async(_blocking, operation="test.holder"))
    await asyncio.sleep(0.05)

    queued = asyncio.create_task(
        fs_runtime.run_fs_io_async(lambda: "queued", operation="test.queued")
    )
    await asyncio.sleep(0.02)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued

    runtime = fs_runtime._fs_runtime
    assert runtime is not None
    assert runtime.queue_depth == 0

    release.set()
    assert await holder == "done"
    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_run_fs_io_async_burst_keeps_event_loop_responsive_and_respects_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_workers", 3)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_concurrency", 3)
    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

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
            fs_runtime.run_fs_io_async(_slow_work, i, operation="test.burst")
            for i in range(30)
        ]
        results = await asyncio.gather(*burst)
    finally:
        stop_heartbeat.set()
        await heartbeat_task

    assert sorted(results) == list(range(30))
    assert heartbeat_ticks > 1

    runtime = fs_runtime._fs_runtime
    assert runtime is not None
    assert runtime.peak_in_flight <= fs_runtime.settings.fs_runtime_max_concurrency
    assert runtime.peak_queue_depth >= 1

    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_fs_runtime_reinit_on_loop_change_and_concurrent_after_reinit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_workers", 2)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_max_concurrency", 2)
    await fs_runtime.close_fs_runtime()

    runtime_main = await fs_runtime._get_fs_runtime()
    executor_main = runtime_main.executor

    thread_data: dict[str, object] = {}

    def _thread_runner() -> None:
        async def _run() -> None:
            runtime_thread = await fs_runtime._get_fs_runtime()
            thread_data["runtime"] = runtime_thread
            thread_data["executor"] = runtime_thread.executor
            result = await asyncio.gather(
                *[fs_runtime.run_fs_io_async(lambda value=idx: value) for idx in range(4)]
            )
            thread_data["result"] = result

        asyncio.run(_run())

    worker = threading.Thread(target=_thread_runner)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()

    runtime_after = await fs_runtime._get_fs_runtime()
    result_after = await asyncio.gather(
        *[fs_runtime.run_fs_io_async(lambda value=idx: value) for idx in range(4)]
    )

    assert thread_data["runtime"] is not runtime_main
    assert thread_data["executor"] is not executor_main
    assert runtime_after is not thread_data["runtime"]
    assert executor_main._shutdown is True
    assert thread_data["result"] == [0, 1, 2, 3]
    assert result_after == [0, 1, 2, 3]

    await fs_runtime.close_fs_runtime()
