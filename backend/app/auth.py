#backend/app/auth.py
from __future__ import annotations

from fastapi import Request


def extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            return token
    api_key = request.headers.get("x-api-key")
    if isinstance(api_key, str) and api_key.strip():
        return api_key.strip()
    return None
