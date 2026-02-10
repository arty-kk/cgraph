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
        from app.services.auth_service import bootstrap_user, create_session  # noqa: E402
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
        user = bootstrap_user("mutation-tests@example.com", "password123")
    token, _ = create_session(user.id)
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


def test_update_file_scan_aborted(monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = _get_client_and_headers()
    project_id = _create_project(client, headers)

    from app.services import file_mutation_service  # noqa: E402

    monkeypatch.setattr(file_mutation_service, "scan_files", lambda *args, **kwargs: {"aborted": True})
    monkeypatch.setattr(
        file_mutation_service,
        "scan_with_background",
        lambda *args, **kwargs: {"task_id": "scan-1", "status": "pending"},
    )

    response = client.put(
        f"/api/nodes/{project_id}/repo/README.md/file",
        json={"content": "updated"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["saved"] is True
    assert payload["reindexed"] is False
    assert payload["index_status"] == "rescan_scheduled"
    assert "scan_aborted" in payload.get("warnings", [])
    assert payload.get("rescan_scheduled") is True


def test_update_file_scan_failure_rollback_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = _get_client_and_headers()
    project_id = _create_project(client, headers)

    from app.services import file_mutation_service  # noqa: E402
    from app.api import nodes as nodes_api  # noqa: E402

    def _raise(*_args, **_kwargs):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(file_mutation_service, "scan_files", _raise)
    monkeypatch.setattr(
        file_mutation_service,
        "scan_with_background",
        lambda *args, **kwargs: {"task_id": "scan-2", "status": "pending"},
    )
    monkeypatch.setattr(nodes_api, "sha256_file", lambda *_args, **_kwargs: "mismatch")

    response = client.put(
        f"/api/nodes/{project_id}/repo/README.md/file",
        json={"content": "updated again"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["saved"] is True
    assert payload["rollback"] == "skipped"
    assert payload["conflict"] is True
    assert payload["conflict_reason"] == "concurrent_change"
    assert payload["index_status"] == "rescan_scheduled"
    assert "scan_failed" in payload.get("warnings", [])
    assert "rollback_skipped" in payload.get("warnings", [])


def test_update_file_scan_failure_rollback_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    client, headers = _get_client_and_headers()
    project_id = _create_project(client, headers)

    from app.services import file_mutation_service  # noqa: E402

    def _raise(*_args, **_kwargs):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(file_mutation_service, "scan_files", _raise)
    monkeypatch.setattr(
        file_mutation_service,
        "scan_with_background",
        lambda *args, **kwargs: {"task_id": "scan-3", "status": "pending"},
    )

    response = client.put(
        f"/api/nodes/{project_id}/repo/README.md/file",
        json={"content": "updated third"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["saved"] is False
    assert payload["rollback"] == "ok"
    assert payload["index_status"] == "failed"
    assert "scan_failed" in payload.get("warnings", [])
    assert "rollback_ok" in payload.get("warnings", [])
