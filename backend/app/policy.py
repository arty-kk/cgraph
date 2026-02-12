"""Async policy layer for org-scoped RBAC checks."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from .auth import extract_token
from .config import settings
from .errors import BadRequestError, ForbiddenError, NotFoundError, UnauthorizedError
from .models import Organization, OrgMembership, Project, User
from .rbac import ORG_ROLES, role_at_least


async def _get_request_session(request: Request):
    session = getattr(request.state, "db_session", None)
    if session is None:
        raise RuntimeError("Async DB session is not available in request state")
    return session


async def _resolve_org_id_unauth_async(request: Request) -> int:
    header = request.headers.get("x-org-id")
    session = await _get_request_session(request)
    if header and isinstance(header, str):
        try:
            org_id = int(header.strip())
        except ValueError:
            raise BadRequestError("X-Org-ID должен быть числом")
        org = await session.get(Organization, org_id)
        if not org:
            raise NotFoundError("Организация не найдена", context={"org_id": org_id})
        return org.id

    org_ids = (await session.execute(select(Organization.id))).scalars().all()
    if len(org_ids) == 1:
        return int(org_ids[0])
    if org_ids:
        raise BadRequestError("Укажите X-Org-ID")

    # Protect against race conditions on concurrent unauthenticated requests.
    dialect = session.bind.dialect.name if session.bind is not None else ""
    if dialect == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 780451})
    org_ids = (await session.execute(select(Organization.id))).scalars().all()
    if len(org_ids) == 1:
        return int(org_ids[0])
    if org_ids:
        raise BadRequestError("Укажите X-Org-ID")
    org = Organization(
        name="Personal",
        slug="personal",
        created_at=datetime.now(timezone.utc),
    )
    session.add(org)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = (
            (await session.execute(select(Organization).where(Organization.slug == "personal")))
            .scalars()
            .first()
        )
        if existing and existing.id is not None:
            return int(existing.id)
        raise
    return int(org.id)


async def require_user_async(request: Request) -> User:
    if not settings.auth_enabled:
        return User(
            id=0,
            email="unauthenticated",
            password_hash="",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
    state_user = getattr(request.state, "user", None)
    if isinstance(state_user, User) and isinstance(state_user.id, int):
        return state_user
    token = extract_token(request)
    if not token:
        raise UnauthorizedError("Требуется токен")
    from .services.auth_service import get_user_from_token_async

    session = await _get_request_session(request)
    return await get_user_from_token_async(session, token)


async def _membership_for_user_async(request: Request, user_id: int, org_id: int) -> OrgMembership | None:
    session = await _get_request_session(request)
    return (
        (
            await session.execute(
                select(OrgMembership).where(
                    OrgMembership.user_id == user_id,
                    OrgMembership.org_id == org_id,
                    OrgMembership.is_active.is_(True),
                )
            )
        )
        .scalars()
        .first()
    )


async def _org_ids_for_user_async(request: Request, user_id: int) -> list[int]:
    session = await _get_request_session(request)
    rows = (
        await session.execute(
            select(OrgMembership.org_id).where(
                OrgMembership.user_id == user_id,
                OrgMembership.is_active.is_(True),
            )
        )
    ).scalars().all()
    return [int(r) for r in rows]


async def require_org_context_async(
    request: Request, min_role: str = "viewer"
) -> tuple[User, int, OrgMembership]:
    if min_role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль доступа")
    if not settings.auth_enabled:
        org_id = await _resolve_org_id_unauth_async(request)
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
    user = await require_user_async(request)
    header = request.headers.get("x-org-id")
    if header and isinstance(header, str):
        try:
            org_id = int(header.strip())
        except ValueError:
            raise BadRequestError("X-Org-ID должен быть числом")
        membership = await _membership_for_user_async(request, user.id, org_id)
        if not membership:
            raise ForbiddenError("Нет доступа к организации")
    else:
        org_ids = await _org_ids_for_user_async(request, user.id)
        if len(org_ids) == 1:
            org_id = org_ids[0]
            membership = await _membership_for_user_async(request, user.id, org_id)
        elif not org_ids:
            raise ForbiddenError("Пользователь не состоит в организациях")
        else:
            raise BadRequestError("Укажите X-Org-ID")
    if not membership or not role_at_least(membership.role, min_role):
        raise ForbiddenError("Недостаточно прав")
    return user, int(org_id), membership


async def require_project_access_async(
    request: Request,
    project_id: int,
    *,
    min_role: str = "viewer",
) -> Project:
    if min_role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль доступа")
    session = await _get_request_session(request)
    if not settings.auth_enabled:
        org_id = await _resolve_org_id_unauth_async(request)
        project = (
            (
                await session.execute(
                    select(Project).where(Project.id == project_id, Project.org_id == org_id)
                )
            )
            .scalars()
            .first()
        )
        if not project:
            raise ForbiddenError("Нет доступа к проекту")
        return project

    user = await require_user_async(request)
    project = await session.get(Project, project_id)
    if not project:
        raise ForbiddenError("Нет доступа к проекту")
    membership = await _membership_for_user_async(request, user.id, project.org_id)
    if not membership:
        raise ForbiddenError("Нет доступа к проекту")
    if not role_at_least(membership.role, min_role):
        raise ForbiddenError("Недостаточно прав")
    return project


async def require_org_role_async(
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

    user = await require_user_async(request)
    membership = await _membership_for_user_async(request, user.id, org_id)
    if not membership:
        raise ForbiddenError("Нет доступа к организации")
    if not role_at_least(membership.role, min_role):
        raise ForbiddenError("Недостаточно прав")
    return user, membership
