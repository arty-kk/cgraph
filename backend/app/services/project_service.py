# backend/app/services/project_service.py
from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import BackgroundTasks
from sqlalchemy import func
from sqlmodel import delete, select

from ..config import settings
from ..db import get_session
from ..errors import BadRequestError, ForbiddenError, LockedError, NotFoundError
from ..graph import (
    compute_graph_metrics_with_threshold,
    graph_payload,
    local_subgraph,
    search_nodes,
    search_semantic,
)
from ..infra.cache import cache_get_json, cache_invalidate_prefix, cache_set_json
from ..logging import get_logger
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
    FileText,
    ModuleContract,
    Project,
    ProjectDoc,
    RepoSnapshot,
    TaskJob,
    TsTypeDef,
)
from ..patches import delete_patch_blob_for_sha
from ..scan import SEARCH_INDEX_MAX_CHARS, scan_project
from ..search import search_text_paths
from ..services.entitlements_service import get_entitlement_bool, get_entitlement_int
from ..services.usage_service import EMBEDDING_QUERY_KIND, check_and_increment, check_usage_limit
from ..snapshots import (
    SnapshotMeta,
    delete_project_snapshot_root,
    delete_snapshot,
    prepare_project_snapshot_root,
    snapshot_meta_from_dict,
    store_snapshot_blob,
)
from ..utils import ProjectLockTimeout, normalize_project_root, project_lock, resolve_under_root
from .task_queue import get_scan_idempotency_key, task_queue

logger = get_logger("stubgraph.project_service")


def _get_active_scan_task(project_id: int, org_id: int) -> tuple[str | None, str | None]:
    idempotency_key = get_scan_idempotency_key(org_id, project_id)
    with get_session() as session:
        job = session.exec(
            select(TaskJob).where(
                TaskJob.org_id == org_id,
                TaskJob.idempotency_key == idempotency_key,
                TaskJob.status.in_(("pending", "running")),
            )
        ).first()
    if not job:
        return None, None
    return job.id, job.status


def create_project(name: str, root_path: str, org_id: int) -> Project:
    if not settings.allow_local_root_path:
        raise BadRequestError("Локальные root_path отключены. Используй загрузку snapshot.")
    root = normalize_project_root(root_path, max_length=settings.max_root_path_chars)
    with get_session() as session:
        project = Project(name=name, root_path=str(root), org_id=org_id)
        session.add(project)
        session.commit()
        session.refresh(project)
    return project


def create_project_from_snapshot(
    name: str,
    meta: SnapshotMeta,
    org_id: int,
) -> Project:
    root = prepare_project_snapshot_root(meta)
    root = normalize_project_root(str(root), max_length=settings.max_root_path_chars)
    with get_session() as session:
        with session.begin():
            project = Project(name=name, root_path=str(root), org_id=org_id)
            session.add(project)
            session.flush()
            snapshot = RepoSnapshot(
                org_id=org_id,
                project_id=project.id,
                content_sha256=meta.sha256,
                archive_name=meta.archive_name,
                storage_json=json.dumps(asdict(meta), ensure_ascii=False),
            )
            session.add(snapshot)
        session.refresh(project)
    return project


def create_project_from_snapshot_blob(
    name: str,
    archive_bytes: bytes,
    archive_name: str,
    org_id: int,
) -> Project:
    meta = store_snapshot_blob(archive_bytes, archive_name)
    return create_project_from_snapshot(name, meta, org_id)


def list_projects(org_id: int) -> list[Project]:
    with get_session() as session:
        return session.exec(select(Project).where(Project.org_id == org_id)).all()


def get_latest_snapshots(project_ids: list[int]) -> dict[int, RepoSnapshot]:
    if not project_ids:
        return {}
    with get_session() as session:
        rows = session.exec(
            select(RepoSnapshot)
            .where(RepoSnapshot.project_id.in_(project_ids))
            .order_by(RepoSnapshot.project_id.asc(), RepoSnapshot.created_at.desc())
        ).all()
    latest: dict[int, RepoSnapshot] = {}
    for row in rows:
        if row.project_id not in latest:
            latest[row.project_id] = row
    return latest


def delete_project(project_id: int, org_id: int) -> None:
    try:
        with project_lock(project_id):
            with get_session() as session:
                project = session.exec(
                    select(Project).where(Project.id == project_id, Project.org_id == org_id)
                ).first()
                if not project:
                    raise NotFoundError("Проект не найден", context={"project_id": project_id})
                project_root_path = project.root_path
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
                snapshots = session.exec(
                    select(RepoSnapshot).where(RepoSnapshot.project_id == project_id)
                ).all()
                snapshot_payloads: list[tuple[RepoSnapshot, dict]] = []
                for snap in snapshots:
                    try:
                        payload = json.loads(snap.storage_json or "{}")
                    except Exception:  # noqa: BLE001
                        payload = {}
                    if isinstance(payload, dict):
                        has_other_refs = session.exec(
                            select(func.count())
                            .select_from(RepoSnapshot)
                            .where(
                                RepoSnapshot.content_sha256 == snap.content_sha256,
                                RepoSnapshot.project_id != project_id,
                            )
                        ).one()
                        has_other_refs = (
                            int(
                                has_other_refs[0]
                                if isinstance(has_other_refs, (tuple, list))
                                else has_other_refs
                            )
                            > 0
                        )
                        if has_other_refs:
                            continue
                        snapshot_payloads.append((snap, payload))
                session.exec(delete(FileEdge).where(FileEdge.project_id == project_id))
                session.exec(delete(FileNode).where(FileNode.project_id == project_id))
                session.exec(delete(ModuleContract).where(ModuleContract.project_id == project_id))
                session.exec(delete(ApiRoute).where(ApiRoute.project_id == project_id))
                session.exec(delete(ApiCall).where(ApiCall.project_id == project_id))
                session.exec(delete(ApiInclude).where(ApiInclude.project_id == project_id))
                session.exec(
                    delete(ApiRouteContract).where(ApiRouteContract.project_id == project_id)
                )
                session.exec(delete(ApiCallMeta).where(ApiCallMeta.project_id == project_id))
                session.exec(delete(TsTypeDef).where(TsTypeDef.project_id == project_id))
                session.exec(
                    delete(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id)
                )
                session.exec(delete(AnalysisRun).where(AnalysisRun.project_id == project_id))
                session.exec(delete(ProjectDoc).where(ProjectDoc.project_id == project_id))
                session.exec(delete(FileText).where(FileText.project_id == project_id))
                session.exec(delete(RepoSnapshot).where(RepoSnapshot.project_id == project_id))
                session.exec(delete(Project).where(Project.id == project_id))
                session.commit()
            try:
                delete_project_snapshot_root(project_root_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Project snapshot root delete failed",
                    extra={
                        "project_id": project_id,
                        "root_path": project_root_path,
                        "error": str(exc),
                    },
                )
                cache_set_json(
                    ["project_delete_failed", "project_root", str(project_id)],
                    {"project_id": project_id, "root_path": project_root_path, "error": str(exc)},
                )
            for sha in shas:
                try:
                    delete_patch_blob_for_sha(sha)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Patch blob delete failed",
                        extra={"project_id": project_id, "sha": sha, "error": str(exc)},
                    )
                    cache_set_json(
                        ["project_delete_failed", "patch", sha],
                        {"project_id": project_id, "sha": sha, "error": str(exc)},
                    )
            for snap, payload in snapshot_payloads:
                try:
                    delete_snapshot(snapshot_meta_from_dict(payload))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Snapshot delete failed",
                        extra={
                            "project_id": project_id,
                            "snapshot_sha": snap.content_sha256,
                            "archive_name": snap.archive_name,
                            "error": str(exc),
                        },
                    )
                    cache_set_json(
                        ["project_delete_failed", "snapshot", snap.content_sha256],
                        {
                            "project_id": project_id,
                            "archive_name": snap.archive_name,
                            "storage": payload.get("storage"),
                            "error": str(exc),
                        },
                    )
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc
    cache_invalidate_prefix([f"project:{project_id}"])


def list_project_files(
    project_id: int,
    org_id: int,
    prefix: str | None = None,
    cursor: str | None = None,
    limit: int = 50_000,
) -> dict:
    get_project(project_id, org_id=org_id)
    if limit < 1 or limit > 200_000:
        raise BadRequestError("limit должен быть в диапазоне 1..200000")

    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    cursor_norm: str | None = None
    if isinstance(cursor, str) and cursor.strip():
        cursor_norm = cursor.strip().replace("\\", "/")

    with get_session() as session:
        base = select(FileNode).where(FileNode.project_id == project_id)
        count_q = (
            select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
        )
        if prefix_norm:
            like = f"{prefix_norm}/%"
            base = base.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
            count_q = count_q.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
        if cursor_norm:
            base = base.where(FileNode.path > cursor_norm)

        total_row = session.exec(count_q).one()
        total = int(total_row[0] if isinstance(total_row, (tuple, list)) else total_row)

        rows = session.exec(base.order_by(FileNode.path).limit(int(limit) + 1)).all()

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

    truncated = len(files) > limit
    next_cursor = files[limit - 1]["path"] if truncated and limit > 0 else None
    files = files[:limit]
    return {
        "files": files,
        "meta": {
            "prefix": prefix_norm or "",
            "cursor": cursor_norm,
            "next_cursor": next_cursor,
            "total": total,
            "returned": len(files),
            "truncated": bool(truncated),
            "limit": int(limit),
        },
    }


def list_project_tree_entries(
    project_id: int,
    org_id: int,
    prefix: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
) -> dict:
    get_project(project_id, org_id=org_id)
    if limit < 1 or limit > 2000:
        raise BadRequestError("limit должен быть в диапазоне 1..2000")

    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    cursor_norm: str | None = None
    if isinstance(cursor, str) and cursor.strip():
        cursor_norm = cursor.strip().replace("\\", "/")

    with get_session() as session:
        base = select(FileNode).where(FileNode.project_id == project_id)
        if prefix_norm:
            like = f"{prefix_norm}/%"
            base = base.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
        if cursor_norm:
            base = base.where(FileNode.path > cursor_norm)

        scan_limit = min(20000, max(limit * 40, limit + 1))
        rows = session.exec(base.order_by(FileNode.path).limit(scan_limit + 1)).all()

    entries: list[dict] = []
    seen: set[str] = set()
    next_cursor = None

    def add_dir(child_path: str, name: str) -> None:
        if child_path in seen:
            return
        seen.add(child_path)
        entries.append(
            {
                "type": "dir",
                "path": child_path,
                "name": name,
                "has_children": True,
            }
        )

    def add_file(node: FileNode) -> None:
        if node.path in seen:
            return
        seen.add(node.path)
        entries.append(
            {
                "type": "file",
                "path": node.path,
                "name": node.path.split("/")[-1],
                "file": {
                    "path": node.path,
                    "language": node.language,
                    "loc": int(node.loc or 0),
                    "complexity": int(node.complexity or 0),
                    "fan_in": int(node.fan_in or 0),
                    "fan_out": int(node.fan_out or 0),
                    "status": node.status,
                    "risk": (0.3 * float(node.complexity or 0))
                    + (0.7 * float(node.fan_in or 0))
                    + (0.1 * float(node.fan_out or 0)),
                },
            }
        )

    for row in rows:
        path = row.path if isinstance(row.path, str) else ""
        if not path:
            continue
        rel = path
        if prefix_norm:
            if path == prefix_norm:
                rel = path.split("/")[-1]
            elif path.startswith(f"{prefix_norm}/"):
                rel = path[len(prefix_norm) + 1 :]
            else:
                continue
        if not rel:
            continue
        if "/" in rel:
            name = rel.split("/", 1)[0]
            child_path = f"{prefix_norm}/{name}" if prefix_norm else name
            add_dir(child_path, name)
        else:
            add_file(row)

        next_cursor = path
        if len(entries) >= limit:
            break

    truncated = len(entries) >= limit and next_cursor is not None
    return {
        "entries": entries,
        "meta": {
            "prefix": prefix_norm or "",
            "cursor": cursor_norm,
            "next_cursor": next_cursor if truncated else None,
            "returned": len(entries),
            "truncated": bool(truncated),
            "limit": int(limit),
        },
    }


def get_file_dependencies(
    project_id: int,
    org_id: int,
    path: str,
    limit: int = 2000,
    cursor_in: str | None = None,
    cursor_out: str | None = None,
) -> dict:
    project = get_project(project_id, org_id=org_id)
    if not isinstance(path, str) or not path.strip():
        raise BadRequestError("path обязателен")
    if limit < 1 or limit > 20_000:
        raise BadRequestError("limit должен быть в диапазоне 1..20000")

    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    _, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)

    cursor_in_norm = cursor_in.strip().replace("\\", "/") if isinstance(cursor_in, str) and cursor_in.strip() else None
    cursor_out_norm = cursor_out.strip().replace("\\", "/") if isinstance(cursor_out, str) and cursor_out.strip() else None

    with get_session() as session:
        inbound_count = session.exec(
            select(func.count()).select_from(FileEdge).where(
                FileEdge.project_id == project_id, FileEdge.dst_path == rel_norm
            )
        ).one()
        outbound_count = session.exec(
            select(func.count()).select_from(FileEdge).where(
                FileEdge.project_id == project_id, FileEdge.src_path == rel_norm
            )
        ).one()

        if isinstance(inbound_count, (tuple, list)):
            inbound_value = inbound_count[0] if inbound_count else 0
        else:
            inbound_value = inbound_count
        if isinstance(outbound_count, (tuple, list)):
            outbound_value = outbound_count[0] if outbound_count else 0
        else:
            outbound_value = outbound_count
        inbound_total = int(inbound_value)
        outbound_total = int(outbound_value)

        inbound_query = (
            select(FileEdge.src_path)
            .where(FileEdge.project_id == project_id, FileEdge.dst_path == rel_norm)
            .order_by(FileEdge.src_path)
        )
        outbound_query = (
            select(FileEdge.dst_path)
            .where(FileEdge.project_id == project_id, FileEdge.src_path == rel_norm)
            .order_by(FileEdge.dst_path)
        )
        if cursor_in_norm:
            inbound_query = inbound_query.where(FileEdge.src_path > cursor_in_norm)
        if cursor_out_norm:
            outbound_query = outbound_query.where(FileEdge.dst_path > cursor_out_norm)

        inbound_rows = session.exec(inbound_query.limit(limit + 1)).all()
        outbound_rows = session.exec(outbound_query.limit(limit + 1)).all()

    inbound = [
        r[0] if isinstance(r, (tuple, list)) else r
        for r in inbound_rows
        if isinstance(r[0] if isinstance(r, (tuple, list)) else r, str)
    ]
    outbound = [
        r[0] if isinstance(r, (tuple, list)) else r
        for r in outbound_rows
        if isinstance(r[0] if isinstance(r, (tuple, list)) else r, str)
    ]

    inbound_truncated = len(inbound) > limit
    outbound_truncated = len(outbound) > limit
    inbound_next_cursor = inbound[limit - 1] if inbound_truncated and limit > 0 else None
    outbound_next_cursor = outbound[limit - 1] if outbound_truncated and limit > 0 else None
    inbound = inbound[:limit]
    outbound = outbound[:limit]

    return {
        "path": rel_norm,
        "inbound": inbound,
        "outbound": outbound,
        "meta": {
            "limit": int(limit),
            "cursor_in": cursor_in_norm,
            "cursor_out": cursor_out_norm,
            "next_cursor_in": inbound_next_cursor,
            "next_cursor_out": outbound_next_cursor,
            "total_inbound": inbound_total,
            "total_outbound": outbound_total,
            "truncated_inbound": inbound_truncated,
            "truncated_outbound": outbound_truncated,
        },
    }


def get_project(project_id: int, org_id: int | None = None) -> Project:
    with get_session() as session:
        if org_id is None:
            project = session.get(Project, project_id)
        else:
            project = session.exec(
                select(Project).where(Project.id == project_id, Project.org_id == org_id)
            ).first()
    if not project:
        raise NotFoundError("Проект не найден", context={"project_id": project_id})
    return project


def _scan_and_update_graph(
    project_id: int,
    org_id: int,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    project = get_project(project_id, org_id=org_id)
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    stats = scan_project(project_id, org_id, root)
    try:
        with project_lock(project_id):
            metrics_pending = compute_graph_metrics_with_threshold(
                project_id,
                background_tasks=background_tasks,
            )
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc
    cache_invalidate_prefix([f"project:{project_id}"])
    return {"ok": True, "stats": stats, "metrics_pending": bool(metrics_pending)}


def scan_with_background(
    project_id: int,
    org_id: int,
    background: bool = False,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    if background:
        task_id, status = _get_active_scan_task(project_id, org_id)
        if task_id and status in ("pending", "running"):
            return {"task_id": task_id, "status": status}

        task_id = task_queue.submit_scan(project_id, org_id)
        if background_tasks is not None:
            background_tasks.add_task(lambda: None)
        return {"task_id": task_id, "status": "pending"}
    return _scan_and_update_graph(project_id, org_id, background_tasks=background_tasks)


def load_graph(project_id: int, org_id: int, limit_nodes: int | None = None) -> dict:
    get_project(project_id, org_id=org_id)
    return graph_payload(project_id, limit_nodes=limit_nodes)


def load_local_graph(
    project_id: int,
    org_id: int,
    path: str,
    hops: int,
    max_nodes: int,
    max_edges: int,
) -> dict:
    project = get_project(project_id, org_id=org_id)
    if hops < 0:
        raise BadRequestError("Количество шагов не может быть отрицательным")
    if max_nodes <= 0 or max_edges <= 0:
        raise BadRequestError("Лимиты графа должны быть положительными")

    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    _, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    return local_subgraph(project_id, rel_norm, hops=hops, max_nodes=max_nodes, max_edges=max_edges)


def search_project_nodes(project_id: int, org_id: int, query: str, limit: int = 20) -> list[dict]:
    get_project(project_id, org_id=org_id)
    if not isinstance(query, str) or not query.strip():
        raise BadRequestError("Параметр q обязателен")
    if limit < 1 or limit > 200:
        raise BadRequestError("Лимит выдачи должен быть между 1 и 200")
    cache_key = [f"project:{project_id}", "search_nodes", query.strip(), str(limit)]
    cached = cache_get_json(cache_key)
    if isinstance(cached, list):
        return cached
    result = search_nodes(project_id, query.strip(), limit=limit)
    cache_set_json(cache_key, result)
    return result


def search_project_semantic(
    project_id: int,
    org_id: int,
    query: str,
    *,
    limit: int = 20,
    prefix: str | None = None,
) -> dict:
    project = get_project(project_id, org_id=org_id)
    if not isinstance(query, str) or not query.strip():
        raise BadRequestError("Параметр q обязателен")
    if limit < 1 or limit > 200:
        raise BadRequestError("Лимит выдачи должен быть между 1 и 200")

    ent_embeddings_enabled = get_entitlement_bool(org_id, "embeddings_enabled")
    usage_enabled = settings.embeddings_enabled and ent_embeddings_enabled is not False
    query_limit: int | None = None
    if usage_enabled:
        query_limit = get_entitlement_int(org_id, "embeddings_daily_query_limit")
        check_usage_limit(
            org_id,
            EMBEDDING_QUERY_KIND,
            1,
            query_limit if query_limit is not None else settings.embeddings_daily_query_limit,
        )
    elif ent_embeddings_enabled is False:
        raise ForbiddenError("Семантический поиск недоступен по плану")

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
    if usage_enabled:
        check_and_increment(
            org_id,
            EMBEDDING_QUERY_KIND,
            1,
            query_limit if query_limit is not None else settings.embeddings_daily_query_limit,
        )
    return response


def search_project_text(
    project_id: int,
    org_id: int,
    query: str,
    *,
    limit_files: int = 200,
    limit_matches: int = 50,
    context_chars: int = 160,
    prefix: str | None = None,
    case_sensitive: bool = False,
) -> dict:
    project = get_project(project_id, org_id=org_id)
    if not isinstance(query, str) or not query.strip():
        raise BadRequestError("Параметр q обязателен")
    if limit_files < 1 or limit_files > 2000:
        raise BadRequestError("limit_files должен быть в диапазоне 1..2000")
    if limit_matches < 1 or limit_matches > 500:
        raise BadRequestError("limit_matches должен быть в диапазоне 1..500")
    if context_chars < 40 or context_chars > 400:
        raise BadRequestError("context_chars должен быть в диапазоне 40..400")

    needle = query.strip()
    cache_key = [
        f"project:{project_id}",
        "search_text",
        needle,
        str(limit_files),
        str(limit_matches),
        str(context_chars),
        str(prefix or ""),
        "1" if case_sensitive else "0",
    ]
    cached = cache_get_json(cache_key)
    if isinstance(cached, dict):
        return cached

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
        result = {
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
        cache_set_json(cache_key, result)
        return result

    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)

    scan_max_chars = max(1, min(int(settings.llm_agentic_max_file_chars), 200_000))
    index_scan_max_chars = min(SEARCH_INDEX_MAX_CHARS, scan_max_chars)

    paths: list[str] = []

    try:
        paths = search_text_paths(
            project_id,
            needle,
            limit=limit_files,
            prefix=prefix_norm,
        )
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

    indexed_text: dict[str, str] = {}
    if paths:
        SQLITE_IN_CHUNK = 400

        def _iter_chunks(seq: list[str], size: int):
            for i in range(0, len(seq), size):
                yield seq[i : i + size]

        with get_session() as s:
            for chunk in _iter_chunks(paths, SQLITE_IN_CHUNK):
                rows = s.exec(
                    select(FileText.path, FileText.content).where(
                        FileText.project_id == project_id,
                        FileText.path.in_(chunk),
                    )
                ).all()
                for row in rows:
                    if isinstance(row, (tuple, list)) and len(row) >= 2:
                        p, content = row[0], row[1]
                    else:
                        p, content = None, None
                    if isinstance(p, str) and p and isinstance(content, str):
                        indexed_text[p] = content

    for p in paths:
        if len(matches) >= limit_matches:
            break
        try:
            abs_path, rel_norm = resolve_under_root(root, p, max_length=settings.max_rel_path_chars)
        except Exception:
            continue
        text_source = indexed_text.get(rel_norm)
        from_index = text_source is not None
        if text_source is None:
            if not abs_path.exists() or not abs_path.is_file():
                continue
            try:
                with abs_path.open("r", encoding="utf-8", errors="replace") as f:
                    text_source = f.read(int(scan_max_chars) + 1)
            except Exception:
                continue
        scanned += 1
        truncated_initial = len(text_source) > scan_max_chars
        if truncated_initial:
            text = text_source[:scan_max_chars]
        else:
            text = text_source

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
            if from_index:
                text = text_source[: int(index_scan_max_chars) + 1]
                truncated = len(text) > index_scan_max_chars
                if truncated:
                    text = text[:index_scan_max_chars]
                _search_text(text, truncated_flag=truncated)
            else:
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

    result = {
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
    cache_set_json(cache_key, result)
    return result
