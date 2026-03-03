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


@pytest.mark.anyio
async def test_storage_sdk_runtime_uses_dedicated_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_io_runtime.settings, "storage_sdk_io_concurrency", 2)
    await external_io_runtime.close_external_io_runtime()
    await external_io_runtime.init_external_io_runtime()

    runtime = await external_io_runtime._get_external_io_runtime()
    loop = asyncio.get_running_loop()
    original_run_in_executor = loop.run_in_executor
    seen_executors = []

    async def _spy_run_in_executor(executor, func, *args):
        seen_executors.append(executor)
        return await original_run_in_executor(executor, func, *args)

    monkeypatch.setattr(loop, "run_in_executor", _spy_run_in_executor)

    assert await external_io_runtime.run_storage_sdk_io_async(lambda: "ok") == "ok"
    assert seen_executors
    assert seen_executors[0] is runtime.storage_sdk_executor
    assert seen_executors[0] is not None

    await external_io_runtime.close_external_io_runtime()


@pytest.mark.anyio
async def test_storage_sdk_runtime_shutdown_executor_and_reinit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_io_runtime.settings, "storage_sdk_io_concurrency", 1)
    await external_io_runtime.close_external_io_runtime()
    await external_io_runtime.init_external_io_runtime()

    runtime_before_close = await external_io_runtime._get_external_io_runtime()
    shutdown_calls: list[tuple[bool, bool]] = []
    original_shutdown = runtime_before_close.storage_sdk_executor.shutdown

    def _spy_shutdown(wait: bool = True, *, cancel_futures: bool = False) -> None:
        shutdown_calls.append((wait, cancel_futures))
        original_shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(runtime_before_close.storage_sdk_executor, "shutdown", _spy_shutdown)

    await external_io_runtime.close_external_io_runtime()

    assert shutdown_calls == [(True, False)]

    await external_io_runtime.init_external_io_runtime()
    runtime_after_reinit = await external_io_runtime._get_external_io_runtime()
    assert runtime_after_reinit.storage_sdk_executor is not runtime_before_close.storage_sdk_executor

    assert await external_io_runtime.run_storage_sdk_io_async(lambda: 1) == 1

    await external_io_runtime.close_external_io_runtime()
