# backend/app/main.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.auth import router as auth_router
from .api.config import router as config_router
from .api.nodes import router as nodes_router
from .api.orgs import router as orgs_router
from .api.projects import router as projects_router
from .api.tasks import router as tasks_router
from .async_db import AsyncSessionLocal
from .auth import extract_token
from .config import settings
from .errors import install_exception_handlers
from .infra.rate_limit import allow_request_async, rate_limit_response
from .infra.runtime_lifecycle import build_cleanup_steps, build_startup_steps
from .logging import log_requests, setup_logging
from .services.auth_service import get_user_from_token_async

logger = logging.getLogger(__name__)


async def attach_request_db_session(request: Request) -> AsyncIterator[None]:
    async with AsyncSessionLocal() as session:
        request.state.db_session = session
        yield


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup_steps: list[tuple[str, Callable[[], Awaitable[Any]]]] = build_startup_steps(role="api")

    try:
        for _, initializer in startup_steps:
            await initializer()
        yield
    finally:
        cleanup_steps: list[tuple[str, Callable[[], Awaitable[Any]]]] = build_cleanup_steps(role="api")
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
    if not settings.auth_enabled:
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if path == "/health":
        return await call_next(request)
    if path.startswith("/api"):
        if path.startswith("/api/auth") or path.startswith("/api/v1/auth"):
            return await call_next(request)
        token = extract_token(request)
        if not token:
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "unauthorized", "message": "Требуется токен"}},
            )
        async with AsyncSessionLocal() as session:
            user = await get_user_from_token_async(session, token)
        request.state.user = user
    return await call_next(request)


api_dependencies = [Depends(attach_request_db_session)]

app.include_router(projects_router, prefix="/api", dependencies=api_dependencies)
app.include_router(nodes_router, prefix="/api", dependencies=api_dependencies)
app.include_router(tasks_router, prefix="/api", dependencies=api_dependencies)
app.include_router(auth_router, prefix="/api", dependencies=api_dependencies)
app.include_router(orgs_router, prefix="/api", dependencies=api_dependencies)
app.include_router(config_router, prefix="/api", dependencies=api_dependencies)
app.include_router(projects_router, prefix="/api/v1", dependencies=api_dependencies)
app.include_router(nodes_router, prefix="/api/v1", dependencies=api_dependencies)
app.include_router(tasks_router, prefix="/api/v1", dependencies=api_dependencies)
app.include_router(auth_router, prefix="/api/v1", dependencies=api_dependencies)
app.include_router(orgs_router, prefix="/api/v1", dependencies=api_dependencies)
app.include_router(config_router, prefix="/api/v1", dependencies=api_dependencies)


@app.get("/health")
def health():
    return {"ok": True}
