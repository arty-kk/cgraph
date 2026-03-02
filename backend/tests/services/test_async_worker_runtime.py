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

    async def _consume_once_safe(*, queues: list[str], timeout_seconds: int = 1) -> bool:
        _ = timeout_seconds
        calls.append(f"consume:{','.join(queues)}")
        await asyncio.sleep(0)
        return False

    monkeypatch.setattr(async_worker_runtime.settings, "worker_runtime_concurrency", 1)
    monkeypatch.setattr(async_worker_runtime, "_startup_worker_resources_async", _startup)
    monkeypatch.setattr(async_worker_runtime, "_cleanup_worker_resources_async", _cleanup)
    monkeypatch.setattr(async_worker_runtime, "_consume_once_safe_async", _consume_once_safe)

    await async_worker_runtime.init_worker_runtime_async()
    await asyncio.sleep(0.05)
    await async_worker_runtime.close_worker_runtime_async()

    assert calls[0] == "startup"
    assert any(call.startswith("consume:") for call in calls)
    assert calls[-1] == "cleanup"


@pytest.mark.anyio
async def test_worker_runtime_processes_payloads_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    max_active = 0

    async def _startup() -> None:
        return None

    async def _cleanup() -> None:
        return None

    async def _consume_once_safe(*, queues: list[str], timeout_seconds: int = 1) -> bool:
        nonlocal active, max_active
        _ = queues, timeout_seconds
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return False

    monkeypatch.setattr(async_worker_runtime.settings, "worker_runtime_concurrency", 3)
    monkeypatch.setattr(async_worker_runtime, "_startup_worker_resources_async", _startup)
    monkeypatch.setattr(async_worker_runtime, "_cleanup_worker_resources_async", _cleanup)
    monkeypatch.setattr(async_worker_runtime, "_consume_once_safe_async", _consume_once_safe)

    await async_worker_runtime.init_worker_runtime_async()
    await asyncio.sleep(0.12)
    await async_worker_runtime.close_worker_runtime_async()

    assert max_active >= 2


@pytest.mark.anyio
async def test_consume_once_safe_exception_does_not_break_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def brpop(self, queues: list[str], timeout: int = 1):
            _ = queues, timeout
            self.calls += 1
            if self.calls == 1:
                return ("light", "payload")
            return None

    seen: list[str] = []

    async def _consume_payload(payload_raw: str) -> None:
        seen.append(payload_raw)
        raise RuntimeError("boom")

    fake_client = _FakeClient()
    monkeypatch.setattr(async_worker_runtime, "init_redis_pool_async", lambda: asyncio.sleep(0))
    monkeypatch.setattr(
        async_worker_runtime,
        "get_async_redis_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        async_worker_runtime,
        "consume_queued_task_payload_async",
        _consume_payload,
    )

    consumed = await async_worker_runtime._consume_once_safe_async(queues=["light", "medium"])
    consumed_next = await async_worker_runtime._consume_once_safe_async(queues=["light", "medium"])

    assert consumed is False
    assert consumed_next is False
    assert seen == ["payload"]


@pytest.mark.anyio
async def test_worker_runtime_close_cancels_all_consumer_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = asyncio.Event()

    async def _startup() -> None:
        return None

    async def _cleanup() -> None:
        return None

    async def _consume_once_safe(*, queues: list[str], timeout_seconds: int = 1) -> bool:
        _ = queues, timeout_seconds
        await blocked.wait()
        return False

    monkeypatch.setattr(async_worker_runtime.settings, "worker_runtime_concurrency", 2)
    monkeypatch.setattr(async_worker_runtime, "_startup_worker_resources_async", _startup)
    monkeypatch.setattr(async_worker_runtime, "_cleanup_worker_resources_async", _cleanup)
    monkeypatch.setattr(async_worker_runtime, "_consume_once_safe_async", _consume_once_safe)

    await async_worker_runtime.init_worker_runtime_async()
    await asyncio.sleep(0.05)
    await async_worker_runtime.close_worker_runtime_async()

    assert async_worker_runtime._worker_runtime_stop is None
    assert async_worker_runtime._worker_runtime_scheduler_task is None
    assert not async_worker_runtime._worker_runtime_tasks


@pytest.mark.anyio
async def test_worker_runtime_starts_and_stops_scheduler_task(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _startup() -> None:
        return None

    async def _cleanup() -> None:
        return None

    async def _consume_once_safe(*, queues: list[str], timeout_seconds: int = 1) -> bool:
        _ = (queues, timeout_seconds)
        await asyncio.sleep(0.01)
        return False

    scheduler_started = asyncio.Event()

    async def _scheduler_loop(*, stop_event: asyncio.Event) -> None:
        scheduler_started.set()
        await stop_event.wait()

    monkeypatch.setattr(async_worker_runtime.settings, "worker_runtime_concurrency", 1)
    monkeypatch.setattr(async_worker_runtime.settings, "llm_routing_calibration_enabled", True)
    monkeypatch.setattr(async_worker_runtime, "_startup_worker_resources_async", _startup)
    monkeypatch.setattr(async_worker_runtime, "_cleanup_worker_resources_async", _cleanup)
    monkeypatch.setattr(async_worker_runtime, "_consume_once_safe_async", _consume_once_safe)
    monkeypatch.setattr(async_worker_runtime, "_routing_calibration_scheduler_loop_async", _scheduler_loop)

    await async_worker_runtime.init_worker_runtime_async()
    await asyncio.wait_for(scheduler_started.wait(), timeout=1.0)
    assert async_worker_runtime._worker_runtime_scheduler_task is not None

    await async_worker_runtime.close_worker_runtime_async()

    assert async_worker_runtime._worker_runtime_scheduler_task is None


@pytest.mark.anyio
async def test_routing_calibration_scheduler_ticks_on_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    called = 0

    async def _calibrate() -> dict[str, object]:
        nonlocal called
        called += 1
        await asyncio.sleep(0)
        return {"updated": True}

    async def _timeout_wait_for(awaitable, timeout):
        _ = timeout
        awaitable.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(async_worker_runtime, "calibrate_routing_policy_thresholds_async", _calibrate)
    monkeypatch.setattr(async_worker_runtime.asyncio, "wait_for", _timeout_wait_for)

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        async_worker_runtime._routing_calibration_scheduler_loop_async(stop_event=stop_event)
    )
    await asyncio.sleep(0)
    stop_event.set()
    await task

    assert called >= 1
