# backend/app/main.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.auth import router as auth_router
from .api.config import router as config_router
from .api.nodes import router as nodes_router
from .api.orgs import router as orgs_router
from .api.projects import router as projects_router
from .api.tasks import router as tasks_router
from .auth import extract_token
from .config import settings
from .errors import install_exception_handlers
from .infra.rate_limit import allow_request_async, rate_limit_response
from .infra.runtime_lifecycle import build_cleanup_steps, build_startup_steps
from .logging import log_requests, setup_logging
from .request_session import get_request_db_session
from .services.auth_service import get_user_from_token_async

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup_steps: list[tuple[str, Callable[[], Awaitable[Any]]]] = build_startup_steps(role="api")

    try:
        for _, initializer in startup_steps:
            await initializer()
        yield
    finally:
        cleanup_steps: list[tuple[str, Callable[[], Awaitable[Any]]]] = (
            build_cleanup_steps(role="api")
        )
        for name, cleanup in cleanup_steps:
            try:
                await cleanup()
            except Exception:  # noqa: BLE001
                logger.exception("Lifespan cleanup failed", extra={"step": name})


app = FastAPI(title="StubGraph", version="0.1.0", lifespan=lifespan)

setup_logging()
install_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(log_requests)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if not await allow_request_async(request):
        return rate_limit_response()
    return await call_next(request)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    # DB session lifecycle is lazy: request.state.db_session may be absent
    # until get_request_db_session(request) is called by middleware/dependency/handler.
    if path == "/health" or not path.startswith("/api"):
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)
    if path.startswith("/api/auth") or path.startswith("/api/v1/auth"):
        return await call_next(request)
    if not settings.auth_enabled:
        return await call_next(request)

    token = extract_token(request)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "unauthorized", "message": "Требуется токен"}},
        )

    session = await get_request_db_session(request)
    user = await get_user_from_token_async(session, token)
    request.state.user = user
    return await call_next(request)


@app.middleware("http")
async def request_db_session_lifecycle(request: Request, call_next):
    session_ctx = None
    session = None
    exc_type = None
    exc = None
    tb = None
    try:
        response = await call_next(request)
        return response
    except Exception as err:
        exc_type = type(err)
        exc = err
        tb = err.__traceback__
        session = getattr(request.state, "db_session", None)
        if session is not None:
            await session.rollback()
        raise
    finally:
        session_ctx = getattr(request.state, "db_session_ctx", None)
        if session_ctx is not None:
            await session_ctx.__aexit__(exc_type, exc, tb)


app.include_router(projects_router, prefix="/api")
app.include_router(nodes_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(orgs_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(nodes_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(orgs_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"ok": True}
