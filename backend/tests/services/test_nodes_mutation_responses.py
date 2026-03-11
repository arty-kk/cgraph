import io
import sys
import zipfile
import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from tests.services.db_helpers import ensure_async_postgres


async def _get_client_and_headers_async():
    try:
        from app.models import OrgMembership, User  # noqa: E402
        from app.async_db import AsyncSessionLocal  # noqa: E402
        from app.services.auth_service import bootstrap_user_async, create_session_async  # noqa: E402
    except ModuleNotFoundError:
        pytest.skip("Postgres dependencies are not available for mutation response tests")

    from app.main import app  # noqa: E402

    client = TestClient(app)
    async with AsyncSessionLocal() as session:
        user = ((await session.execute(select(User).limit(1))).scalars().first())
    if not user:
        async with AsyncSessionLocal() as session:
            created = await bootstrap_user_async(session, "mutation-tests@example.com", "password123")
            token, _ = await create_session_async(session, created.id)
            user = created
    else:
        async with AsyncSessionLocal() as session:
            token, _ = await create_session_async(session, user.id)

    async with AsyncSessionLocal() as session:
        membership = (
            (
                await session.execute(
                    select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
                )
            )
            .scalars()
            .first()
        )
    if not membership:
        pytest.skip("No org membership available for mutation response tests")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Org-ID": str(membership.org_id),
    }
    return client, headers


def _create_project(client: TestClient, headers: dict) -> int:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("repo/README.md", "hello")
    buffer.seek(0)
    response = client.post(
        "/api/projects/from-snapshot",
        data={"name": "mutation-project"},
        files={"archive": ("repo.zip", buffer, "application/zip")},
        headers=headers,
    )
    if response.status_code != 200:
        pytest.skip("Unable to create snapshot project for mutation response tests")
    task_id = response.json().get("task_id")
    if not isinstance(task_id, str) or not task_id:
        pytest.skip("Snapshot import task was not enqueued")

    deadline = time.time() + 10
    while time.time() < deadline:
        status_response = client.get(f"/api/tasks/status/{task_id}", headers=headers)
        if status_response.status_code != 200:
            pytest.skip("Unable to inspect snapshot import task status")
        payload = status_response.json()
        if payload.get("status") == "succeeded":
            project_id = payload.get("result", {}).get("project_id")
            if isinstance(project_id, int):
                return project_id
            break
        time.sleep(0.1)

    pytest.skip("Snapshot import task did not finish in time")


@pytest.mark.anyio
async def test_update_file_returns_async_task_contract(ensure_async_postgres, monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = await _get_client_and_headers_async()
    project_id = _create_project(client, headers)

    from app.api import nodes as nodes_api  # noqa: E402

    async def _submit_mutation_indexing_async(**kwargs):
        _ = kwargs
        return "mutation-1", "pending"

    monkeypatch.setattr(
        nodes_api,
        "submit_mutation_indexing_async",
        _submit_mutation_indexing_async,
    )

    response = client.put(
        f"/api/nodes/{project_id}/repo/README.md/file",
        json={"content": "updated"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["saved"] is True
    assert payload["task_id"] == "mutation-1"
    assert payload["task_status"] == "pending"
    assert payload["index_status"] == "rescan_scheduled"
    assert payload.get("rescan_task", {}).get("task_id") == "mutation-1"


@pytest.mark.anyio
async def test_rename_file_returns_async_task_contract(ensure_async_postgres, monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = await _get_client_and_headers_async()
    project_id = _create_project(client, headers)

    from app.api import nodes as nodes_api  # noqa: E402

    async def _submit_mutation_indexing_async(**kwargs):
        _ = kwargs
        return "mutation-2", "running"

    monkeypatch.setattr(
        nodes_api,
        "submit_mutation_indexing_async",
        _submit_mutation_indexing_async,
    )

    response = client.post(
        f"/api/nodes/{project_id}/repo/README.md/rename",
        json={"new_path": "repo/RENAMED.md", "create_dirs": True},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "repo/RENAMED.md"
    assert payload["saved"] is True
    assert payload["task_id"] == "mutation-2"
    assert payload["task_status"] == "running"


@pytest.mark.anyio
async def test_node_miss_enqueues_indexing_without_sync_scan(ensure_async_postgres, monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = await _get_client_and_headers_async()
    project_id = _create_project(client, headers)

    from app.api import nodes as nodes_api  # noqa: E402

    submit_calls: list[dict] = []

    async def _submit_mutation_indexing_async(**kwargs):
        submit_calls.append(kwargs)
        return "read-miss-task", "pending"

    async def _forbidden_scan(*args, **kwargs):
        _ = (args, kwargs)
        raise AssertionError("_scan_files_async must not be called in read-path")

    async def _forbidden_metrics(*args, **kwargs):
        _ = (args, kwargs)
        raise AssertionError("_update_graph_metrics_incremental_async must not be called in read-path")

    monkeypatch.setattr(nodes_api, "submit_mutation_indexing_async", _submit_mutation_indexing_async)
    monkeypatch.setattr(nodes_api, "_scan_files_async", _forbidden_scan)
    monkeypatch.setattr(nodes_api, "_update_graph_metrics_incremental_async", _forbidden_metrics)

    response = client.get(f"/api/nodes/{project_id}/repo/README.md/node", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["indexing_started"] is True
    assert payload["node_available"] is False
    assert payload["task_id"] == "read-miss-task"
    assert payload["task_status"] == "pending"
    assert "временно недоступен" in payload["message"]
    assert len(submit_calls) == 1
    assert submit_calls[0]["operation"] == "read_node_miss"
    assert submit_calls[0]["rel_paths"] == ["repo/README.md"]


@pytest.mark.anyio
async def test_node_miss_burst_requests_keep_latency(ensure_async_postgres, monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = await _get_client_and_headers_async()
    project_id = _create_project(client, headers)

    from app.api import nodes as nodes_api  # noqa: E402

    async def _slow_submit_mutation_indexing_async(**kwargs):
        _ = kwargs
        await asyncio.sleep(0.05)
        return "read-miss-task", "pending"

    monkeypatch.setattr(nodes_api, "submit_mutation_indexing_async", _slow_submit_mutation_indexing_async)

    ticks = 0
    stop = asyncio.Event()

    async def _ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    async def _request_once() -> dict:
        response = await asyncio.to_thread(
            client.get,
            f"/api/nodes/{project_id}/repo/README.md/node",
            headers=headers,
        )
        assert response.status_code == 200
        return response.json()

    ticker_task = asyncio.create_task(_ticker())
    started = time.monotonic()
    try:
        payloads = await asyncio.wait_for(asyncio.gather(*[_request_once() for _ in range(20)]), timeout=5)
    finally:
        stop.set()
        await ticker_task

    elapsed = time.monotonic() - started
    assert ticks > 10
    assert elapsed < 2
    assert all(p["indexing_started"] is True for p in payloads)
    assert all(p["node_available"] is False for p in payloads)
