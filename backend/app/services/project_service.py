#backend/app/services/project_service.py
from __future__ import annotations

import json
from pathlib import Path

from fastapi import BackgroundTasks
from sqlmodel import select, delete
from sqlalchemy import func, text as sa_text

from ..config import settings
from ..db import get_session
from ..errors import BadRequestError, NotFoundError
from ..graph import compute_graph_metrics, graph_payload, local_subgraph, search_nodes, search_semantic
from ..logging import get_logger
from ..models import (
    Project, FileNode, FileEdge, ModuleContract,
    AnalysisRun, ProjectDoc, ApiRoute, ApiCall,
    ApiInclude, ApiRouteContract, ApiCallMeta, TsTypeDef, FileChunkEmbedding
)
from ..scan import scan_project
from ..utils import normalize_project_root, project_lock, resolve_under_root
from .task_queue import task_queue

PATCH_BLOB_DIRNAME = "patches"
logger = get_logger("cgraph.api")


def _delete_patch_blob_for_sha(sha: str) -> None:
    if not isinstance(sha, str) or not sha:
        return
    base = Path(settings.db_dir).resolve()
    fp = (base / PATCH_BLOB_DIRNAME / f"{sha}.diff").resolve()
    if base not in fp.parents and fp != base:
        logger.warning("Refusing to delete patch blob outside db_dir", extra={"sha": sha})
        return
    if fp.exists() and fp.is_file():
        try:
            fp.unlink()
        except Exception as error:  # noqa: BLE001
            logger.warning("Failed to delete patch blob", extra={"sha": sha, "reason": str(error)})


def create_project(name: str, root_path: str) -> Project:
    root = normalize_project_root(root_path, max_length=settings.max_root_path_chars)
    with get_session() as session:
        project = Project(name=name, root_path=str(root))
        session.add(project)
        session.commit()
        session.refresh(project)
    return project


def list_projects() -> list[Project]:
    with get_session() as session:
        return session.exec(select(Project)).all()


def delete_project(project_id: int) -> None:
    with project_lock(project_id):
        with get_session() as session:
            project = session.get(Project, project_id)
            if not project:
                raise NotFoundError("Проект не найден", context={"project_id": project_id})

            session.exec(delete(FileEdge).where(FileEdge.project_id == project_id))
            session.exec(delete(FileNode).where(FileNode.project_id == project_id))
            session.exec(delete(ModuleContract).where(ModuleContract.project_id == project_id))
            session.exec(delete(ApiRoute).where(ApiRoute.project_id == project_id))
            session.exec(delete(ApiCall).where(ApiCall.project_id == project_id))
            session.exec(delete(ApiInclude).where(ApiInclude.project_id == project_id))
            session.exec(delete(ApiRouteContract).where(ApiRouteContract.project_id == project_id))
            session.exec(delete(ApiCallMeta).where(ApiCallMeta.project_id == project_id))
            session.exec(delete(TsTypeDef).where(TsTypeDef.project_id == project_id))
            session.exec(delete(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id))
            runs = session.exec(select(AnalysisRun).where(AnalysisRun.project_id == project_id)).all()
            shas: set[str] = set()
            for run in runs:
                try:
                    data = json.loads(run.result_json or "{}")
                except Exception:  # noqa: BLE001
                    data = {}
                if not isinstance(data, dict):
                    continue
                meta = data.get("patch_unified_diff_meta")
                if isinstance(meta, dict):
                    sha = meta.get("sha256")
                    if isinstance(sha, str) and sha:
                        shas.add(sha)
            for sha in shas:
                _delete_patch_blob_for_sha(sha)
            session.exec(delete(AnalysisRun).where(AnalysisRun.project_id == project_id))
            session.exec(delete(ProjectDoc).where(ProjectDoc.project_id == project_id))
            try:
                session.execute(sa_text("DELETE FROM filetext_fts WHERE project_id=:pid"), {"pid": int(project_id)})
            except Exception:
                pass
            session.exec(delete(Project).where(Project.id == project_id))
            session.commit()


def list_project_files(project_id: int, prefix: str | None = None, limit: int = 50_000) -> dict:
    get_project(project_id)
    if limit < 1 or limit > 200_000:
        raise BadRequestError("limit должен быть в диапазоне 1..200000")

    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    with get_session() as session:
        base = select(FileNode).where(FileNode.project_id == project_id)
        count_q = select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
        if prefix_norm:
            like = f"{prefix_norm}/%"
            base = base.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
            count_q = count_q.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))

        total_row = session.exec(count_q).one()
        total = int(total_row[0] if isinstance(total_row, (tuple, list)) else total_row)

        rows = session.exec(base.order_by(FileNode.path).limit(int(limit))).all()

    def risk(n: FileNode) -> float:
        try:
            return (0.3 * float(n.complexity or 0)) + (0.7 * float(n.fan_in or 0)) + (0.1 * float(n.fan_out or 0))
        except Exception:
            return 0.0

    files = [
        {
            "path": n.path,
            "language": n.language,
            "loc": int(n.loc or 0),
            "complexity": int(n.complexity or 0),
            "fan_in": int(n.fan_in or 0),
            "fan_out": int(n.fan_out or 0),
            "status": n.status,
            "risk": risk(n),
        }
        for n in rows
        if isinstance(n.path, str) and n.path
    ]

    truncated = total > len(files)
    return {
        "files": files,
        "meta": {
            "prefix": prefix_norm or "",
            "total": total,
            "returned": len(files),
            "truncated": bool(truncated),
            "limit": int(limit),
        },
    }


def get_project(project_id: int) -> Project:
    with get_session() as session:
        project = session.get(Project, project_id)
    if not project:
        raise NotFoundError("Проект не найден", context={"project_id": project_id})
    return project


def _scan_and_update_graph(project_id: int) -> dict:
    project = get_project(project_id)
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    stats = scan_project(project_id, root)
    with project_lock(project_id):
        compute_graph_metrics(project_id)
    return {"ok": True, "stats": stats}


def scan_with_background(project_id: int, background: bool = False, background_tasks: BackgroundTasks | None = None) -> dict:
    if background:
        task_id = task_queue.submit(lambda: _scan_and_update_graph(project_id))
        if background_tasks is not None:
            background_tasks.add_task(lambda: None)
        return {"task_id": task_id, "status": "pending"}
    return _scan_and_update_graph(project_id)


def load_graph(project_id: int, limit_nodes: int | None = None) -> dict:
    get_project(project_id)
    return graph_payload(project_id, limit_nodes=limit_nodes)


def load_local_graph(
    project_id: int,
    path: str,
    hops: int,
    max_nodes: int,
    max_edges: int,
) -> dict:
    project = get_project(project_id)
    if hops < 0:
        raise BadRequestError("Количество шагов не может быть отрицательным")
    if max_nodes <= 0 or max_edges <= 0:
        raise BadRequestError("Лимиты графа должны быть положительными")

    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    _, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    return local_subgraph(project_id, rel_norm, hops=hops, max_nodes=max_nodes, max_edges=max_edges)


def search_project_nodes(project_id: int, query: str, limit: int = 20) -> list[dict]:
    get_project(project_id)
    if not isinstance(query, str) or not query.strip():
        raise BadRequestError("Параметр q обязателен")
    if limit < 1 or limit > 200:
        raise BadRequestError("Лимит выдачи должен быть между 1 и 200")
    return search_nodes(project_id, query.strip(), limit=limit)


def search_project_semantic(
    project_id: int,
    query: str,
    *,
    limit: int = 20,
    prefix: str | None = None,
) -> dict:
    project = get_project(project_id)
    if not isinstance(query, str) or not query.strip():
        raise BadRequestError("Параметр q обязателен")
    if limit < 1 or limit > 200:
        raise BadRequestError("Лимит выдачи должен быть между 1 и 200")

    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    response = search_semantic(project_id, root, query.strip(), max_results=limit, prefix=prefix)
    if isinstance(response, dict) and response.get("error"):
        message = response.get("message")
        if not isinstance(message, str) or not message:
            message = "Ошибка семантического поиска"
        raise BadRequestError(message)
    return response
