import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services.task_queue import TaskQueue, TaskState  # noqa: E402


class TestTaskQueueRetention(unittest.TestCase):
    def test_purge_removes_expired_completed_tasks(self) -> None:
        queue = TaskQueue(completed_ttl_seconds=10)
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with queue._lock:
            queue._tasks["expired"] = TaskState(
                status="succeeded",
                completed_at=now - timedelta(seconds=20),
            )
            queue._tasks["recent"] = TaskState(
                status="failed",
                completed_at=now - timedelta(seconds=5),
            )
            queue._tasks["pending"] = TaskState(status="pending")
            queue._tasks["running"] = TaskState(status="running")
            queue._purge(now)
            self.assertNotIn("expired", queue._tasks)
            self.assertIn("recent", queue._tasks)
            self.assertIn("pending", queue._tasks)
            self.assertIn("running", queue._tasks)

    def test_purge_enforces_max_completed_tasks(self) -> None:
        queue = TaskQueue(max_completed_tasks=2)
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with queue._lock:
            queue._tasks["oldest"] = TaskState(
                status="succeeded",
                completed_at=now - timedelta(seconds=30),
            )
            queue._tasks["middle"] = TaskState(
                status="failed",
                completed_at=now - timedelta(seconds=20),
            )
            queue._tasks["newest"] = TaskState(
                status="succeeded",
                completed_at=now - timedelta(seconds=10),
            )
            queue._tasks["running"] = TaskState(status="running")
            queue._purge(now)
            self.assertNotIn("oldest", queue._tasks)
            self.assertIn("middle", queue._tasks)
            self.assertIn("newest", queue._tasks)
            self.assertIn("running", queue._tasks)

    def test_get_keeps_recent_completed_tasks(self) -> None:
        queue = TaskQueue(completed_ttl_seconds=60)
        now = datetime.now(timezone.utc)
        with queue._lock:
            queue._tasks["recent"] = TaskState(
                status="succeeded",
                result={"ok": True},
                completed_at=now - timedelta(seconds=30),
            )
        state = queue.get("recent")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.status, "succeeded")
        self.assertEqual(state.result, {"ok": True})


if __name__ == "__main__":
    unittest.main()
