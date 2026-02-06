# backend/app/api/orgs.py
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlmodel import select

from ..db import get_session
from ..errors import BadRequestError, NotFoundError
from ..models import User
from ..policy import require_org_role, require_user
from ..rbac import ORG_ROLES
from ..services.org_service import (
    add_or_update_member,
    create_org,
    get_org,
    list_members,
    list_orgs_for_user,
    remove_member,
)

router = APIRouter(prefix="/orgs", tags=["orgs"])


class OrgCreate(BaseModel):
    name: str = Field(..., description="Organization name")


class MemberUpsert(BaseModel):
    email: str = Field(..., description="User email")
    role: str = Field(default="member", description="Role: owner|admin|member|viewer")


@router.get("")
def list_orgs(request: Request):
    user = require_user(request)
    orgs = list_orgs_for_user(user.id)
    return [{"id": o.id, "name": o.name, "created_at": o.created_at.isoformat()} for o in orgs]


@router.post("")
def create_org_endpoint(request: Request, body: OrgCreate):
    user = require_user(request)
    org = create_org(body.name, user.id)
    return {"id": org.id, "name": org.name, "created_at": org.created_at.isoformat()}


@router.get("/{org_id}")
def get_org_endpoint(request: Request, org_id: int):
    require_org_role(request, org_id, min_role="viewer")
    org = get_org(org_id)
    return {"id": org.id, "name": org.name, "created_at": org.created_at.isoformat()}


@router.get("/{org_id}/members")
def get_org_members(request: Request, org_id: int):
    require_org_role(request, org_id, min_role="admin")
    return list_members(org_id)


@router.post("/{org_id}/members")
def upsert_member(request: Request, org_id: int, body: MemberUpsert):
    require_org_role(request, org_id, min_role="admin")
    email = body.email.strip().lower()
    if not email:
        raise BadRequestError("Email обязателен")
    if body.role not in ORG_ROLES:
        raise BadRequestError("Некорректная роль")
    with get_session() as session:
        user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        raise NotFoundError("Пользователь не найден")
    membership = add_or_update_member(org_id, user.id, body.role)
    return {"user_id": membership.user_id, "role": membership.role, "org_id": membership.org_id}


@router.delete("/{org_id}/members/{user_id}")
def delete_member(request: Request, org_id: int, user_id: int):
    require_org_role(request, org_id, min_role="admin")
    remove_member(org_id, user_id)
    return {"ok": True}
