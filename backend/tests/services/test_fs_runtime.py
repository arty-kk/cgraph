import asyncio
import sys
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
async def test_run_fs_io_async_executes_and_tracks_queue_peaks(monkeypatch: pytest.MonkeyPatch) -> None:
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
async def test_run_fs_io_async_cancellation_releases_queue_depth(monkeypatch: pytest.MonkeyPatch) -> None:
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

    queued = asyncio.create_task(fs_runtime.run_fs_io_async(lambda: "queued", operation="test.queued"))
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
