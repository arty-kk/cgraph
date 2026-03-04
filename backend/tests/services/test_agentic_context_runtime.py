import asyncio
import sys
import threading
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm.agentic import context as agentic_context


@pytest.mark.anyio
async def test_seed_fs_semaphore_reinit_on_loop_change_and_keeps_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agentic_context.settings, "llm_agentic_fs_ops_concurrency", 2)
    monkeypatch.setattr(agentic_context.settings, "fs_runtime_max_concurrency", 3)

    agentic_context._SEED_FS_SEMAPHORE = None
    agentic_context._SEED_FS_SEMAPHORE_LOOP = None
    agentic_context._SEED_FS_SEMAPHORE_LOCK = None
    agentic_context._SEED_FS_SEMAPHORE_LOCK_LOOP = None

    current = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def _fake_run_fs_io_async(fn, *args, **kwargs):
        nonlocal current, max_seen
        _ = (fn, args, kwargs)
        async with lock:
            current += 1
            max_seen = max(max_seen, current)
        await asyncio.sleep(0.03)
        async with lock:
            current -= 1
        return "ok"

    monkeypatch.setattr(agentic_context, "run_fs_io_async", _fake_run_fs_io_async)

    sem_main = await agentic_context._seed_fs_semaphore_async()
    await asyncio.gather(
        *[agentic_context._run_seed_fs_io_async(lambda: None) for _ in range(6)]
    )

    thread_data: dict[str, object] = {}

    def _thread_runner() -> None:
        async def _run() -> None:
            sem_thread = await agentic_context._seed_fs_semaphore_async()
            thread_data["sem"] = sem_thread
            thread_data["loop"] = agentic_context._SEED_FS_SEMAPHORE_LOOP

        asyncio.run(_run())

    worker = threading.Thread(target=_thread_runner)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()

    sem_after = await agentic_context._seed_fs_semaphore_async()
    await asyncio.gather(
        *[agentic_context._run_seed_fs_io_async(lambda: None) for _ in range(6)]
    )

    assert sem_main is not thread_data["sem"]
    assert sem_after is not thread_data["sem"]
    assert max_seen <= 2
