#backend/app/api/projects.py
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from ..db import get_session
from ..models import Project
from ..scan import scan_project
from ..graph import compute_graph_metrics, graph_payload

router = APIRouter(prefix="/api/projects", tags=["projects"])

class CreateProject(BaseModel):
    name: str = Field(..., description="UI name for the project")
    root_path: str = Field(..., description="Absolute path on local machine")

@router.post("")
def create_project(body: CreateProject):
    root = Path(body.root_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail="root_path must exist and be a directory")

    with get_session() as s:
        p = Project(name=body.name, root_path=str(root))
        s.add(p)
        s.commit()
        s.refresh(p)
    return {"id": p.id, "name": p.name, "root_path": p.root_path}

@router.get("")
def list_projects():
    with get_session() as s:
        ps = s.exec(select(Project)).all()
    return [{"id": p.id, "name": p.name, "root_path": p.root_path} for p in ps]

@router.post("/{project_id}/scan")
def scan(project_id: int):
    with get_session() as s:
        p = s.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")

    root = Path(p.root_path).resolve()
    stats = scan_project(project_id, root)
    compute_graph_metrics(project_id)
    return {"ok": True, "stats": stats}

@router.get("/{project_id}/graph")
def get_graph(project_id: int, limit_nodes: int | None = None):
    with get_session() as s:
        p = s.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return graph_payload(project_id, limit_nodes=limit_nodes)
