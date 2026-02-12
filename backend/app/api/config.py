# backend/app/api/config.py
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import settings
from ..policy import require_org_context_async

router = APIRouter(prefix="/config", tags=["config"])


class ClientConfig(BaseModel):
    allow_local_root_path: bool


@router.get("")
async def get_config(request: Request) -> ClientConfig:
    await require_org_context_async(request, min_role="viewer")
    return ClientConfig(allow_local_root_path=bool(settings.allow_local_root_path))
