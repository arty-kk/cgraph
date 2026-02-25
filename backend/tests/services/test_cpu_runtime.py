import asyncio
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import cpu_runtime


def _sleep_and_echo(delay_s: float, payload: str) -> str:
    time.sleep(delay_s)
    return payload


def _sleep_and_return(delay_s: float, value: int) -> int:
    time.sleep(delay_s)
    return value


def _add_one(value: int) -> int:
    return value + 1


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.mark.anyio
async def test_cpu_runtime_init_close_and_reinit_on_other_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_workers", 1)
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_concurrency", 1)

    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.init_cpu_runtime()
    runtime_first = cpu_runtime._cpu_runtime
    assert runtime_first is not None

    worker_result: dict[str, int] = {}

    def _run_in_thread() -> None:
        worker_result["value"] = asyncio.run(
            cpu_runtime.run_cpu_io_async(_add_one, 40, operation="test.reinit.worker")
        )

    thread = threading.Thread(target=_run_in_thread)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert worker_result["value"] == 41

    await cpu_runtime.run_cpu_io_async(_add_one, 1, operation="test.reinit.main")
    runtime_final = cpu_runtime._cpu_runtime
    assert runtime_final is not None
    assert runtime_final.loop is asyncio.get_running_loop()

    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.close_cpu_runtime()


@pytest.mark.anyio
async def test_run_cpu_io_async_executes_and_tracks_queue_peaks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_workers", 1)
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_concurrency", 1)
    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.init_cpu_runtime()

    first, second = await asyncio.gather(
        cpu_runtime.run_cpu_io_async(_sleep_and_echo, 0.03, "a", operation="test.slow"),
        cpu_runtime.run_cpu_io_async(_sleep_and_echo, 0.03, "b", operation="test.slow"),
    )

    assert {first, second} == {"a", "b"}
    runtime = cpu_runtime._cpu_runtime
    assert runtime is not None
    assert runtime.peak_queue_depth >= 1
    assert runtime.peak_in_flight == 1

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

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        burst = [
            cpu_runtime.run_cpu_io_async(_sleep_and_return, 0.03, i, operation="test.burst")
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


@pytest.mark.anyio
async def test_cpu_runtime_timeout_shutdown_without_dangling_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_workers", 1)
    monkeypatch.setattr(cpu_runtime.settings, "cpu_runtime_max_concurrency", 1)
    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.init_cpu_runtime()

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            cpu_runtime.run_cpu_io_async(
                _sleep_and_return,
                0.5,
                7,
                operation="test.timeout",
            ),
            timeout=0.05,
        )

    runtime = cpu_runtime._cpu_runtime
    assert runtime is not None
    proc_map = getattr(runtime.executor, "_processes", None) or {}
    worker_pids = [proc.pid for proc in proc_map.values() if proc is not None and proc.pid]

    close_task = asyncio.create_task(cpu_runtime.close_cpu_runtime())
    await asyncio.sleep(0.01)
    assert not close_task.done()
    await close_task

    for _ in range(20):
        if not any(_pid_alive(pid) for pid in worker_pids):
            break
        await asyncio.sleep(0.05)
    assert not any(_pid_alive(pid) for pid in worker_pids)


@pytest.mark.anyio
async def test_run_cpu_io_async_rejects_non_pickle_safe_contract() -> None:
    await cpu_runtime.close_cpu_runtime()

    with pytest.raises(TypeError, match="callable must be top-level importable"):
        await cpu_runtime.run_cpu_io_async(lambda: 1, operation="test.bad.callable")

    with pytest.raises(TypeError, match="args must be pickle-serializable"):
        await cpu_runtime.run_cpu_io_async(
            _add_one,
            threading.Lock(),
            operation="test.bad.args",
        )

    await cpu_runtime.close_cpu_runtime()
