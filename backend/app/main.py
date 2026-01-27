#backend/app/main.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .api.projects import router as projects_router
from .api.nodes import router as nodes_router
from .api.tasks import router as tasks_router
from .errors import install_exception_handlers
from .logging import log_requests, setup_logging

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

app.include_router(projects_router)
app.include_router(nodes_router)
app.include_router(tasks_router)

@app.get("/health")
def health():
    return {"ok": True}
