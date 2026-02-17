import asyncio
import io
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))


def _get_client_and_headers():
    try:
        from app.db import get_session  # noqa: E402
        from app.models import OrgMembership, User  # noqa: E402
        from app.async_db import AsyncSessionLocal  # noqa: E402
        from app.services.auth_service import bootstrap_user_async, create_session_async  # noqa: E402
    except ModuleNotFoundError:
        pytest.skip("Postgres dependencies are not available for mutation response tests")

    try:
        with get_session() as session:
            session.exec(select(1)).first()
    except SQLAlchemyError:
        pytest.skip("Postgres is not available for mutation response tests")

    from app.main import app  # noqa: E402

    client = TestClient(app)
    with get_session() as session:
        user = session.exec(select(User).limit(1)).first()
    if not user:
        async def _bootstrap_async():
            async with AsyncSessionLocal() as session:
                created = await bootstrap_user_async(session, "mutation-tests@example.com", "password123")
                token, _ = await create_session_async(session, created.id)
                return created, token
        user, token = asyncio.run(_bootstrap_async())
    else:
        async def _create_session_async_for_user(user_id: int):
            async with AsyncSessionLocal() as session:
                token, _ = await create_session_async(session, user_id)
                return token
        token = asyncio.run(_create_session_async_for_user(user.id))
    with get_session() as session:
        membership = session.exec(
            select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
        ).first()
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
    return int(response.json().get("id"))


def test_update_file_returns_async_task_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = _get_client_and_headers()
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


def test_rename_file_returns_async_task_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = _get_client_and_headers()
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
