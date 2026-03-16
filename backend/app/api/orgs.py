# backend/app/api/orgs.py
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlmodel import select

from ..config import settings
from ..errors import BadRequestError, ForbiddenError, NotFoundError
from ..models import User
from ..policy import require_org_context_async, require_org_role_async, require_user_async
from ..request_session import get_request_db_session
from ..rbac import ORG_ROLES
from ..services.org_service import (
    add_or_update_member_async,
    create_org_async,
    get_org_async,
    list_members_async,
    list_orgs_for_user_async,
    remove_member_async,
)

router = APIRouter(prefix="/orgs", tags=["orgs"])


class OrgCreate(BaseModel):
    name: str = Field(..., description="Organization name")


class MemberUpsert(BaseModel):
    email: str = Field(..., description="User email")
    role: str = Field(default="member", description="Role: owner|admin|member|viewer")


@router.get("")
async def list_orgs(request: Request):
    session = await get_request_db_session(request)
    if not settings.auth_enabled:
        _, org_id, _ = await require_org_context_async(request)
        org = await get_org_async(session, org_id)
        return [{"id": org.id, "name": org.name, "created_at": org.created_at.isoformat()}]

    user = await require_user_async(request)
    orgs = await list_orgs_for_user_async(session, user.id)
    return [{"id": o.id, "name": o.name, "created_at": o.created_at.isoformat()} for o in orgs]


@router.post("")
async def create_org_endpoint(request: Request, body: OrgCreate):
    session = await get_request_db_session(request)
    if not settings.auth_enabled:
        raise ForbiddenError("Создание организации недоступно при отключенной аутентификации")
    user = await require_user_async(request)
    org = await create_org_async(session, body.name, user.id)
    return {"id": org.id, "name": org.name, "created_at": org.created_at.isoformat()}


@router.get("/{org_id}")
async def get_org_endpoint(request: Request, org_id: int):
    session = await get_request_db_session(request)
    await require_org_role_async(request, org_id, min_role="viewer")
    org = await get_org_async(session, org_id)
    return {"id": org.id, "name": org.name, "created_at": org.created_at.isoformat()}


@router.get("/{org_id}/members")
async def get_org_members(request: Request, org_id: int):
    session = await get_request_db_session(request)
    await require_org_role_async(request, org_id, min_role="admin")
    return await list_members_async(session, org_id)


@router.post("/{org_id}/members")
async def upsert_member(request: Request, org_id: int, body: MemberUpsert):
    session = await get_request_db_session(request)
    await require_org_role_async(request, org_id, min_role="admin")
    email = body.email.strip().lower()
    if not email:
        raise BadRequestError("Email обязателен")
    if body.role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль")
    user = (await session.execute(select(User).where(User.email == email))).scalars().first()
    if not user:
        raise NotFoundError("Пользователь не найден")
    membership = await add_or_update_member_async(session, org_id, user.id, body.role)
    return {"user_id": membership.user_id, "role": membership.role, "org_id": membership.org_id}


@router.delete("/{org_id}/members/{user_id}")
async def delete_member(request: Request, org_id: int, user_id: int):
    session = await get_request_db_session(request)
    await require_org_role_async(request, org_id, min_role="admin")
    await remove_member_async(session, org_id, user_id)
    return {"ok": True}
