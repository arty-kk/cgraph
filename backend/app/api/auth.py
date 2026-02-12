# backend/app/api/auth.py
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..async_db import AsyncSessionLocal
from ..auth import extract_token
from ..errors import BadRequestError, UnauthorizedError
from ..services.auth_service import (
    authenticate_user_async,
    bootstrap_user_async,
    create_api_key_async,
    create_session_async,
    get_user_from_token_async,
    list_api_keys_async,
    register_user_async,
    revoke_api_key_async,
    revoke_session_async,
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
async def bootstrap(body: AuthCredentials):
    async with AsyncSessionLocal() as session:
        user = await bootstrap_user_async(session, body.email, body.password)
    return {"id": user.id, "email": user.email}


@router.post("/register")
async def register(body: AuthCredentials):
    async with AsyncSessionLocal() as session:
        user = await register_user_async(session, body.email, body.password)
    return {"id": user.id, "email": user.email}


@router.post("/login")
async def login(body: AuthCredentials):
    async with AsyncSessionLocal() as session:
        user = await authenticate_user_async(session, body.email, body.password)
        token, expires_at = await create_session_async(session, user.id)
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.post("/logout")
async def logout(request: Request):
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

    await revoke_session_async(request.state.db_session, token)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    token = _require_token(request)
    user = await get_user_from_token_async(request.state.db_session, token)
    return {"id": user.id, "email": user.email}


@router.post("/api-keys")
async def create_key(request: Request, body: ApiKeyRequest):
    token = _require_token(request)
    user = await get_user_from_token_async(request.state.db_session, token)
    raw, key = await create_api_key_async(request.state.db_session, user.id, body.name)
    return {
        "id": key.id,
        "name": key.name,
        "token": raw,
        "created_at": key.created_at.isoformat(),
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
    }


@router.get("/api-keys")
async def list_keys(request: Request):
    token = _require_token(request)
    user = await get_user_from_token_async(request.state.db_session, token)
    keys = await list_api_keys_async(request.state.db_session, user.id)
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
async def delete_key(request: Request, key_id: int):
    token = _require_token(request)
    user = await get_user_from_token_async(request.state.db_session, token)
    await revoke_api_key_async(request.state.db_session, user.id, key_id)
    return {"ok": True}
