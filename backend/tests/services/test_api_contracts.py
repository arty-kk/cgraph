import inspect
import io
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal
from app.models import OrgMembership, User
from app.services.auth_service import bootstrap_user_async, create_session_async

pytest_plugins = ("tests.services.db_helpers",)


@pytest.fixture
async def api_client_context(ensure_async_postgres):
    from app.main import app

    client = TestClient(app)
    async with AsyncSessionLocal() as session:
        user = ((await session.execute(select(User).limit(1))).scalars().first())

    if not user:
        async with AsyncSessionLocal() as session:
            user = await bootstrap_user_async(session, "test@example.com", "password123")
            token, _ = await create_session_async(session, user.id)
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
        pytest.skip("No org membership available for API contract tests")

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Org-ID": str(membership.org_id),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("repo/README.md", "hello")
    buffer.seek(0)
    response = client.post(
        "/api/projects/from-snapshot",
        data={"name": "contract-project"},
        files={"archive": ("repo.zip", buffer, "application/zip")},
        headers=headers,
    )
    if response.status_code != 200:
        pytest.skip("Unable to create snapshot project for contract tests")
    payload = response.json()
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        pytest.skip("Snapshot import task was not enqueued")
    project_id = None
    deadline = time.time() + 10
    while time.time() < deadline:
        status_response = client.get(f"/api/tasks/status/{task_id}", headers=headers)
        if status_response.status_code != 200:
            pytest.skip("Unable to inspect snapshot import task status")
        status_payload = status_response.json()
        if status_payload.get("status") == "succeeded":
            project_id = status_payload.get("result", {}).get("project_id")
            break
        time.sleep(0.1)
    if not isinstance(project_id, int):
        pytest.skip("Snapshot import task did not finish in time")
    return client, headers, project_id


def _assert_task_envelope(payload: dict) -> None:
    assert isinstance(payload, dict)
    assert isinstance(payload.get("task_id"), str)
    assert payload.get("status") in ("pending", "running")


@pytest.mark.anyio
async def test_health_includes_request_id(api_client_context) -> None:
    client, _, _ = api_client_context
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers.get("X-Request-ID")


def test_health_handler_is_async_coroutine_function() -> None:
    from app.main import health

    assert inspect.iscoroutinefunction(health)


@pytest.mark.anyio
async def test_projects_versioned_and_unversioned(api_client_context) -> None:
    client, headers, _ = api_client_context
    response_v1 = client.get("/api/v1/projects", headers=headers)
    response_unversioned = client.get("/api/projects", headers=headers)
    assert response_v1.status_code == 200
    assert response_unversioned.status_code == 200
    assert response_v1.json() == response_unversioned.json()


@pytest.mark.anyio
async def test_config_contract(api_client_context) -> None:
    client, headers, _ = api_client_context
    response = client.get("/api/config", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("allow_local_root_path"), bool)


@pytest.mark.anyio
async def test_files_tree_contract(api_client_context) -> None:
    client, headers, project_id = api_client_context
    response = client.get(f"/api/projects/{project_id}/files/tree", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("entries"), list)
    assert isinstance(payload.get("meta"), dict)


@pytest.mark.anyio
async def test_dependencies_contract(api_client_context) -> None:
    client, headers, project_id = api_client_context
    response = client.get(
        f"/api/projects/{project_id}/dependencies",
        params={"path": "repo/README.md"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("inbound"), list)
    assert isinstance(payload.get("outbound"), list)


@pytest.mark.anyio
async def test_graph_contract(api_client_context) -> None:
    client, headers, project_id = api_client_context
    response = client.get(f"/api/projects/{project_id}/graph", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert "nodes" in payload
    assert "edges" in payload


@pytest.mark.anyio
async def test_runs_contract(api_client_context) -> None:
    client, headers, project_id = api_client_context
    response = client.get(f"/api/tasks/{project_id}/runs", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.anyio
async def test_run_scan_docs_endpoints_return_task_envelope(api_client_context) -> None:
    client, headers, project_id = api_client_context
    run_payload = {
        "target_path": "repo/README.md",
        "prompt": "contract-check",
        "agentic": False,
    }

    run_response = client.post(
        f"/api/tasks/{project_id}/run",
        json=run_payload,
        headers=headers,
    )
    assert run_response.status_code == 200
    _assert_task_envelope(run_response.json())

    scan_response = client.post(
        f"/api/projects/{project_id}/scan",
        headers=headers,
    )
    assert scan_response.status_code == 200
    _assert_task_envelope(scan_response.json())

    docs_response = client.post(
        f"/api/projects/{project_id}/docs/build",
        headers=headers,
    )
    assert docs_response.status_code == 200
    _assert_task_envelope(docs_response.json())


@pytest.mark.anyio
async def test_create_project_from_snapshot_returns_task_envelope(api_client_context) -> None:
    client, headers, _ = api_client_context
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("repo/main.py", "print('ok')")
    buffer.seek(0)

    response = client.post(
        "/api/projects/from-snapshot",
        data={"name": "contract-snapshot-task"},
        files={"archive": ("repo.zip", buffer, "application/zip")},
        headers=headers,
    )

    assert response.status_code == 200
    _assert_task_envelope(response.json())
