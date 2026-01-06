#backend/app/api/nodes.py
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException
from sqlmodel import select

from ..db import get_session
from ..models import Project, FileNode
from ..contracts import get_or_build_contract
from ..utils import resolve_under_root

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

@router.get("/{project_id}/{path:path}/contract")
def contract(project_id: int, path: str):
    with get_session() as s:
        p = s.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")

    root = Path(p.root_path).resolve()
    try:
        abs_path, rel_norm = resolve_under_root(root, path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes project root")
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not abs_path.is_file():
        raise HTTPException(status_code=400, detail="Target must be a file")

    try:
        c = get_or_build_contract(project_id, root, rel_norm)
        return c
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build contract: {e}")

@router.get("/{project_id}/{path:path}/node")
def node(project_id: int, path: str):
    with get_session() as s:
        proj = s.get(Project, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        try:
            _, rel_norm = resolve_under_root(Path(proj.root_path).resolve(), path)
        except ValueError:
            raise HTTPException(status_code=400, detail="Path escapes project root")
        n = s.exec(
            select(FileNode).where(
                FileNode.project_id == project_id,
                FileNode.path == rel_norm,
            )
        ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")
    return {
        "path": n.path, "language": n.language, "loc": n.loc, "complexity": n.complexity,
        "fan_in": n.fan_in, "fan_out": n.fan_out, "scc_id": n.scc_id, "status": n.status
    }
