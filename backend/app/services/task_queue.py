#backend/app/services/task_queue.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from ..config import settings


@dataclass
class TaskState:
    status: str
    result: Any | None = None
    error: str | None = None
    completed_at: datetime | None = None


class TaskQueue:
    def __init__(
        self,
        max_workers: int = 4,
        completed_ttl_seconds: int | None = None,
        max_completed_tasks: int | None = None,
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, TaskState] = {}
        self._lock = Lock()
        self._completed_ttl_seconds = completed_ttl_seconds
        self._max_completed_tasks = max_completed_tasks

    def submit(self, fn: Callable[[], Any]) -> str:
        task_id = uuid4().hex
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge(now)
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
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge(now)
            state = self._tasks.get(task_id)
            if not state:
                return None
            return TaskState(
                status=state.status,
                result=state.result,
                error=state.error,
                completed_at=state.completed_at,
            )

    def _set_state(self, task_id: str, status: str, result: Any | None = None, error: str | None = None) -> None:
        completed_at: datetime | None = None
        if status in {"succeeded", "failed"}:
            completed_at = datetime.now(timezone.utc)
        with self._lock:
            current = self._tasks.get(task_id)
            if not current:
                current = TaskState(status=status)
                self._tasks[task_id] = current
            current.status = status
            current.result = result
            current.error = error
            if completed_at and current.completed_at is None:
                current.completed_at = completed_at

    def _purge(self, now: datetime) -> None:
        if self._completed_ttl_seconds is None and self._max_completed_tasks is None:
            return
        if self._completed_ttl_seconds is not None:
            cutoff = now - timedelta(seconds=self._completed_ttl_seconds)
            expired = [
                task_id
                for task_id, state in self._tasks.items()
                if state.status in {"succeeded", "failed"}
                and state.completed_at
                and state.completed_at < cutoff
            ]
            for task_id in expired:
                self._tasks.pop(task_id, None)
        if self._max_completed_tasks is not None:
            completed = [
                (task_id, state.completed_at)
                for task_id, state in self._tasks.items()
                if state.status in {"succeeded", "failed"} and state.completed_at
            ]
            if len(completed) > self._max_completed_tasks:
                completed.sort(key=lambda item: item[1])
                to_remove = completed[: len(completed) - self._max_completed_tasks]
                for task_id, _completed_at in to_remove:
                    self._tasks.pop(task_id, None)


task_queue = TaskQueue(
    completed_ttl_seconds=settings.task_queue_completed_ttl_seconds,
    max_completed_tasks=settings.task_queue_max_completed,
)
