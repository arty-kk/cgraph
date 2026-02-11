import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from redis import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.errors import BadRequestError, ExternalServiceError  # noqa: E402
from app.infra.redis_client import get_redis_client  # noqa: E402
from app.models import TaskJob  # noqa: E402
from app.services.task_queue import (  # noqa: E402
    _guard_inflight,
    get_scan_idempotency_key,
    task_queue,
)


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


    def test_submit_docs_reuses_existing_job(self) -> None:
        project_id = 52
        org_id = 8
        job_id = uuid4().hex
        idempotency_key = f"docs-existing-job-{uuid4().hex}"
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = TaskJob(
                id=job_id,
                org_id=org_id,
                status="running",
                queue="light",
                idempotency_key=idempotency_key,
                result_json=None,
                error=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            session.add(job)
            session.commit()

        with patch(
            "app.services.task_queue._idempotency_key", return_value=idempotency_key
        ), patch("app.celery_tasks.docs_task.apply_async") as apply_mock:
            returned_id = task_queue.submit_docs(project_id, org_id)

        self.assertEqual(returned_id, job_id)
        apply_mock.assert_not_called()

    def test_submit_run_reuses_existing_job(self) -> None:
        project_id = 62
        org_id = 9
        payload = {"target_path": "repo/README.md", "prompt": "idempotency"}
        job_id = uuid4().hex
        idempotency_key = f"run-existing-job-{uuid4().hex}"
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = TaskJob(
                id=job_id,
                org_id=org_id,
                status="pending",
                queue="heavy",
                idempotency_key=idempotency_key,
                result_json=None,
                error=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            session.add(job)
            session.commit()

        with patch(
            "app.services.task_queue._idempotency_key",
            return_value=idempotency_key,
        ), patch("app.services.task_queue._guard_inflight") as guard_mock, patch(
            "app.celery_tasks.run_task_job.apply_async"
        ) as apply_mock:
            returned_id = task_queue.submit_run(
                project_id=project_id,
                org_id=org_id,
                payload=payload,
            )

        self.assertEqual(returned_id, job_id)
        guard_mock.assert_not_called()
        apply_mock.assert_not_called()

    def test_inflight_guard_blocks_when_redis_state_expired(self) -> None:
        try:
            client = get_redis_client()
            client.ping()
        except Exception:
            self.skipTest("Redis is not available for inflight guard test")
        previous_limit = settings.task_queue_inflight_heavy_limit
        settings.task_queue_inflight_heavy_limit = 1
        inflight_key = "stubgraph:queue:heavy:inflight"
        job_id = uuid4().hex
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = TaskJob(
                id=job_id,
                org_id=1,
                status="running",
                queue="heavy",
                result_json=None,
                error=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            session.add(job)
            session.commit()
        client.delete(inflight_key)
        try:
            with self.assertRaises(BadRequestError):
                _guard_inflight("heavy", uuid4().hex)
        finally:
            settings.task_queue_inflight_heavy_limit = previous_limit
            client.delete(inflight_key)
            with get_session() as session:
                existing = session.get(TaskJob, job_id)
                if existing:
                    session.delete(existing)
                    session.commit()

    def test_submit_run_marks_job_failed_when_apply_async_raises(self) -> None:
        job_id = uuid4().hex
        payload = {"cmd": "echo hello"}
        with patch("app.services.task_queue._guard_inflight"), patch(
            "app.services.task_queue._release_inflight"
        ) as release_mock, patch(
            "app.services.task_queue.uuid4", return_value=SimpleNamespace(hex=job_id)
        ), patch(
            "app.celery_tasks.run_task_job.apply_async",
            side_effect=RuntimeError("queue unavailable"),
        ):
            with self.assertRaises(ExternalServiceError) as exc_ctx:
                task_queue.submit_run(project_id=101, org_id=202, payload=payload)

        err = exc_ctx.exception
        self.assertEqual(err.code, "external_service_error")
        self.assertEqual(err.context, {"task_id": job_id, "queue": "heavy"})
        release_mock.assert_called_once_with("heavy", job_id)

        with get_session() as session:
            job = session.get(TaskJob, job_id)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, "queue unavailable")
        self.assertIsNotNone(job.completed_at)

    def test_submit_scan_marks_job_failed_when_apply_async_raises(self) -> None:
        with patch(
            "app.celery_tasks.scan_task.apply_async",
            side_effect=RuntimeError("scan queue unavailable"),
        ):
            with self.assertRaises(ExternalServiceError) as exc_ctx:
                task_queue.submit_scan(project_id=301, org_id=401)

        err = exc_ctx.exception
        self.assertEqual(err.code, "external_service_error")
        self.assertEqual(err.message, "Не удалось отправить задачу в очередь")
        self.assertEqual(err.context["queue"], "medium")
        self.assertIn("task_id", err.context)

        with get_session() as session:
            job = session.get(TaskJob, err.context["task_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, "scan queue unavailable")
        self.assertIsNotNone(job.completed_at)

    def test_submit_docs_marks_job_failed_when_apply_async_raises(self) -> None:
        with patch(
            "app.celery_tasks.docs_task.apply_async",
            side_effect=RuntimeError("docs queue unavailable"),
        ):
            with self.assertRaises(ExternalServiceError) as exc_ctx:
                task_queue.submit_docs(project_id=302, org_id=402)

        err = exc_ctx.exception
        self.assertEqual(err.code, "external_service_error")
        self.assertEqual(err.message, "Не удалось отправить задачу в очередь")
        self.assertEqual(err.context["queue"], "light")
        self.assertIn("task_id", err.context)

        with get_session() as session:
            job = session.get(TaskJob, err.context["task_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, "docs queue unavailable")
        self.assertIsNotNone(job.completed_at)


class TestTaskQueueInflightGuard(unittest.TestCase):
    def test_inflight_guard_raises_external_service_error_when_redis_unavailable(self) -> None:
        previous_limit = settings.task_queue_inflight_heavy_limit
        settings.task_queue_inflight_heavy_limit = 1
        try:
            with patch(
                "app.services.task_queue.get_redis_client",
                side_effect=RedisError("redis unavailable"),
            ):
                with self.assertRaises(ExternalServiceError) as exc_ctx:
                    _guard_inflight("heavy", uuid4().hex)
        finally:
            settings.task_queue_inflight_heavy_limit = previous_limit

        err = exc_ctx.exception
        self.assertEqual(err.code, "external_service_error")
        self.assertIn("Не удалось проверить лимит heavy-задач", err.message)
        self.assertEqual(err.context, {"queue": "heavy", "limit": 1})


if __name__ == "__main__":
    unittest.main()
