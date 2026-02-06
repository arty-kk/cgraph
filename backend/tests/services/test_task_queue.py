import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.db import get_session  # noqa: E402
from app.models import TaskJob  # noqa: E402
from app.services.task_queue import get_scan_idempotency_key, task_queue  # noqa: E402


class TestTaskQueueStatus(unittest.TestCase):
    def setUp(self) -> None:
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            self.skipTest("Postgres is not available for task queue tests")

    def test_get_returns_job_state(self) -> None:
        job_id = uuid4().hex
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = TaskJob(
                id=job_id,
                org_id=1,
                status="succeeded",
                queue="light",
                result_json='{"ok": true}',
                error=None,
                created_at=now,
                updated_at=now,
                completed_at=now,
            )
            session.add(job)
            session.commit()

        state = task_queue.get(job_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.status, "succeeded")
        self.assertEqual(state.result, {"ok": True})

    def test_submit_scan_reuses_existing_job(self) -> None:
        project_id = 42
        org_id = 7
        job_id = uuid4().hex
        now = datetime.now(timezone.utc)
        idempotency_key = get_scan_idempotency_key(org_id, project_id)
        with get_session() as session:
            job = TaskJob(
                id=job_id,
                org_id=org_id,
                status="pending",
                queue="medium",
                idempotency_key=idempotency_key,
                result_json=None,
                error=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            session.add(job)
            session.commit()

        returned_id = task_queue.submit_scan(project_id, org_id)
        self.assertEqual(returned_id, job_id)
        with get_session() as session:
            count = session.exec(
                select(TaskJob).where(
                    TaskJob.org_id == org_id,
                    TaskJob.idempotency_key == idempotency_key,
                )
            ).all()
        self.assertEqual(len(count), 1)


if __name__ == "__main__":
    unittest.main()
