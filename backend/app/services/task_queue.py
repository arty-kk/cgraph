#backend/app/services/task_queue.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable
from uuid import uuid4


@dataclass
class TaskState:
    status: str
    result: Any | None = None
    error: str | None = None


class TaskQueue:
    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, TaskState] = {}
        self._lock = Lock()

    def submit(self, fn: Callable[[], Any]) -> str:
        task_id = uuid4().hex
        with self._lock:
            self._tasks[task_id] = TaskState(status="pending")

        def runner() -> None:
            self._set_state(task_id, "running")
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001
                self._set_state(task_id, "failed", error=str(exc))
                return
            self._set_state(task_id, "succeeded", result=result)

        self._executor.submit(runner)
        return task_id

    def get(self, task_id: str) -> TaskState | None:
        with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                return None
            return TaskState(status=state.status, result=state.result, error=state.error)

    def _set_state(self, task_id: str, status: str, result: Any | None = None, error: str | None = None) -> None:
        with self._lock:
            current = self._tasks.get(task_id)
            if not current:
                current = TaskState(status=status)
                self._tasks[task_id] = current
            current.status = status
            current.result = result
            current.error = error


task_queue = TaskQueue()