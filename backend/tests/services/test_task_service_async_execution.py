import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import task_service


@pytest.mark.anyio
async def test_run_task_async_offloads_sync_execution(monkeypatch):
    request = task_service.TaskRequest(
        target_path="backend/app/main.py",
        prompt="check",
        mode="analyze",
        profile=None,
        depth=1,
        dep_mode="contracts",
        impact_max_nodes=None,
        impact_max_depth=None,
        apply_patch=False,
        allow_out_of_context_patch=False,
        agentic=False,
        provided_fields=set(),
    )

    captured: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(task_service.asyncio, "to_thread", _fake_to_thread)

    result = await task_service.run_task_async(11, 22, request)

    assert result == {"ok": True}
    assert captured["func"] is task_service.run_task
    assert captured["args"] == (11, 22, request)
    assert captured["kwargs"] == {}


def test_scan_with_background_uses_async_submit(monkeypatch):
    async def _fake_get_active(project_id: int, org_id: int):
        return None, None

    async def _fake_submit_scan(project_id: int, org_id: int):
        _ = (project_id, org_id)
        return "scan-123"

    run_calls = {"count": 0}
    original_run = task_service.asyncio.run

    def _fake_run(coro):
        run_calls["count"] += 1
        return original_run(coro)

    monkeypatch.setattr(task_service, "_get_active_scan_task_async", _fake_get_active)
    monkeypatch.setattr(task_service, "submit_scan_async", _fake_submit_scan)
    monkeypatch.setattr(task_service.asyncio, "run", _fake_run)

    result = task_service.scan_with_background(5, 9)

    assert result == {"task_id": "scan-123", "status": "pending"}
    assert run_calls["count"] == 2
