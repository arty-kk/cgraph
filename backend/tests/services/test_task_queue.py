import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.db import get_session
from app.errors import ExternalServiceError
from app.models import TaskJob
from app.services.task_queue import (
    get_scan_idempotency_key,
    submit_mutation_indexing_async,
    submit_run_async,
    submit_scan_async,
)


@pytest.fixture
def ensure_postgres():
    try:
        with get_session() as session:
            session.exec(select(1)).first()
    except SQLAlchemyError:
        pytest.skip("Postgres is not available for task queue tests")


@pytest.mark.anyio
async def test_submit_scan_async_reuses_existing_job(ensure_postgres):
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

    returned_id = await submit_scan_async(project_id, org_id)
    assert returned_id == job_id


@pytest.mark.anyio
async def test_submit_mutation_indexing_async_reuses_existing_job(ensure_postgres):
    project_id = 72
    org_id = 10
    job_id = uuid4().hex
    idempotency_key = f"mutation-existing-job-{uuid4().hex}"
    now = datetime.now(timezone.utc)
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

    from unittest.mock import patch

    with patch("app.services.task_queue._idempotency_key", return_value=idempotency_key):
        returned_id, status = await submit_mutation_indexing_async(
            project_id=project_id,
            org_id=org_id,
            rel_paths=["repo/README.md"],
            operation="update_file",
        )

    assert returned_id == job_id
    assert status == "pending"


@pytest.mark.anyio
async def test_submit_run_async_marks_job_failed_when_apply_async_raises(ensure_postgres):
    payload = {"cmd": "echo hello"}

    from unittest.mock import patch

    async def _noop_guard(*args, **kwargs):
        _ = (args, kwargs)

    async def _noop_release(*args, **kwargs):
        _ = (args, kwargs)

    with patch("app.services.task_queue._guard_inflight_async", side_effect=_noop_guard), patch(
        "app.services.task_queue._release_inflight_async", side_effect=_noop_release
    ), patch(
        "app.celery_tasks.run_task_job.apply_async",
        side_effect=RuntimeError("queue unavailable"),
    ):
        with pytest.raises(ExternalServiceError) as exc_ctx:
            await submit_run_async(project_id=101, org_id=202, payload=payload)

    err = exc_ctx.value
    assert err.code == "external_service_error"
    assert err.context["queue"] == "heavy"
    assert isinstance(err.context.get("task_id"), str)

    with get_session() as session:
        job = session.get(TaskJob, err.context["task_id"])
    assert job is not None
    assert job.status == "failed"
    assert job.error == "queue unavailable"
    assert job.completed_at is not None
