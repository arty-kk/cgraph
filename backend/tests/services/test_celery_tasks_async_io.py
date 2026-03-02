import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import celery_tasks


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_fs_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(celery_tasks, "run_fs_io_async", _fake_fs_runtime)

    result = await celery_tasks._normalize_project_root_async("/repo")

    assert result == Path("/repo")
    assert calls["func"] is celery_tasks.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {"operation": "celery.normalize_root"}


@pytest.mark.anyio
async def test_consume_queued_task_payload_dispatches_by_task_name(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, object] = {}

    async def _fake_scan(job_id: str, project_id: int, org_id: int) -> None:
        received["scan"] = (job_id, project_id, org_id)

    monkeypatch.setattr(celery_tasks, "_scan_task_async", _fake_scan)
    monkeypatch.setattr(celery_tasks, "_TASK_DISPATCH", {"stubgraph.scan": _fake_scan})

    body = json.dumps([["job-1", 11, 22], {}, None], ensure_ascii=False).encode("utf-8")
    payload = {
        "body": base64.b64encode(body).decode("ascii"),
        "headers": {"task": "stubgraph.scan"},
        "properties": {"body_encoding": "base64"},
    }

    await celery_tasks.consume_queued_task_payload_async(json.dumps(payload, ensure_ascii=False))

    assert received["scan"] == ("job-1", 11, 22)


@pytest.mark.anyio
async def test_scan_task_async_marks_failed_when_business_coroutine_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses: list[str] = []

    async def _fake_set_job_status_async(_job_id: str, status: str, **_kwargs) -> None:
        statuses.append(status)

    async def _boom(_project_id: int, _org_id: int) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(celery_tasks, "_set_job_status_async", _fake_set_job_status_async)
    monkeypatch.setattr(celery_tasks, "_scan_and_update_graph_async", _boom)

    await celery_tasks._scan_task_async("job", 1, 1)

    assert statuses == ["running", "failed"]
