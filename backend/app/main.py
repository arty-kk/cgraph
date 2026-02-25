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
from .async_db import AsyncSessionLocal, close_async_db, init_async_db
from .auth import extract_token
from .config import settings
from .errors import install_exception_handlers
from .infra.cpu_runtime import close_cpu_runtime, init_cpu_runtime
from .infra.external_io_runtime import close_external_io_runtime, init_external_io_runtime
from .infra.fs_runtime import close_fs_runtime, init_fs_runtime
from .infra.rate_limit import allow_request_async, rate_limit_response
from .infra.redis_client import close_redis_pool_async, init_redis_pool_async
from .llm.client import close_async_openai_client, init_async_openai_client
from .logging import log_requests, setup_logging
from .s3_runtime import close_s3_runtime, init_s3_runtime
from .scan import close_scan_runtime
from .services.auth_service import get_user_from_token_async

logger = logging.getLogger(__name__)




def _should_attach_db_session(path: str) -> bool:
    if path == "/health":
        return False
    return path.startswith("/api") or path.startswith("/api/v1")


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup_steps: list[tuple[str, Callable[[], Awaitable[Any]]]] = [
        ("init_redis_pool_async", init_redis_pool_async),
        ("init_async_db", init_async_db),
        ("init_fs_runtime", init_fs_runtime),
        ("init_cpu_runtime", init_cpu_runtime),
        ("init_external_io_runtime", init_external_io_runtime),
    ]

    if settings.openai_api_key:
        startup_steps.append(("init_async_openai_client", init_async_openai_client))

    use_s3 = (settings.storage_backend or "local").strip().lower() == "s3"
    if use_s3:
        startup_steps.append(("init_s3_runtime", init_s3_runtime))

    try:
        for _, initializer in startup_steps:
            await initializer()
        yield
    finally:
        cleanup_steps: list[tuple[str, Callable[[], Awaitable[Any]]]] = [
            ("close_s3_runtime", close_s3_runtime),
            ("close_redis_pool_async", close_redis_pool_async),
            ("close_async_openai_client", close_async_openai_client),
            ("close_fs_runtime", close_fs_runtime),
            ("close_cpu_runtime", close_cpu_runtime),
            ("close_external_io_runtime", close_external_io_runtime),
            ("close_scan_runtime", close_scan_runtime),
            ("close_async_db", close_async_db),
        ]
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
        user = await get_user_from_token_async(request.state.db_session, token)
        request.state.user = user
    return await call_next(request)


# NOTE: function-based middlewares execute in reverse declaration order.
# Keep DB session middleware declared after all others so request.state.db_session
# is available in every middleware/endpoint and remains exactly one per request.
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    if not _should_attach_db_session(request.url.path):
        return await call_next(request)

    async with AsyncSessionLocal() as session:
        request.state.db_session = session
        return await call_next(request)


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
def health():
    return {"ok": True}
