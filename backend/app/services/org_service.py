"""Organization management helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..errors import BadRequestError, NotFoundError
from ..models import Organization, OrgMembership, User
from ..rbac import ORG_ROLES


def _normalize_org_name(name: str, fallback: str = "Personal") -> str:
    if isinstance(name, str):
        value = name.strip()
        if value:
            return value[:200]
    return fallback


def _validate_role(role: str) -> str:
    if role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль")
    return role


async def _ensure_not_last_active_owner_async(
    session: AsyncSession,
    org_id: int,
    user_id: int,
) -> None:
    active_owner_user_ids = (
        (
            await session.execute(
                select(OrgMembership.user_id)
                .where(
                    OrgMembership.org_id == org_id,
                    OrgMembership.role == "owner",
                    OrgMembership.is_active.is_(True),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if len(active_owner_user_ids) == 1 and int(active_owner_user_ids[0]) == user_id:
        raise BadRequestError("Нельзя удалить или понизить последнего активного owner")


async def create_org_async(session: AsyncSession, name: str, owner_user_id: int) -> Organization:
    org_name = _normalize_org_name(name)
    now = datetime.now(timezone.utc)
    async with session.begin():
        org = Organization(name=org_name, created_at=now)
        session.add(org)
        await session.flush()
        membership = OrgMembership(
            org_id=org.id,
            user_id=owner_user_id,
            role="owner",
            is_active=True,
            created_at=now,
        )
        session.add(membership)
    return org


async def list_orgs_for_user_async(session: AsyncSession, user_id: int) -> list[Organization]:
    memberships = (
        (
            await session.execute(
                select(OrgMembership.org_id).where(
                    OrgMembership.user_id == user_id,
                    OrgMembership.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    org_ids = [int(row) for row in memberships]
    if not org_ids:
        return []
    return list(
        (await session.execute(select(Organization).where(Organization.id.in_(org_ids))))
        .scalars()
        .all()
    )


async def get_org_async(session: AsyncSession, org_id: int) -> Organization:
    org = await session.get(Organization, org_id)
    if not org:
        raise NotFoundError("Организация не найдена", context={"org_id": org_id})
    return org


async def list_members_async(session: AsyncSession, org_id: int) -> list[dict]:
    rows = (
        await session.execute(
            select(User, OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == User.id,
            )
        )
    ).all()
    return [
        {
            "id": user.id,
            "email": user.email,
            "role": membership.role,
            "is_active": membership.is_active,
            "created_at": membership.created_at.isoformat(),
        }
        for user, membership in rows
    ]


async def add_or_update_member_async(
    session: AsyncSession,
    org_id: int,
    user_id: int,
    role: str,
) -> OrgMembership:
    role = _validate_role(role)
    now = datetime.now(timezone.utc)
    async with session.begin():
        existing = (
            (
                await session.execute(
                    select(OrgMembership)
                    .where(
                        OrgMembership.org_id == org_id,
                        OrgMembership.user_id == user_id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .first()
        )
        if existing:
            if existing.role == "owner" and existing.is_active and role != "owner":
                await _ensure_not_last_active_owner_async(session, org_id, user_id)
            existing.role = role
            existing.is_active = True
            session.add(existing)
            membership = existing
        else:
            membership = OrgMembership(
                org_id=org_id,
                user_id=user_id,
                role=role,
                is_active=True,
                created_at=now,
            )
            session.add(membership)
    await session.refresh(membership)
    return membership


async def remove_member_async(session: AsyncSession, org_id: int, user_id: int) -> None:
    async with session.begin():
        membership = (
            (
                await session.execute(
                    select(OrgMembership)
                    .where(
                        OrgMembership.org_id == org_id,
                        OrgMembership.user_id == user_id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .first()
        )
        if not membership:
            raise NotFoundError("Участник не найден")
        if membership.role == "owner" and membership.is_active:
            await _ensure_not_last_active_owner_async(session, org_id, user_id)
        await session.delete(membership)
