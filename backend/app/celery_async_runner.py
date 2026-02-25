from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any, TypeVar

from .logging import get_logger

logger = get_logger("stubgraph.celery")

T = TypeVar("T")
_RUNNER_READY_TIMEOUT_SECONDS = 5.0


class _ProcessAsyncRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready.clear()
            thread = threading.Thread(
                target=self._thread_main,
                name="stubgraph-celery-async-runner",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        ready = self._ready.wait(timeout=_RUNNER_READY_TIMEOUT_SECONDS)
        if not ready:
            raise RuntimeError("Timed out while starting celery async runner")
        if self._loop is None:
            raise RuntimeError("Failed to start celery async runner")

    def stop(self) -> None:
        with self._lock:
            loop = self._loop
            thread = self._thread
            if loop is None or thread is None:
                self._loop = None
                self._thread = None
                return
            loop.call_soon_threadsafe(loop.stop)
        thread.join()
        with self._lock:
            self._loop = None
            self._thread = None
            self._ready.clear()

    def run_sync(
        self,
        coro_func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        log_context: str,
    ) -> T:
        loop = self._loop
        if loop is None:
            raise RuntimeError("Celery async runner is not started")
        future: Future[T] = asyncio.run_coroutine_threadsafe(coro_func(*args), loop)
        try:
            return future.result()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Celery async runner execution failed",
                extra={"entrypoint": log_context},
            )
            raise

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()


_runner = _ProcessAsyncRunner()
_runner_started = False
_runner_state_lock = threading.Lock()


def start_process_async_runner() -> None:
    global _runner_started
    with _runner_state_lock:
        if _runner_started:
            return
        _runner.start()
        _runner_started = True


def stop_process_async_runner() -> None:
    global _runner_started
    with _runner_state_lock:
        if not _runner_started:
            return
        _runner.stop()
        _runner_started = False


def run_coroutine_sync(
    coro_func: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    log_context: str,
) -> T:
    return _runner.run_sync(coro_func, *args, log_context=log_context)
