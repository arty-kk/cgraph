from __future__ import annotations

from fastapi import Request

from .async_db import AsyncSessionLocal


async def get_request_db_session(request: Request):
    """Return request-scoped AsyncSession, opening it lazily on first demand.

    Contract for ``request.state.db_session``:
    - guaranteed after calling this helper;
    - may be absent on requests that never touched the database;
    - handlers/dependencies must call this helper instead of direct attribute access
      when they need a database session.
    """

    session = getattr(request.state, "db_session", None)
    if session is not None:
        return session

    session_ctx = AsyncSessionLocal()
    session = await session_ctx.__aenter__()
    request.state.db_session_ctx = session_ctx
    request.state.db_session = session
    return session

