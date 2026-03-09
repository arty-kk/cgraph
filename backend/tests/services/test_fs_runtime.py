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
async def test_run_fs_io_async_tracks_peaks_per_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_interactive_max_workers", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_interactive_max_concurrency", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_bulk_max_workers", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_bulk_max_concurrency", 1)
    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

    def _slow(label: str) -> str:
        time.sleep(0.03)
        return label

    first, second = await asyncio.gather(
        fs_runtime.run_fs_io_async(_slow, "a", operation="test.slow.bulk", lane="bulk"),
        fs_runtime.run_fs_io_async(_slow, "b", operation="test.slow.bulk", lane="bulk"),
    )

    assert {first, second} == {"a", "b"}
    runtime = fs_runtime._fs_runtime
    assert runtime is not None
    assert runtime.bulk.peak_queue_depth >= 1
    assert runtime.bulk.peak_in_flight == 1
    assert runtime.interactive.peak_queue_depth == 0

    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_run_fs_io_async_cancellation_releases_queue_depth_for_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_interactive_max_workers", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_interactive_max_concurrency", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_bulk_max_workers", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_bulk_max_concurrency", 1)
    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

    release = Event()

    def _blocking() -> str:
        release.wait(timeout=1)
        return "done"

    holder = asyncio.create_task(
        fs_runtime.run_fs_io_async(_blocking, operation="test.holder.bulk", lane="bulk")
    )
    await asyncio.sleep(0.05)

    queued = asyncio.create_task(
        fs_runtime.run_fs_io_async(lambda: "queued", operation="test.queued.bulk", lane="bulk")
    )
    await asyncio.sleep(0.02)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued

    runtime = fs_runtime._fs_runtime
    assert runtime is not None
    assert runtime.bulk.queue_depth == 0

    release.set()
    assert await holder == "done"
    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_bulk_load_does_not_block_interactive_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_interactive_max_workers", 2)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_interactive_max_concurrency", 2)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_bulk_max_workers", 1)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_bulk_max_concurrency", 1)
    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

    def _bulk_work() -> str:
        time.sleep(0.08)
        return "bulk"

    def _interactive_read() -> str:
        time.sleep(0.005)
        return "interactive"

    bulk_tasks = [
        asyncio.create_task(fs_runtime.run_fs_io_async(_bulk_work, operation="test.bulk", lane="bulk"))
        for _ in range(8)
    ]

    await asyncio.sleep(0.01)
    start = time.perf_counter()
    interactive_results = await asyncio.gather(
        *[
            fs_runtime.run_fs_io_async(
                _interactive_read,
                operation="test.interactive",
                lane="interactive",
            )
            for _ in range(6)
        ]
    )
    interactive_elapsed = time.perf_counter() - start
    await asyncio.gather(*bulk_tasks)

    assert all(item == "interactive" for item in interactive_results)
    assert interactive_elapsed < 0.25

    runtime = fs_runtime._fs_runtime
    assert runtime is not None
    assert runtime.bulk.peak_queue_depth >= 1
    assert runtime.interactive.peak_in_flight >= 1

    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_fs_runtime_reinit_on_loop_change_rebuilds_both_lane_executors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_interactive_max_workers", 2)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_interactive_max_concurrency", 2)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_bulk_max_workers", 2)
    monkeypatch.setattr(fs_runtime.settings, "fs_runtime_bulk_max_concurrency", 2)
    await fs_runtime.close_fs_runtime()

    runtime_main = await fs_runtime._get_fs_runtime()
    interactive_executor_main = runtime_main.interactive.executor
    bulk_executor_main = runtime_main.bulk.executor

    thread_data: dict[str, object] = {}

    def _thread_runner() -> None:
        async def _run() -> None:
            runtime_thread = await fs_runtime._get_fs_runtime()
            thread_data["runtime"] = runtime_thread
            thread_data["interactive_executor"] = runtime_thread.interactive.executor
            thread_data["bulk_executor"] = runtime_thread.bulk.executor
            result = await asyncio.gather(
                fs_runtime.run_fs_io_async(lambda: 1, lane="interactive"),
                fs_runtime.run_fs_io_async(lambda: 2, lane="bulk"),
            )
            thread_data["result"] = result

        asyncio.run(_run())

    worker = threading.Thread(target=_thread_runner)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()

    runtime_after = await fs_runtime._get_fs_runtime()
    assert thread_data["runtime"] is not runtime_main
    assert runtime_after is not thread_data["runtime"]
    assert interactive_executor_main._shutdown is True
    assert bulk_executor_main._shutdown is True
    assert thread_data["result"] == [1, 2]

    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_run_fs_io_async_rejects_unknown_lane() -> None:
    await fs_runtime.close_fs_runtime()
    await fs_runtime.init_fs_runtime()

    with pytest.raises(ValueError, match="Unsupported fs runtime lane"):
        await fs_runtime.run_fs_io_async(lambda: None, lane="unknown")  # type: ignore[arg-type]

    await fs_runtime.close_fs_runtime()
