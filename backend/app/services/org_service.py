"""Organization management helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..errors import BadRequestError, ForbiddenError, NotFoundError
from ..models import Organization, OrgMembership, User
from ..rbac import ORG_ROLES, can_manage_member_role


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


async def list_org_memberships_for_user_async(
    session: AsyncSession, user_id: int
) -> list[tuple[Organization, str]]:
    """Return each active org for the user paired with the user's role in it.

    The role is the same source of truth used by ``require_org_role_async`` so
    consumers (e.g. the UI) can gate role-restricted actions consistently with
    server-side enforcement.
    """
    rows = (
        await session.execute(
            select(Organization, OrgMembership.role).where(
                OrgMembership.user_id == user_id,
                OrgMembership.is_active.is_(True),
                OrgMembership.org_id == Organization.id,
            )
        )
    ).all()
    return [(org, str(role)) for org, role in rows]


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
    *,
    actor_role: str,
) -> OrgMembership:
    role = _validate_role(role)
    if not can_manage_member_role(actor_role, role):
        raise ForbiddenError("Недостаточно прав для назначения этой роли")
    now = datetime.now(timezone.utc)
    async with session.begin():
        org = await session.get(Organization, org_id)
        if not org:
            raise NotFoundError("Организация не найдена", context={"org_id": org_id})
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
            if existing.is_active and not can_manage_member_role(actor_role, existing.role):
                raise ForbiddenError("Недостаточно прав для изменения этого участника")
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


async def remove_member_async(
    session: AsyncSession,
    org_id: int,
    user_id: int,
    *,
    actor_role: str,
) -> None:
    async with session.begin():
        org = await session.get(Organization, org_id)
        if not org:
            raise NotFoundError("Организация не найдена", context={"org_id": org_id})
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
        if membership.is_active and not can_manage_member_role(actor_role, membership.role):
            raise ForbiddenError("Недостаточно прав для удаления этого участника")
        if membership.role == "owner" and membership.is_active:
            await _ensure_not_last_active_owner_async(session, org_id, user_id)
        await session.delete(membership)
