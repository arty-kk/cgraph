import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import external_io_runtime


@pytest.mark.anyio
async def test_openai_runtime_short_limit_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_io_runtime.settings, "openai_io_short_concurrency", 2)
    monkeypatch.setattr(external_io_runtime.settings, "openai_io_long_concurrency", 1)
    await external_io_runtime.close_external_io_runtime()
    await external_io_runtime.init_external_io_runtime()

    current = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def _work() -> int:
        nonlocal current, max_seen
        async with lock:
            current += 1
            max_seen = max(max_seen, current)
        await asyncio.sleep(0.04)
        async with lock:
            current -= 1
        return 1

    results = await asyncio.gather(
        *[
            external_io_runtime.run_openai_io_async(_work, kind="short")
            for _ in range(8)
        ]
    )

    assert len(results) == 8
    assert max_seen <= 2

    await external_io_runtime.close_external_io_runtime()


@pytest.mark.anyio
async def test_openai_runtime_releases_permit_on_error_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_io_runtime.settings, "openai_io_short_concurrency", 1)
    monkeypatch.setattr(external_io_runtime.settings, "openai_io_long_concurrency", 1)
    await external_io_runtime.close_external_io_runtime()
    await external_io_runtime.init_external_io_runtime()

    async def _fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await external_io_runtime.run_openai_io_async(_fail, kind="short")

    assert await external_io_runtime.run_openai_io_async(
        lambda: asyncio.sleep(0, result="ok"),
        kind="short",
    ) == "ok"

    started = asyncio.Event()

    async def _block() -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(external_io_runtime.run_openai_io_async(_block, kind="short"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await external_io_runtime.run_openai_io_async(
        lambda: asyncio.sleep(0, result="after-cancel"),
        kind="short",
    ) == "after-cancel"

    await external_io_runtime.close_external_io_runtime()


@pytest.mark.anyio
async def test_storage_sdk_runtime_limit_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_io_runtime.settings, "storage_sdk_io_concurrency", 2)
    await external_io_runtime.close_external_io_runtime()
    await external_io_runtime.init_external_io_runtime()

    import threading
    import time

    current = 0
    max_seen = 0
    lock = threading.Lock()

    def _work() -> int:
        nonlocal current, max_seen
        with lock:
            current += 1
            max_seen = max(max_seen, current)
        time.sleep(0.04)
        with lock:
            current -= 1
        return 1

    results = await asyncio.gather(
        *[external_io_runtime.run_storage_sdk_io_async(_work) for _ in range(8)]
    )

    assert len(results) == 8
    assert max_seen <= 2

    await external_io_runtime.close_external_io_runtime()
