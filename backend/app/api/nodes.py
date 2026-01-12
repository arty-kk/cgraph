#backend/app/api/nodes.py
from __future__ import annotations

from fastapi import APIRouter
from sqlmodel import select

from ..db import get_session
from ..models import Project, FileNode
from ..contracts import get_or_build_contract
from ..config import settings
from ..errors import BadRequestError, NotFoundError
from ..utils import normalize_project_root, resolve_under_root

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

@router.get("/{project_id}/{path:path}/contract")
def contract(project_id: int, path: str):
    with get_session() as s:
        p = s.get(Project, project_id)
    if not p:
        raise NotFoundError("Проект не найден", context={"project_id": project_id})

    root = normalize_project_root(p.root_path, max_length=settings.max_root_path_chars)
    abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    if not abs_path.exists():
        raise NotFoundError("Файл не найден", context={"path": rel_norm})
    if not abs_path.is_file():
        raise BadRequestError("Цель должна быть файлом")

    try:
        c = get_or_build_contract(project_id, root, rel_norm)
        return c
    except FileNotFoundError:
        raise NotFoundError("Файл не найден", context={"path": rel_norm})
    except Exception as e:
        raise BadRequestError("Не удалось собрать контракт", context={"reason": str(e)})

@router.get("/{project_id}/{path:path}/node")
def node(project_id: int, path: str):
    with get_session() as s:
        proj = s.get(Project, project_id)
        if not proj:
            raise NotFoundError("Проект не найден", context={"project_id": project_id})
        _, rel_norm = resolve_under_root(
            normalize_project_root(proj.root_path, max_length=settings.max_root_path_chars),
            path,
            max_length=settings.max_rel_path_chars,
        )
        n = s.exec(
            select(FileNode).where(
                FileNode.project_id == project_id,
                FileNode.path == rel_norm,
            )
        ).first()
    if not n:
        raise NotFoundError("Узел не найден", context={"path": rel_norm})
    return {
        "path": n.path, "language": n.language, "loc": n.loc, "complexity": n.complexity,
        "fan_in": n.fan_in, "fan_out": n.fan_out, "scc_id": n.scc_id, "status": n.status
    }
