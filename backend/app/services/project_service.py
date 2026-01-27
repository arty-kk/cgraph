#backend/app/services/project_service.py
from __future__ import annotations

import json
import re
from threading import Lock
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import func
from sqlalchemy import text as sa_text
from sqlmodel import delete, select

from ..config import settings
from ..db import get_session
from ..errors import BadRequestError, NotFoundError
from ..graph import (
    compute_graph_metrics,
    graph_payload,
    local_subgraph,
    search_nodes,
    search_semantic,
)
from ..models import (
    AnalysisRun,
    ApiCall,
    ApiCallMeta,
    ApiInclude,
    ApiRoute,
    ApiRouteContract,
    FileChunkEmbedding,
    FileEdge,
    FileNode,
    ModuleContract,
    Project,
    ProjectDoc,
    TsTypeDef,
)
from ..patches import delete_patch_blob_for_sha
from ..scan import SEARCH_INDEX_MAX_CHARS, scan_project
from ..utils import normalize_project_root, project_lock, resolve_under_root
from .task_queue import task_queue

_scan_tasks: dict[int, str] = {}
_scan_tasks_lock = Lock()

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _fts_query_from_substring(q: str, *, max_tokens: int = 12) -> str | None:
    tokens = [t for t in _FTS_TOKEN_RE.findall(q or "") if t]
    if not tokens:
        return None
    tokens = tokens[: max(1, int(max_tokens))]
    esc = []
    for t in tokens:
        esc.append(t.replace('"', '""'))
    return " AND ".join([f'"{t}"' for t in esc if t])


def _get_active_scan_task(project_id: int) -> tuple[str | None, str | None]:
    with _scan_tasks_lock:
        task_id = _scan_tasks.get(project_id)
    if not task_id:
        return None, None
    state = task_queue.get(task_id)
    if not state:
        with _scan_tasks_lock:
            if _scan_tasks.get(project_id) == task_id:
                _scan_tasks.pop(project_id, None)
        return None, None
    if state.status in ("pending", "running"):
        return task_id, state.status
    with _scan_tasks_lock:
        if _scan_tasks.get(project_id) == task_id:
            _scan_tasks.pop(project_id, None)
    return task_id, state.status


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
            session.exec(
                delete(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id)
            )
            runs = session.exec(
                select(AnalysisRun).where(AnalysisRun.project_id == project_id)
            ).all()
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
                delete_patch_blob_for_sha(sha)
            session.exec(delete(AnalysisRun).where(AnalysisRun.project_id == project_id))
            session.exec(delete(ProjectDoc).where(ProjectDoc.project_id == project_id))
            try:
                session.execute(
                    sa_text("DELETE FROM filetext_fts WHERE project_id=:pid"),
                    {"pid": int(project_id)},
                )
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
        count_q = (
            select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
        )
        if prefix_norm:
            like = f"{prefix_norm}/%"
            base = base.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
            count_q = count_q.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))

        total_row = session.exec(count_q).one()
        total = int(total_row[0] if isinstance(total_row, (tuple, list)) else total_row)

        rows = session.exec(base.order_by(FileNode.path).limit(int(limit))).all()

    def risk(n: FileNode) -> float:
        try:
            return (
                (0.3 * float(n.complexity or 0))
                + (0.7 * float(n.fan_in or 0))
                + (0.1 * float(n.fan_out or 0))
            )
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


def scan_with_background(
    project_id: int,
    background: bool = False,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    if background:
        task_id, status = _get_active_scan_task(project_id)
        if task_id and status in ("pending", "running"):
            return {"task_id": task_id, "status": status}

        task_id = task_queue.submit(lambda: _scan_and_update_graph(project_id))
        with _scan_tasks_lock:
            _scan_tasks[project_id] = task_id
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
        meta = response.get("meta")
        reason = meta.get("reason") if isinstance(meta, dict) else None
        context = {"reason": reason} if isinstance(reason, str) and reason else None
        raise BadRequestError(message, context=context)
    return response


def search_project_text(
    project_id: int,
    query: str,
    *,
    limit_files: int = 200,
    limit_matches: int = 50,
    context_chars: int = 160,
    prefix: str | None = None,
    case_sensitive: bool = False,
) -> dict:
    project = get_project(project_id)
    if not isinstance(query, str) or not query.strip():
        raise BadRequestError("Параметр q обязателен")
    if limit_files < 1 or limit_files > 2000:
        raise BadRequestError("limit_files должен быть в диапазоне 1..2000")
    if limit_matches < 1 or limit_matches > 500:
        raise BadRequestError("limit_matches должен быть в диапазоне 1..500")
    if context_chars < 40 or context_chars > 400:
        raise BadRequestError("context_chars должен быть в диапазоне 40..400")

    needle = query.strip()

    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    with get_session() as session:
        row = session.exec(
            select(FileNode.id).where(FileNode.project_id == project_id).limit(1)
        ).first()
    if not row:
        return {
            "matches": [],
            "meta": {
                "query": needle,
                "prefix": prefix_norm or "",
                "case_sensitive": bool(case_sensitive),
                "limit_files": int(limit_files),
                "limit_matches": int(limit_matches),
                "context_chars": int(context_chars),
                "scan_max_chars_per_file": int(settings.llm_agentic_max_file_chars),
                "scanned_files": 0,
                "matched_files": 0,
                "truncated_files": 0,
                "message": "Проект не проиндексирован. Запустите Scan.",
            },
        }

    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)

    scan_max_chars = max(1, min(int(settings.llm_agentic_max_file_chars), 200_000))
    index_scan_max_chars = min(SEARCH_INDEX_MAX_CHARS, scan_max_chars)

    paths: list[str] = []

    fts_query = _fts_query_from_substring(needle)
    if fts_query:
        try:
            sql = "SELECT path FROM filetext_fts WHERE filetext_fts MATCH :q AND project_id = :pid"
            params: dict[str, Any] = {"q": fts_query, "pid": int(project_id)}
            if prefix_norm:
                params["prefix"] = prefix_norm
                params["like"] = f"{prefix_norm}/%"
                sql += " AND (path = :prefix OR path LIKE :like)"
            sql += " ORDER BY bm25(filetext_fts) LIMIT :lim"
            params["lim"] = int(limit_files)
            with get_session() as s:
                rows = s.execute(sa_text(sql), params).all()
            for row in rows:
                p = row[0] if isinstance(row, (tuple, list)) else row
                if isinstance(p, str) and p:
                    paths.append(p)
        except Exception:
            paths = []

    if not paths:
        with get_session() as s:
            q = select(FileNode.path).where(FileNode.project_id == project_id)
            if prefix_norm:
                like = f"{prefix_norm}/%"
                q = q.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
            q = q.order_by(FileNode.fan_in.desc(), FileNode.path.asc()).limit(int(limit_files))
            rows = s.exec(q).all()
        for row in rows:
            p = row[0] if isinstance(row, (tuple, list)) else row
            if isinstance(p, str) and p:
                paths.append(p)

    needle_cmp = needle if case_sensitive else needle.lower()

    matches: list[dict] = []
    scanned = 0
    matched_files: set[str] = set()
    truncated_files = 0

    for p in paths:
        if len(matches) >= limit_matches:
            break
        try:
            abs_path, rel_norm = resolve_under_root(root, p, max_length=settings.max_rel_path_chars)
        except Exception:
            continue
        if not abs_path.exists() or not abs_path.is_file():
            continue
        try:
            with abs_path.open("r", encoding="utf-8", errors="replace") as f:
                text = f.read(int(scan_max_chars) + 1)
        except Exception:
            continue
        scanned += 1
        truncated_initial = len(text) > scan_max_chars
        if truncated_initial:
            text = text[:scan_max_chars]

        def _search_text(payload: str, *, truncated_flag: bool) -> bool:
            haystack = payload if case_sensitive else payload.lower()
            start_idx = 0
            found_any = False
            while True:
                if len(matches) >= limit_matches:
                    break
                idx = haystack.find(needle_cmp, start_idx)
                if idx == -1:
                    break
                found_any = True
                matched_files.add(rel_norm)

                line = payload.count("\n", 0, idx) + 1
                last_nl = payload.rfind("\n", 0, idx)
                col = (idx - (last_nl + 1)) + 1 if last_nl != -1 else idx + 1

                half = max(10, context_chars // 2)
                s0 = max(0, idx - half)
                e0 = min(len(payload), idx + len(needle) + half)
                snippet = payload[s0:e0]

                matches.append(
                    {
                        "path": rel_norm,
                        "line": int(line),
                        "col": int(col),
                        "snippet": snippet,
                        "truncated_file": bool(truncated_flag),
                    }
                )

                step = max(1, len(needle_cmp))
                start_idx = idx + step
            return found_any

        truncated = truncated_initial
        matched = _search_text(text, truncated_flag=truncated)

        if truncated_initial and not matched and scan_max_chars < index_scan_max_chars:
            try:
                with abs_path.open("r", encoding="utf-8", errors="replace") as f:
                    text = f.read(int(index_scan_max_chars) + 1)
            except Exception:
                continue
            truncated = len(text) > index_scan_max_chars
            if truncated:
                text = text[:index_scan_max_chars]
            _search_text(text, truncated_flag=truncated)

        if truncated:
            truncated_files += 1

    return {
        "matches": matches,
        "meta": {
            "query": needle,
            "prefix": prefix_norm or "",
            "case_sensitive": bool(case_sensitive),
            "limit_files": int(limit_files),
            "limit_matches": int(limit_matches),
            "context_chars": int(context_chars),
            "scan_max_chars_per_file": int(scan_max_chars),
            "scanned_files": int(scanned),
            "matched_files": int(len(matched_files)),
            "truncated_files": int(truncated_files),
        },
    }
