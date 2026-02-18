import sys
import time
from pathlib import Path

import pytest
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal
from app.errors import BadRequestError
from app.models import OrgMembership, User
from app.services import org_service

from tests.services.db_helpers import ensure_async_postgres


async def _create_user(label: str) -> int:
    suffix = int(time.time() * 1000000)
    user = User(email=f"orgsvc_{label}_{suffix}@example.com", password_hash="x")
    async with AsyncSessionLocal() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return int(user.id)


async def _membership(org_id: int, user_id: int):
    async with AsyncSessionLocal() as session:
        return (
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


@pytest.mark.anyio
async def test_cannot_remove_last_owner(ensure_async_postgres) -> None:
    owner_id = await _create_user("remove_last_owner")
    async with AsyncSessionLocal() as session:
        org = await org_service.create_org_async(session, "remove-last-owner", owner_id)

    async with AsyncSessionLocal() as session:
        with pytest.raises(BadRequestError) as exc:
            await org_service.remove_member_async(session, int(org.id), owner_id)
    assert exc.value.code == "bad_request"

    membership = await _membership(int(org.id), owner_id)
    assert membership is not None
    assert membership.role == "owner"
    assert membership.is_active is True


@pytest.mark.anyio
async def test_cannot_downgrade_last_owner(ensure_async_postgres) -> None:
    owner_id = await _create_user("downgrade_last_owner")
    async with AsyncSessionLocal() as session:
        org = await org_service.create_org_async(session, "downgrade-last-owner", owner_id)

    async with AsyncSessionLocal() as session:
        with pytest.raises(BadRequestError) as exc:
            await org_service.add_or_update_member_async(session, int(org.id), owner_id, "member")
    assert exc.value.code == "bad_request"

    membership = await _membership(int(org.id), owner_id)
    assert membership is not None
    assert membership.role == "owner"
    assert membership.is_active is True


@pytest.mark.anyio
async def test_can_remove_or_downgrade_owner_when_second_active_owner_exists(
    ensure_async_postgres,
) -> None:
    owner_one_id = await _create_user("owner_one")
    owner_two_id = await _create_user("owner_two")

    async with AsyncSessionLocal() as session:
        org = await org_service.create_org_async(session, "with-two-owners", owner_one_id)
    org_id = int(org.id)

    async with AsyncSessionLocal() as session:
        await org_service.add_or_update_member_async(session, org_id, owner_two_id, "owner")

    async with AsyncSessionLocal() as session:
        await org_service.remove_member_async(session, org_id, owner_one_id)
    owner_one_membership = await _membership(org_id, owner_one_id)
    assert owner_one_membership is None

    async with AsyncSessionLocal() as session:
        await org_service.add_or_update_member_async(session, org_id, owner_one_id, "owner")
    async with AsyncSessionLocal() as session:
        updated = await org_service.add_or_update_member_async(
            session,
            org_id,
            owner_two_id,
            "member",
        )
    assert updated.role == "member"
    assert updated.is_active is True

    owner_two_membership = await _membership(org_id, owner_two_id)
    assert owner_two_membership is not None
    assert owner_two_membership.role == "member"
    assert owner_two_membership.is_active is True

    owner_one_membership = await _membership(org_id, owner_one_id)
    assert owner_one_membership is not None
    assert owner_one_membership.role == "owner"
    assert owner_one_membership.is_active is True
