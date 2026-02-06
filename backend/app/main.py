#backend/app/main.py
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.auth import router as auth_router
from .api.nodes import router as nodes_router
from .api.orgs import router as orgs_router
from .api.projects import router as projects_router
from .api.tasks import router as tasks_router
from .auth import extract_token
from .config import settings
from .db import init_db
from .errors import install_exception_handlers
from .infra.rate_limit import allow_request, rate_limit_response
from .logging import log_requests, setup_logging
from .services.auth_service import get_user_from_token

init_db()

app = FastAPI(title="StubGraph", version="0.1.0")

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
    if not allow_request(request):
        return rate_limit_response()
    return await call_next(request)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    if not settings.auth_enabled:
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
        get_user_from_token(token)
    return await call_next(request)

app.include_router(projects_router, prefix="/api")
app.include_router(nodes_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(orgs_router, prefix="/api")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(nodes_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(orgs_router, prefix="/api/v1")

@app.get("/health")
def health():
    return {"ok": True}
