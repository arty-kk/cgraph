# backend/app/api/nodes.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlmodel import select

from ..config import settings
from ..contracts import get_or_build_contract_async
from ..errors import BadRequestError, LockedError, NotFoundError
from ..graph import update_graph_metrics_incremental
from ..infra.cache import cache_invalidate_prefix
from ..logging import get_logger
from ..models import FileNode
from ..policy import require_project_access_async
from ..scan import scan_files
from ..services.file_mutation_service import (
    build_mutation_queued_response,
    removed_neighbors,
    scan_aborted,
)
from ..services.task_queue import task_queue
from ..utils import (
    ProjectLockTimeout,
    normalize_project_root,
    project_lock_async,
    resolve_under_root,
)


class FileUpdate(BaseModel):
    content: str = Field(..., description="New file content")


class FileCreate(BaseModel):
    content: str | None = Field(None, description="New file content")


class FileRename(BaseModel):
    new_path: str = Field(..., description="New file path under project root")
    create_dirs: bool = Field(True, description="Create parent directories if missing")


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


router = APIRouter(prefix="/nodes", tags=["nodes"])
logger = get_logger("stubgraph.api")


def _invalidate_pack_cache(project_id: int) -> None:
    cache_invalidate_prefix([f"project:{project_id}", "pack"])


@router.get("/{project_id}/{path:path}/contract")
async def contract(request: Request, project_id: int, path: str):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    if not abs_path.exists():
        raise NotFoundError("Файл не найден", context={"path": rel_norm})
    if not abs_path.is_file():
        raise BadRequestError("Цель должна быть файлом")

    try:
        c = await get_or_build_contract_async(request.state.db_session, project_id, root, rel_norm)
        return c
    except FileNotFoundError:
        raise NotFoundError("Файл не найден", context={"path": rel_norm})
    except Exception as e:
        raise BadRequestError("Не удалось собрать контракт", context={"reason": str(e)})


@router.get("/{project_id}/{path:path}/node")
async def node(request: Request, project_id: int, path: str):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    abs_path, rel_norm = resolve_under_root(
        root,
        path,
        max_length=settings.max_rel_path_chars,
    )
    if not abs_path.exists():
        raise NotFoundError("Файл не найден", context={"path": rel_norm})
    if not abs_path.is_file():
        raise BadRequestError("Цель должна быть файлом")

    n = (
        (
            await request.state.db_session.execute(
                select(FileNode).where(
                    FileNode.project_id == project_id,
                    FileNode.path == rel_norm,
                )
            )
        )
        .scalars()
        .first()
    )
    if not n:
        try:
            if not abs_path.exists():
                raise NotFoundError("Файл не найден", context={"path": rel_norm})
            if not abs_path.is_file():
                raise BadRequestError("Цель должна быть файлом")
            reindexed = scan_files(project_id, project.org_id, root, [rel_norm])
            if scan_aborted(reindexed):
                logger.warning(
                    "Scan aborted during node lookup",
                    extra={"path": rel_norm, "operation": "node_lookup"},
                )
            else:
                removed_neighbors_list = removed_neighbors(reindexed)
                update_graph_metrics_incremental(
                    project_id,
                    [rel_norm],
                    removed_edge_neighbors=removed_neighbors_list,
                )
        except ProjectLockTimeout as exc:
            raise LockedError(
                "Проект сейчас занят, повторите позже",
                context={"project_id": project_id},
            ) from exc
        n = (
            (
                await request.state.db_session.execute(
                    select(FileNode).where(
                        FileNode.project_id == project_id,
                        FileNode.path == rel_norm,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not n:
            raise NotFoundError("Узел не найден", context={"path": rel_norm})
    return {
        "path": n.path,
        "language": n.language,
        "loc": n.loc,
        "complexity": n.complexity,
        "fan_in": n.fan_in,
        "fan_out": n.fan_out,
        "scc_id": n.scc_id,
        "status": n.status,
    }


@router.get("/{project_id}/{path:path}/file")
async def get_file(request: Request, project_id: int, path: str, max_chars: int | None = None):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
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
async def update_file(
    request: Request,
    project_id: int,
    path: str,
    body: FileUpdate,
):
    # Single source of truth for mutation response: docs/file-mutation-contract.md
    project = await require_project_access_async(request, project_id, min_role="member")
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    if not abs_path.exists():
        raise NotFoundError("Файл не найден", context={"path": rel_norm})
    if not abs_path.is_file():
        raise BadRequestError("Цель должна быть файлом")

    content = body.content
    if not isinstance(content, str):
        raise BadRequestError("Некорректное содержимое файла")

    try:
        async with project_lock_async(request.state.db_session, project_id):
            if not abs_path.exists():
                raise NotFoundError("Файл не найден", context={"path": rel_norm})
            if not abs_path.is_file():
                raise BadRequestError("Цель должна быть файлом")
            abs_path.write_text(content, encoding="utf-8")
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc

    _invalidate_pack_cache(project_id)
    task_id, task_status = await task_queue.submit_mutation_indexing_async(
        project_id=project_id,
        org_id=project.org_id,
        rel_paths=[rel_norm],
        operation="update_file",
    )
    return build_mutation_queued_response(path=rel_norm, task_id=task_id, task_status=task_status)


@router.post("/{project_id}/{path:path}/file")
async def create_file(
    request: Request,
    project_id: int,
    path: str,
    body: FileCreate,
):
    project = await require_project_access_async(request, project_id, min_role="member")
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)

    content = body.content if isinstance(body.content, str) or body.content is None else None
    if content is None and body.content is not None:
        raise BadRequestError("Некорректное содержимое файла")
    content = content or ""

    try:
        async with project_lock_async(request.state.db_session, project_id):
            if abs_path.exists():
                raise BadRequestError("Файл уже существует", context={"path": rel_norm})
            parent = abs_path.parent
            if parent.exists() and not parent.is_dir():
                raise BadRequestError("Родительский путь должен быть директорией")
            if not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)

            abs_path.write_text(content, encoding="utf-8")
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc

    _invalidate_pack_cache(project_id)
    task_id, task_status = await task_queue.submit_mutation_indexing_async(
        project_id=project_id,
        org_id=project.org_id,
        rel_paths=[rel_norm],
        operation="create_file",
    )
    return build_mutation_queued_response(path=rel_norm, task_id=task_id, task_status=task_status)


@router.post("/{project_id}/{path:path}/rename")
async def rename_file(
    request: Request,
    project_id: int,
    path: str,
    body: FileRename,
):
    project = await require_project_access_async(request, project_id, min_role="member")
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    new_abs, new_rel = resolve_under_root(
        root,
        body.new_path,
        max_length=settings.max_rel_path_chars,
    )
    if rel_norm == new_rel:
        raise BadRequestError("Новый путь совпадает со старым", context={"path": rel_norm})

    try:
        async with project_lock_async(request.state.db_session, project_id):
            if not abs_path.exists():
                raise NotFoundError("Файл не найден", context={"path": rel_norm})
            if not abs_path.is_file():
                raise BadRequestError("Цель должна быть файлом")
            if new_abs.exists():
                raise BadRequestError("Файл уже существует", context={"path": new_rel})
            new_parent = new_abs.parent
            if not new_parent.exists():
                if body.create_dirs:
                    new_parent.mkdir(parents=True, exist_ok=True)
                else:
                    raise BadRequestError(
                        "Родительская директория не существует",
                        context={"path": new_rel},
                    )
            if not new_parent.is_dir():
                raise BadRequestError("Родительский путь должен быть директорией")

            abs_path.rename(new_abs)
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc

    _invalidate_pack_cache(project_id)
    task_id, task_status = await task_queue.submit_mutation_indexing_async(
        project_id=project_id,
        org_id=project.org_id,
        rel_paths=[rel_norm, new_rel],
        operation="rename_file",
    )
    return build_mutation_queued_response(path=new_rel, task_id=task_id, task_status=task_status)


@router.delete("/{project_id}/{path:path}/file")
async def delete_file(
    request: Request,
    project_id: int,
    path: str,
):
    project = await require_project_access_async(request, project_id, min_role="member")
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)

    try:
        async with project_lock_async(request.state.db_session, project_id):
            if not abs_path.exists():
                raise NotFoundError("Файл не найден", context={"path": rel_norm})
            if not abs_path.is_file():
                raise BadRequestError("Цель должна быть файлом")

            abs_path.unlink()
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc

    _invalidate_pack_cache(project_id)
    task_id, task_status = await task_queue.submit_mutation_indexing_async(
        project_id=project_id,
        org_id=project.org_id,
        rel_paths=[rel_norm],
        operation="delete_file",
    )
    return build_mutation_queued_response(path=rel_norm, task_id=task_id, task_status=task_status)
