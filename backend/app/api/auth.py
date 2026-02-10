# backend/app/api/auth.py
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..auth import extract_token
from ..errors import BadRequestError, UnauthorizedError
from ..services.auth_service import (
    authenticate_user,
    bootstrap_user,
    create_api_key,
    create_session,
    get_user_from_token,
    list_api_keys,
    register_user,
    revoke_api_key,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthCredentials(BaseModel):
    email: str = Field(..., description="User email")
    password: str = Field(..., description="User password")


class ApiKeyRequest(BaseModel):
    name: str = Field(default="default", description="Key name")


def _require_token(request: Request) -> str:
    token = extract_token(request)
    if not token:
        raise UnauthorizedError("Требуется токен")
    return token


@router.post("/bootstrap")
def bootstrap(body: AuthCredentials):
    user = bootstrap_user(body.email, body.password)
    return {"id": user.id, "email": user.email}


@router.post("/register")
def register(body: AuthCredentials):
    user = register_user(body.email, body.password)
    return {"id": user.id, "email": user.email}


@router.post("/login")
def login(body: AuthCredentials):
    user = authenticate_user(body.email, body.password)
    token, expires_at = create_session(user.id)
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.post("/logout")
def logout(request: Request):
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            raise UnauthorizedError("Требуется токен")
    else:
        api_key = request.headers.get("x-api-key")
        if isinstance(api_key, str) and api_key.strip():
            raise BadRequestError("API-ключи не поддерживаются для logout endpoint")
        raise UnauthorizedError("Требуется токен")

    revoke_session(token)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    token = _require_token(request)
    user = get_user_from_token(token)
    return {"id": user.id, "email": user.email}


@router.post("/api-keys")
def create_key(request: Request, body: ApiKeyRequest):
    token = _require_token(request)
    user = get_user_from_token(token)
    raw, key = create_api_key(user.id, body.name)
    return {
        "id": key.id,
        "name": key.name,
        "token": raw,
        "created_at": key.created_at.isoformat(),
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
    }


@router.get("/api-keys")
def list_keys(request: Request):
    token = _require_token(request)
    user = get_user_from_token(token)
    keys = list_api_keys(user.id)
    return [
        {
            "id": k.id,
            "name": k.name,
            "created_at": k.created_at.isoformat(),
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        }
        for k in keys
    ]


@router.delete("/api-keys/{key_id}")
def delete_key(request: Request, key_id: int):
    token = _require_token(request)
    user = get_user_from_token(token)
    revoke_api_key(user.id, key_id)
    return {"ok": True}
