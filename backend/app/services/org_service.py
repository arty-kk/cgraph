"""Organization management helpers.

Use create_org/create_org_for_user to bootstrap an org and assign membership.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from ..db import get_session
from ..errors import BadRequestError, NotFoundError
from ..models import Organization, OrgMembership, User
from ..rbac import ORG_ROLES


def _normalize_org_name(name: str, fallback: str = "Personal") -> str:
    if isinstance(name, str):
        value = name.strip()
        if value:
            return value[:200]
    return fallback


def _default_org_name(email: str) -> str:
    if isinstance(email, str) and "@" in email:
        prefix = email.split("@", 1)[0].strip()
        if prefix:
            return _normalize_org_name(prefix)
    return "Personal"


def _validate_role(role: str) -> str:
    if role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль")
    return role


def _ensure_not_last_active_owner(session: Session, org_id: int, user_id: int) -> None:
    active_owner_user_ids = session.exec(
        select(OrgMembership.user_id)
        .where(
            OrgMembership.org_id == org_id,
            OrgMembership.role == "owner",
            OrgMembership.is_active.is_(True),
        )
        .with_for_update()
    ).all()
    if len(active_owner_user_ids) == 1 and int(active_owner_user_ids[0]) == user_id:
        raise BadRequestError("Нельзя удалить или понизить последнего активного owner")


def create_org(name: str, owner_user_id: int) -> Organization:
    org_name = _normalize_org_name(name)
    now = datetime.now(timezone.utc)
    with get_session() as session:
        with session.begin():
            org = Organization(name=org_name, created_at=now)
            session.add(org)
            session.flush()
            membership = OrgMembership(
                org_id=org.id,
                user_id=owner_user_id,
                role="owner",
                is_active=True,
                created_at=now,
            )
            session.add(membership)
    return org


def create_org_for_user(user: User) -> Organization:
    name = _default_org_name(user.email or "")
    return create_org(name, user.id)


def list_orgs_for_user(user_id: int) -> list[Organization]:
    with get_session() as session:
        memberships = session.exec(
            select(OrgMembership.org_id).where(
                OrgMembership.user_id == user_id,
                OrgMembership.is_active.is_(True),
            )
        ).all()
        org_ids = [int(row) for row in memberships]
        if not org_ids:
            return []
        return session.exec(select(Organization).where(Organization.id.in_(org_ids))).all()


def get_org(org_id: int) -> Organization:
    with get_session() as session:
        org = session.get(Organization, org_id)
    if not org:
        raise NotFoundError("Организация не найдена", context={"org_id": org_id})
    return org


def list_members(org_id: int) -> list[dict]:
    with get_session() as session:
        rows = session.exec(
            select(User, OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == User.id,
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


def add_or_update_member(org_id: int, user_id: int, role: str) -> OrgMembership:
    role = _validate_role(role)
    now = datetime.now(timezone.utc)
    with get_session() as session:
        with session.begin():
            existing = session.exec(
                select(OrgMembership)
                .where(
                    OrgMembership.org_id == org_id,
                    OrgMembership.user_id == user_id,
                )
                .with_for_update()
            ).first()
            if existing:
                if existing.role == "owner" and existing.is_active and role != "owner":
                    _ensure_not_last_active_owner(session, org_id, user_id)
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
        session.refresh(membership)
        return membership


def remove_member(org_id: int, user_id: int) -> None:
    with get_session() as session:
        with session.begin():
            membership = session.exec(
                select(OrgMembership)
                .where(
                    OrgMembership.org_id == org_id,
                    OrgMembership.user_id == user_id,
                )
                .with_for_update()
            ).first()
            if not membership:
                raise NotFoundError("Участник не найден")
            if membership.role == "owner" and membership.is_active:
                _ensure_not_last_active_owner(session, org_id, user_id)
            session.delete(membership)
