#backend/app/api/nodes.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlmodel import select

from ..db import get_session
from ..graph import update_graph_metrics_incremental
from ..models import Project, FileNode
from ..scan import scan_files
from ..contracts import get_or_build_contract
from ..config import settings
from ..errors import BadRequestError, NotFoundError
from ..utils import normalize_project_root, resolve_under_root, project_lock


class FileUpdate(BaseModel):
    content: str = Field(..., description="New file content")


def _clamp_int(v: int | None, default: int, lo: int, hi: int) -> int:
    try:
        if v is None:
            return default
        n = int(v)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _read_text_limited(path: str, max_chars: int | None) -> tuple[str, bool]:
    if not max_chars or max_chars <= 0:
        return Path(path).read_text(encoding="utf-8", errors="replace"), False

    with Path(path).open("r", encoding="utf-8", errors="replace") as f:
        chunk = f.read(max_chars + 1)
    truncated = len(chunk) > max_chars
    if truncated:
        chunk = chunk[:max_chars]
    return chunk, truncated

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


@router.get("/{project_id}/{path:path}/file")
def get_file(project_id: int, path: str, max_chars: int | None = None):
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

    limit = None
    if max_chars is not None:
        limit = _clamp_int(max_chars, 200_000, 200, 200_000)

    content, truncated = _read_text_limited(str(abs_path), limit)
    return {
        "path": rel_norm,
        "content": content,
        "truncated": bool(truncated),
        "max_chars": limit,
    }


@router.put("/{project_id}/{path:path}/file")
def update_file(project_id: int, path: str, body: FileUpdate):
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

    content = body.content
    if not isinstance(content, str):
        raise BadRequestError("Некорректное содержимое файла")

    with project_lock(project_id):
        abs_path.write_text(content, encoding="utf-8")
        reindexed = scan_files(project_id, root, [rel_norm])
        update_graph_metrics_incremental(
            project_id,
            [rel_norm],
            removed_edge_neighbors=reindexed.get("removed_edge_neighbors") if isinstance(reindexed, dict) else None,
        )

    return {"path": rel_norm, "saved": True, "reindexed": reindexed}
