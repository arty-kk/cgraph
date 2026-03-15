import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main
from app.api import orgs as orgs_api
from app.async_db import AsyncSessionLocal
from app.models import OrgMembership

pytest_plugins = ("tests.services.db_helpers",)


async def _count_memberships_for_user(user_id: int) -> int:
    async with AsyncSessionLocal() as session:
        memberships = (
            (await session.execute(select(OrgMembership).where(OrgMembership.user_id == user_id)))
            .scalars()
            .all()
        )
    return len(memberships)


@pytest.mark.anyio
async def test_create_org_rejected_when_auth_disabled_and_does_not_create_zero_user_membership(
    monkeypatch,
    ensure_async_postgres,
) -> None:
    monkeypatch.setattr(orgs_api.settings, "auth_enabled", False)

    async def _forbidden_create_org_async(*_args, **_kwargs):
        raise AssertionError("create_org_async must not be called when auth is disabled")

    monkeypatch.setattr(orgs_api, "create_org_async", _forbidden_create_org_async)

    before_count = await _count_memberships_for_user(0)

    with TestClient(main.app) as client:
        response = client.post("/api/orgs", json={"name": "no-auth-org"})

    after_count = await _count_memberships_for_user(0)

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "forbidden",
            "message": "Создание организации недоступно при отключенной аутентификации",
        }
    }
    assert after_count == before_count
