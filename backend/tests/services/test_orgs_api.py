import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main
from app.api import orgs as orgs_api
from app.async_db import AsyncSessionLocal
from app.models import Organization, OrgMembership, User

pytest_plugins = ("tests.services.db_helpers",)


async def _create_user(email: str) -> User:
    user = User(email=email, password_hash="x")
    async with AsyncSessionLocal() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def _missing_org_id() -> int:
    async with AsyncSessionLocal() as session:
        max_org_id = (
            (await session.execute(select(Organization.id).order_by(Organization.id.desc())))
            .scalars()
            .first()
        )
    return int(max_org_id or 0) + 1


async def _membership_exists(org_id: int, user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        membership = (
            (
                await session.execute(
                    select(OrgMembership).where(
                        OrgMembership.org_id == org_id,
                        OrgMembership.user_id == user_id,
                    )
                )
            )
            .scalars()
            .first()
        )
    return membership is not None


async def _count_memberships_for_user(user_id: int) -> int:
    async with AsyncSessionLocal() as session:
        memberships = (
            (await session.execute(select(OrgMembership).where(OrgMembership.user_id == user_id)))
            .scalars()
            .all()
        )
    return len(memberships)


async def _create_org(name: str, slug: str) -> Organization:
    org = Organization(name=name, slug=slug)
    async with AsyncSessionLocal() as session:
        session.add(org)
        await session.commit()
        await session.refresh(org)
    return org


async def _count_orgs() -> int:
    async with AsyncSessionLocal() as session:
        org_ids = (await session.execute(select(Organization.id))).scalars().all()
    return len(org_ids)


async def _delete_all_orgs() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Organization))
        await session.commit()


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


@pytest.mark.anyio
async def test_add_member_returns_not_found_for_missing_org_when_auth_disabled(
    monkeypatch,
    ensure_async_postgres,
) -> None:
    monkeypatch.setattr(orgs_api.settings, "auth_enabled", False)

    org_id = await _missing_org_id()
    user = await _create_user(f"missing-org-member-{org_id}@example.com")

    exists_before = await _membership_exists(org_id, int(user.id))

    with TestClient(main.app) as client:
        response = client.post(
            f"/api/orgs/{org_id}/members",
            json={"email": user.email, "role": "member"},
        )

    exists_after = await _membership_exists(org_id, int(user.id))

    assert exists_before is False
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Организация не найдена",
            "context": {"org_id": org_id},
        }
    }
    assert exists_after is False


@pytest.mark.anyio
async def test_list_orgs_returns_single_org_when_auth_disabled(
    monkeypatch,
    ensure_async_postgres,
) -> None:
    monkeypatch.setattr(orgs_api.settings, "auth_enabled", False)

    await _delete_all_orgs()
    try:
        org = await _create_org(name="Single Org", slug="single-org")
        org_count = await _count_orgs()
        assert org_count == 1

        with TestClient(main.app) as client:
            response = client.get("/api/orgs")

        assert response.status_code == 200
        payload = response.json()

        assert isinstance(payload, list)
        assert len(payload) == 1

        only_org = payload[0]
        assert only_org["id"] == org.id
        assert only_org["name"] == org.name
        assert isinstance(only_org["created_at"], str)
        assert only_org["created_at"] == org.created_at.isoformat()
        # Effective role is surfaced so the UI can gate role-restricted actions;
        # auth-disabled callers act as owner.
        assert only_org["role"] == "owner"
    finally:
        await _delete_all_orgs()
