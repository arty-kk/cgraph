import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import async_worker_runtime


@pytest.mark.anyio
async def test_worker_runtime_start_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _startup() -> None:
        calls.append("startup")

    async def _cleanup() -> None:
        calls.append("cleanup")

    async def _consume(*, queue: str, timeout_seconds: int = 1) -> bool:
        _ = timeout_seconds
        calls.append(f"consume:{queue}")
        await asyncio.sleep(0)
        return False

    monkeypatch.setattr(async_worker_runtime, "_startup_worker_resources_async", _startup)
    monkeypatch.setattr(async_worker_runtime, "_cleanup_worker_resources_async", _cleanup)
    monkeypatch.setattr(async_worker_runtime, "consume_worker_queue_once_async", _consume)

    await async_worker_runtime.init_worker_runtime_async()
    await asyncio.sleep(0.05)
    await async_worker_runtime.close_worker_runtime_async()

    assert calls[0] == "startup"
    assert any(call.startswith("consume:") for call in calls)
    assert calls[-1] == "cleanup"
