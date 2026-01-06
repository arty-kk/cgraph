#backend/app/main.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .api.projects import router as projects_router
from .api.nodes import router as nodes_router
from .api.tasks import router as tasks_router

init_db()

app = FastAPI(title="Code Surgeon (local)", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(nodes_router)
app.include_router(tasks_router)

@app.get("/health")
def health():
    return {"ok": True}
