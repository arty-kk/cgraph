"""Policy layer for org-scoped RBAC checks.

Usage:
    user, org_id, membership = require_org_context(request, min_role="viewer")
    project = require_project_access(request, project_id, min_role="member")
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request
from sqlmodel import select

from .auth import extract_token
from .config import settings
from .db import get_session
from .errors import BadRequestError, ForbiddenError, NotFoundError, UnauthorizedError
from .models import OrgMembership, Organization, Project, User
from .rbac import ORG_ROLES, role_at_least
from .services.auth_service import get_user_from_token

def require_user(request: Request) -> User:
    if not settings.auth_enabled:
        return User(
            id=0,
            email="unauthenticated",
            password_hash="",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
    token = extract_token(request)
    if not token:
        raise UnauthorizedError("Требуется токен")
    return get_user_from_token(token)


def _membership_for_user(user_id: int, org_id: int) -> OrgMembership | None:
    with get_session() as session:
        return session.exec(
            select(OrgMembership).where(
                OrgMembership.user_id == user_id,
                OrgMembership.org_id == org_id,
                OrgMembership.is_active.is_(True),
            )
        ).first()


def _org_ids_for_user(user_id: int) -> list[int]:
    with get_session() as session:
        rows = session.exec(
            select(OrgMembership.org_id).where(
                OrgMembership.user_id == user_id,
                OrgMembership.is_active.is_(True),
            )
        ).all()
    return [int(r) for r in rows]


def _resolve_org_id_unauth(request: Request) -> int:
    header = request.headers.get("x-org-id")
    with get_session() as session:
        if header and isinstance(header, str):
            try:
                org_id = int(header.strip())
            except ValueError:
                raise BadRequestError("X-Org-ID должен быть числом")
            org = session.get(Organization, org_id)
            if not org:
                raise NotFoundError("Организация не найдена", context={"org_id": org_id})
            return org.id

        org_ids = session.exec(select(Organization.id)).all()
        if len(org_ids) == 1:
            return int(org_ids[0])
        if not org_ids:
            org = Organization(name="Personal", created_at=datetime.now(timezone.utc))
            session.add(org)
            session.commit()
            session.refresh(org)
            return int(org.id)
        raise BadRequestError("Укажите X-Org-ID")


def _resolve_org_id(request: Request, user_id: int) -> int:
    header = request.headers.get("x-org-id")
    if header and isinstance(header, str):
        try:
            org_id = int(header.strip())
        except ValueError:
            raise BadRequestError("X-Org-ID должен быть числом")
        if not _membership_for_user(user_id, org_id):
            raise ForbiddenError("Нет доступа к организации")
        return org_id

    org_ids = _org_ids_for_user(user_id)
    if len(org_ids) == 1:
        return org_ids[0]
    if not org_ids:
        raise ForbiddenError("Пользователь не состоит в организациях")
    raise BadRequestError("Укажите X-Org-ID")


def require_org_context(request: Request, min_role: str = "viewer") -> tuple[User, int, OrgMembership]:
    if min_role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль доступа")
    if not settings.auth_enabled:
        org_id = _resolve_org_id_unauth(request)
        return (
            User(
                id=0,
                email="unauthenticated",
                password_hash="",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            ),
            org_id,
            OrgMembership(
                org_id=org_id,
                user_id=0,
                role="owner",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            ),
        )
    user = require_user(request)
    org_id = _resolve_org_id(request, user.id)
    membership = _membership_for_user(user.id, org_id)
    if not membership:
        raise ForbiddenError("Нет доступа к организации")
    if not role_at_least(membership.role, min_role):
        raise ForbiddenError("Недостаточно прав")
    return user, org_id, membership


def require_org_role(
    request: Request,
    org_id: int,
    *,
    min_role: str = "viewer",
) -> tuple[User, OrgMembership]:
    if min_role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль доступа")
    if not settings.auth_enabled:
        return (
            User(
                id=0,
                email="unauthenticated",
                password_hash="",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            ),
            OrgMembership(
                org_id=org_id,
                user_id=0,
                role="owner",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            ),
        )
    user = require_user(request)
    membership = _membership_for_user(user.id, org_id)
    if not membership:
        raise ForbiddenError("Нет доступа к организации")
    if not role_at_least(membership.role, min_role):
        raise ForbiddenError("Недостаточно прав")
    return user, membership


def require_project_access(
    request: Request,
    project_id: int,
    *,
    min_role: str = "viewer",
) -> Project:
    if min_role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль доступа")
    if not settings.auth_enabled:
        with get_session() as session:
            project = session.get(Project, project_id)
        if not project:
            raise NotFoundError("Проект не найден", context={"project_id": project_id})
        return project
    user = require_user(request)
    with get_session() as session:
        project = session.get(Project, project_id)
    if not project:
        raise ForbiddenError("Нет доступа к проекту")
    membership = _membership_for_user(user.id, project.org_id)
    if not membership:
        raise ForbiddenError("Нет доступа к проекту")
    if not role_at_least(membership.role, min_role):
        raise ForbiddenError("Недостаточно прав")
    return project
