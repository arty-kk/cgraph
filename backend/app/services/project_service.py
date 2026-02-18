# backend/app/services/project_service.py
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from fastapi import BackgroundTasks
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from ..async_db import AsyncSessionLocal
from ..config import settings
from ..errors import BadRequestError, ForbiddenError, LockedError, NotFoundError
from ..graph import compute_graph_metrics_async
from ..infra.cache import cache_get_json_async, cache_invalidate_prefix_async, cache_set_json_async
from ..llm.client import get_async_openai_client
from ..logging import get_logger
from ..models import (
    AnalysisRun,
    AnalysisStageTelemetry,
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
from ..search import search_text_paths_async
from ..services.entitlements_service import (
    get_entitlement_bool_async,
    get_entitlement_int_async,
)
from ..services.usage_service import (
    EMBEDDING_QUERY_KIND,
    check_and_increment_async,
    check_usage_limit_async,
)
from ..snapshots import (
    SnapshotMeta,
    delete_project_snapshot_root_async,
    delete_snapshot_async,
    prepare_project_snapshot_root_async,
    snapshot_meta_from_dict,
)
from ..utils import (
    ProjectLockTimeout,
    normalize_project_root,
    project_lock_async,
    resolve_under_root,
)
from .task_queue import get_scan_idempotency_key_async, submit_scan_async

logger = get_logger("stubgraph.project_service")


async def _delete_patch_blob_for_sha_async(sha: str) -> None:
    await asyncio.to_thread(delete_patch_blob_for_sha, sha)


async def _delete_patch_blobs_async(
    shas: set[str],
    *,
    max_parallel: int = 4,
) -> list[tuple[str, Exception]]:
    selected = [sha for sha in sorted(shas) if isinstance(sha, str) and sha]
    if not selected:
        return []

    semaphore = asyncio.Semaphore(max(1, int(max_parallel)))

    async def _delete_one(sha: str) -> tuple[str, Exception] | None:
        async with semaphore:
            try:
                await _delete_patch_blob_for_sha_async(sha)
            except Exception as exc:  # noqa: BLE001
                return sha, exc
            return None

    rows = await asyncio.gather(*[_delete_one(sha) for sha in selected])
    return [row for row in rows if row is not None]


async def _delete_snapshots_async(
    snapshot_payloads: list[tuple[RepoSnapshot, dict]],
    *,
    max_parallel: int = 4,
) -> list[tuple[RepoSnapshot, dict, Exception]]:
    if not snapshot_payloads:
        return []

    semaphore = asyncio.Semaphore(max(1, int(max_parallel)))

    async def _delete_one(
        snap: RepoSnapshot,
        payload: dict,
    ) -> tuple[RepoSnapshot, dict, Exception] | None:
        async with semaphore:
            try:
                await delete_snapshot_async(snapshot_meta_from_dict(payload))
            except Exception as exc:  # noqa: BLE001
                return snap, payload, exc
            return None

    rows = await asyncio.gather(*[_delete_one(snap, payload) for snap, payload in snapshot_payloads])
    return [row for row in rows if row is not None]


def _extract_patch_blob_shas(runs) -> set[str]:
    shas: set[str] = set()
    for run in runs:
        try:
            data = json.loads(getattr(run, "result_json", None) or "{}")
        except Exception:
            data = {}
        if not isinstance(data, dict):
            continue
        meta = data.get("patch_unified_diff_meta")
        if isinstance(meta, dict):
            sha = meta.get("sha256")
            if isinstance(sha, str) and sha:
                shas.add(sha)
    return shas


async def _extract_patch_blob_shas_async(runs) -> set[str]:
    return await asyncio.to_thread(_extract_patch_blob_shas, runs)


def _parse_snapshot_storage_payloads(snapshots) -> list[tuple[RepoSnapshot, dict]]:
    payloads: list[tuple[RepoSnapshot, dict]] = []
    for snap in snapshots:
        try:
            payload = json.loads(getattr(snap, "storage_json", None) or "{}")
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            payloads.append((snap, payload))
    return payloads


async def _parse_snapshot_storage_payloads_async(
    snapshots,
) -> list[tuple[RepoSnapshot, dict]]:
    return await asyncio.to_thread(_parse_snapshot_storage_payloads, snapshots)


async def _collect_delete_artifacts_async(
    runs,
    snapshots,
) -> tuple[set[str], list[tuple[RepoSnapshot, dict]]]:
    return await asyncio.gather(
        _extract_patch_blob_shas_async(runs),
        _parse_snapshot_storage_payloads_async(snapshots),
    )


async def _delete_project_artifacts_async(
    shas: set[str],
    snapshot_payloads: list[tuple[RepoSnapshot, dict]],
) -> tuple[list[tuple[str, Exception]], list[tuple[RepoSnapshot, dict, Exception]]]:
    return await asyncio.gather(
        _delete_patch_blobs_async(shas),
        _delete_snapshots_async(snapshot_payloads),
    )




async def _cache_project_delete_failures_async(rows: list[tuple[list[str], dict]]) -> None:
    if not rows:
        return
    await asyncio.gather(
        *(
            cache_set_json_async(parts, payload)
            for parts, payload in rows
            if isinstance(parts, list) and isinstance(payload, dict)
        )
    )

async def _load_snapshot_ref_counts_async(
    session: AsyncSession,
    project_id: int,
    content_shas: set[str],
) -> dict[str, int]:
    selected = [sha for sha in sorted(content_shas) if isinstance(sha, str) and sha]
    if not selected:
        return {}

    rows = (
        await session.execute(
            select(RepoSnapshot.content_sha256, func.count())
            .where(
                RepoSnapshot.content_sha256.in_(selected),
                RepoSnapshot.project_id != project_id,
            )
            .group_by(RepoSnapshot.content_sha256)
        )
    ).all()

    counts: dict[str, int] = {}
    for row in rows:
        if isinstance(row, (tuple, list)) and len(row) >= 2:
            sha, count = row[0], row[1]
        else:
            continue
        if isinstance(sha, str) and sha:
            counts[sha] = int(count or 0)
    return counts
def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _cosine_similarity_local(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    n = min(len(vec_a), len(vec_b))
    if n <= 0:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(n):
        a = float(vec_a[i])
        b = float(vec_b[i])
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    denom = (norm_a ** 0.5) * (norm_b ** 0.5)
    if denom <= 0:
        return 0.0
    return dot / denom


def _read_text_if_file(path, max_chars: int) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except Exception:
        return None


async def _read_text_if_file_async(path, max_chars: int) -> str | None:
    return await asyncio.to_thread(_read_text_if_file, path, max_chars)


async def _resolve_under_root_async(root, rel_path: str, *, max_length: int):
    return await asyncio.to_thread(
        resolve_under_root,
        root,
        rel_path,
        max_length=max_length,
    )


async def _normalize_project_root_async(root_path: str) -> Path:
    return await asyncio.to_thread(
        normalize_project_root,
        root_path,
        max_length=settings.max_root_path_chars,
    )


def _resolve_and_read_text_under_root(
    root,
    rel_path: str,
    *,
    max_rel_path_length: int,
    max_chars: int,
) -> tuple[str, str] | None:
    try:
        abs_path, rel_norm = resolve_under_root(
            root,
            rel_path,
            max_length=max_rel_path_length,
        )
    except Exception:
        return None

    payload = _read_text_if_file(abs_path, max_chars)
    if not isinstance(payload, str):
        return None
    return rel_norm, payload


async def _resolve_and_read_text_under_root_async(
    root,
    rel_path: str,
    *,
    max_rel_path_length: int,
    max_chars: int,
) -> tuple[str, str] | None:
    return await asyncio.to_thread(
        _resolve_and_read_text_under_root,
        root,
        rel_path,
        max_rel_path_length=max_rel_path_length,
        max_chars=max_chars,
    )


async def _read_project_files_async(
    root,
    rel_paths: list[str],
    *,
    max_chars: int,
    max_parallel: int = 8,
) -> dict[str, str]:
    selected_paths = [p for p in rel_paths if isinstance(p, str) and p]
    if not selected_paths:
        return {}

    semaphore = asyncio.Semaphore(max(1, int(max_parallel)))

    async def _load_one(rel_path: str) -> tuple[str, str] | None:
        async with semaphore:
            return await _resolve_and_read_text_under_root_async(
                root,
                rel_path,
                max_rel_path_length=settings.max_rel_path_chars,
                max_chars=max_chars,
            )

    rows = await asyncio.gather(*[_load_one(path) for path in selected_paths])
    result: dict[str, str] = {}
    for row in rows:
        if not row:
            continue
        rel_norm, payload = row
        if rel_norm not in result:
            result[rel_norm] = payload
    return result


async def _resolve_project_paths_async(
    root,
    rel_paths: list[str],
    *,
    max_parallel: int = 16,
) -> dict[str, tuple[Path, str]]:
    selected_paths = [p for p in rel_paths if isinstance(p, str) and p]
    if not selected_paths:
        return {}

    semaphore = asyncio.Semaphore(max(1, int(max_parallel)))

    async def _resolve_one(rel_path: str) -> tuple[str, tuple[Path, str]] | None:
        async with semaphore:
            try:
                abs_path, rel_norm = await _resolve_under_root_async(
                    root,
                    rel_path,
                    max_length=settings.max_rel_path_chars,
                )
            except Exception:
                return None
        return rel_path, (abs_path, rel_norm)

    rows = await asyncio.gather(*[_resolve_one(path) for path in selected_paths])
    result: dict[str, tuple[Path, str]] = {}
    for row in rows:
        if row is None:
            continue
        rel_path, payload = row
        if rel_path not in result:
            result[rel_path] = payload
    return result




def _score_semantic_rows(
    rows,
    *,
    query_embedding: list[float],
    file_cache: dict[str, str],
    chunk_size: int,
    step: int,
) -> tuple[int, list[dict]]:
    compared = 0
    scored: list[dict] = []

    for row in rows:
        path, chunk_index, embedding_json, symbol_name, symbol_start_line, symbol_end_line = row
        if not isinstance(path, str) or not path:
            continue
        try:
            embedding = json.loads(embedding_json) if isinstance(embedding_json, str) else None
        except Exception:
            continue
        if not isinstance(embedding, list) or not embedding:
            continue
        try:
            score = _cosine_similarity_local(query_embedding, embedding)
        except Exception:
            continue
        compared += 1

        snippet = ""
        text = file_cache.get(path, "")
        if text:
            symbol_start = _as_int(symbol_start_line, 0)
            symbol_end = _as_int(symbol_end_line, 0)
            if symbol_start > 0 and symbol_end >= symbol_start:
                lines = text.splitlines(keepends=True)
                snippet = "".join(lines[symbol_start - 1 : symbol_end])
            else:
                start_pos = max(0, _as_int(chunk_index, 0) * step)
                end_pos = start_pos + chunk_size
                if start_pos < len(text):
                    snippet = text[start_pos:end_pos]

        scored.append(
            {
                "path": path,
                "score": float(score),
                "snippet": snippet,
                "symbol_name": str(symbol_name or ""),
                "symbol_line": _as_int(symbol_start_line, 0),
            }
        )

    return compared, scored


async def _score_semantic_rows_async(
    rows,
    *,
    query_embedding: list[float],
    file_cache: dict[str, str],
    chunk_size: int,
    step: int,
) -> tuple[int, list[dict]]:
    return await asyncio.to_thread(
        _score_semantic_rows,
        rows,
        query_embedding=query_embedding,
        file_cache=file_cache,
        chunk_size=chunk_size,
        step=step,
    )



def _find_text_matches_in_payload(
    payload: str,
    *,
    needle: str,
    needle_cmp: str,
    case_sensitive: bool,
    context_chars: int,
    limit_matches: int,
    start_count: int,
    truncated_flag: bool,
) -> tuple[list[dict], bool]:
    haystack = payload if case_sensitive else payload.lower()
    start_idx = 0
    found_any = False
    file_matches: list[dict] = []

    while True:
        if start_count + len(file_matches) >= limit_matches:
            break
        idx = haystack.find(needle_cmp, start_idx)
        if idx == -1:
            break
        found_any = True

        line = payload.count("\n", 0, idx) + 1
        last_nl = payload.rfind("\n", 0, idx)
        col = (idx - (last_nl + 1)) + 1 if last_nl != -1 else idx + 1

        half = max(10, context_chars // 2)
        s0 = max(0, idx - half)
        e0 = min(len(payload), idx + len(needle) + half)
        snippet = payload[s0:e0]

        file_matches.append(
            {
                "line": int(line),
                "col": int(col),
                "snippet": snippet,
                "truncated_file": bool(truncated_flag),
            }
        )

        step = max(1, len(needle_cmp))
        start_idx = idx + step

    return file_matches, found_any


async def _find_text_matches_in_payload_async(
    payload: str,
    *,
    needle: str,
    needle_cmp: str,
    case_sensitive: bool,
    context_chars: int,
    limit_matches: int,
    start_count: int,
    truncated_flag: bool,
) -> tuple[list[dict], bool]:
    return await asyncio.to_thread(
        _find_text_matches_in_payload,
        payload,
        needle=needle,
        needle_cmp=needle_cmp,
        case_sensitive=case_sensitive,
        context_chars=context_chars,
        limit_matches=limit_matches,
        start_count=start_count,
        truncated_flag=truncated_flag,
    )



def _build_graph_node_payload(nodes) -> tuple[list[dict], list[str]]:
    def risk_value(node) -> float:
        complexity = _as_float(getattr(node, "complexity", 0), 0.0)
        fan_in = _as_float(getattr(node, "fan_in", 0), 0.0)
        fan_out = _as_float(getattr(node, "fan_out", 0), 0.0)
        return (0.3 * complexity) + (0.7 * fan_in) + (0.1 * fan_out)

    node_payload: list[dict] = []
    node_paths: list[str] = []
    for node in nodes:
        path = node.path if isinstance(node.path, str) else ""
        if not path:
            continue
        node_paths.append(path)
        node_payload.append(
            {
                "id": path,
                "label": path.rsplit("/", 1)[-1],
                "path": path,
                "language": node.language,
                "loc": _as_int(getattr(node, "loc", 0), 0),
                "complexity": _as_float(getattr(node, "complexity", 0), 0.0),
                "fan_in": _as_int(getattr(node, "fan_in", 0), 0),
                "fan_out": _as_int(getattr(node, "fan_out", 0), 0),
                "scc_id": _as_int(getattr(node, "scc_id", -1), -1),
                "status": node.status,
                "risk": risk_value(node),
            }
        )
    return node_payload, node_paths


async def _build_graph_node_payload_async(nodes) -> tuple[list[dict], list[str]]:
    return await asyncio.to_thread(_build_graph_node_payload, nodes)


def _build_graph_edge_payload(
    edges,
    *,
    effective_limit: int | None,
    node_set: set[str],
) -> list[dict]:
    edge_payload: list[dict] = []
    for edge in edges:
        if not (
            isinstance(edge.src_path, str)
            and edge.src_path
            and isinstance(edge.dst_path, str)
            and edge.dst_path
        ):
            continue
        if effective_limit is not None and (
            edge.src_path not in node_set or edge.dst_path not in node_set
        ):
            continue
        edge_payload.append(
            {"source": edge.src_path, "target": edge.dst_path, "kind": edge.kind}
        )

    edge_payload.sort(key=lambda item: (item["source"], item["target"], item.get("kind") or ""))
    return edge_payload


async def _build_graph_edge_payload_async(
    edges,
    *,
    effective_limit: int | None,
    node_set: set[str],
) -> list[dict]:
    return await asyncio.to_thread(
        _build_graph_edge_payload,
        edges,
        effective_limit=effective_limit,
        node_set=node_set,
    )



def _build_local_graph_payload(
    node_rows,
    edge_set: set[tuple[str, str, str]],
    nodes_set: set[str],
) -> tuple[list[dict], list[dict]]:
    def risk_value(node: FileNode) -> float:
        complexity = _as_float(getattr(node, "complexity", 0), 0.0)
        fan_in = _as_float(getattr(node, "fan_in", 0), 0.0)
        fan_out = _as_float(getattr(node, "fan_out", 0), 0.0)
        return (0.3 * complexity) + (0.7 * fan_in) + (0.1 * fan_out)

    node_payload = [
        {
            "id": node.path,
            "label": node.path.rsplit("/", 1)[-1],
            "path": node.path,
            "language": node.language,
            "loc": _as_int(getattr(node, "loc", 0), 0),
            "complexity": _as_float(getattr(node, "complexity", 0), 0.0),
            "fan_in": _as_int(getattr(node, "fan_in", 0), 0),
            "fan_out": _as_int(getattr(node, "fan_out", 0), 0),
            "scc_id": _as_int(getattr(node, "scc_id", -1), -1),
            "status": node.status,
            "risk": risk_value(node),
        }
        for node in node_rows
    ]

    edge_payload = [
        {"source": s, "target": d, "kind": k}
        for s, d, k in edge_set
        if s in nodes_set and d in nodes_set
    ]
    return node_payload, edge_payload


async def _build_local_graph_payload_async(
    node_rows,
    edge_set: set[tuple[str, str, str]],
    nodes_set: set[str],
) -> tuple[list[dict], list[dict]]:
    return await asyncio.to_thread(_build_local_graph_payload, node_rows, edge_set, nodes_set)


def _build_project_files_payload(rows, *, limit: int) -> tuple[list[dict], bool, str | None]:
    def _risk(node: FileNode) -> float:
        return (
            (0.3 * _as_float(getattr(node, "complexity", 0), 0.0))
            + (0.7 * _as_float(getattr(node, "fan_in", 0), 0.0))
            + (0.1 * _as_float(getattr(node, "fan_out", 0), 0.0))
        )

    files = [
        {
            "path": node.path,
            "language": node.language,
            "loc": _as_int(getattr(node, "loc", 0), 0),
            "complexity": _as_int(getattr(node, "complexity", 0), 0),
            "fan_in": _as_int(getattr(node, "fan_in", 0), 0),
            "fan_out": _as_int(getattr(node, "fan_out", 0), 0),
            "status": node.status,
            "risk": _risk(node),
        }
        for node in rows
        if isinstance(node.path, str) and node.path
    ]

    truncated = len(files) > limit
    next_cursor = files[limit - 1]["path"] if truncated and limit > 0 else None
    return files[:limit], truncated, next_cursor


async def _build_project_files_payload_async(rows, *, limit: int) -> tuple[list[dict], bool, str | None]:
    return await asyncio.to_thread(_build_project_files_payload, rows, limit=limit)


def _build_project_tree_payload(
    rows,
    *,
    prefix_norm: str | None,
    limit: int,
    scan_limit: int,
    has_more_rows: bool,
) -> tuple[list[dict], str | None, bool]:
    entries: list[dict] = []
    seen: set[str] = set()
    last_consumed_path: str | None = None
    reached_limit = False
    has_next_unique_entry = False

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
                    "loc": _as_int(getattr(node, "loc", 0), 0),
                    "complexity": _as_int(getattr(node, "complexity", 0), 0),
                    "fan_in": _as_int(getattr(node, "fan_in", 0), 0),
                    "fan_out": _as_int(getattr(node, "fan_out", 0), 0),
                    "status": node.status,
                    "risk": (0.3 * _as_float(getattr(node, "complexity", 0), 0.0))
                    + (0.7 * _as_float(getattr(node, "fan_in", 0), 0.0))
                    + (0.1 * _as_float(getattr(node, "fan_out", 0), 0.0)),
                },
            }
        )

    scanned_rows = rows[:scan_limit]
    for row in scanned_rows:
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
        is_dir_entry = "/" in rel
        if is_dir_entry:
            name = rel.split("/", 1)[0]
            child_path = f"{prefix_norm}/{name}" if prefix_norm else name
            entry_key = child_path
        else:
            entry_key = path

        if len(entries) >= limit:
            reached_limit = True
            if entry_key in seen:
                last_consumed_path = path
                continue
            has_next_unique_entry = True
            break

        if is_dir_entry:
            add_dir(child_path, name)
        else:
            add_file(row)
        last_consumed_path = path

    if len(entries) >= limit:
        reached_limit = True

    truncated = reached_limit and (has_next_unique_entry or has_more_rows)
    return entries, last_consumed_path if truncated else None, bool(truncated)


async def _build_project_tree_payload_async(
    rows,
    *,
    prefix_norm: str | None,
    limit: int,
    scan_limit: int,
    has_more_rows: bool,
) -> tuple[list[dict], str | None, bool]:
    return await asyncio.to_thread(
        _build_project_tree_payload,
        rows,
        prefix_norm=prefix_norm,
        limit=limit,
        scan_limit=scan_limit,
        has_more_rows=has_more_rows,
    )


async def _get_active_scan_task_async(
    session: AsyncSession, project_id: int, org_id: int
) -> tuple[str | None, str | None]:
    idempotency_key = await get_scan_idempotency_key_async(org_id, project_id)
    job = (
        (
            await session.execute(
                select(TaskJob).where(
                    TaskJob.org_id == org_id,
                    TaskJob.idempotency_key == idempotency_key,
                    TaskJob.status.in_(("pending", "running")),
                )
            )
        )
        .scalars()
        .first()
    )
    if not job:
        return None, None
    return job.id, job.status


async def create_project_async(
    session: AsyncSession,
    name: str,
    root_path: str,
    org_id: int,
) -> Project:
    if not settings.allow_local_root_path:
        raise BadRequestError("Локальные root_path отключены. Используй загрузку snapshot.")
    root = await _normalize_project_root_async(root_path)
    project = Project(name=name, root_path=str(root), org_id=org_id)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def create_project_from_snapshot_async(
    session: AsyncSession,
    name: str,
    meta: SnapshotMeta,
    org_id: int,
) -> Project:
    root = await prepare_project_snapshot_root_async(meta)
    root = await _normalize_project_root_async(str(root))
    async with session.begin():
        project = Project(name=name, root_path=str(root), org_id=org_id)
        session.add(project)
        await session.flush()
        snapshot = RepoSnapshot(
            org_id=org_id,
            project_id=project.id,
            content_sha256=meta.sha256,
            archive_name=meta.archive_name,
            storage_json=json.dumps(asdict(meta), ensure_ascii=False),
        )
        session.add(snapshot)
    await session.refresh(project)
    return project


async def list_projects_async(session: AsyncSession, org_id: int) -> list[Project]:
    return list((await session.execute(select(Project).where(Project.org_id == org_id))).scalars().all())


async def get_latest_snapshots_async(
    session: AsyncSession, project_ids: list[int]
) -> dict[int, RepoSnapshot]:
    if not project_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(RepoSnapshot)
                .where(RepoSnapshot.project_id.in_(project_ids))
                .order_by(RepoSnapshot.project_id.asc(), RepoSnapshot.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    latest: dict[int, RepoSnapshot] = {}
    for row in rows:
        if row.project_id not in latest:
            latest[row.project_id] = row
    return latest


async def delete_project_async(session: AsyncSession, project_id: int, org_id: int) -> None:
    try:
        async with project_lock_async(session, project_id):
            project = (
                (
                    await session.execute(
                        select(Project).where(Project.id == project_id, Project.org_id == org_id)
                    )
                )
                .scalars()
                .first()
            )
            if not project:
                raise NotFoundError("Проект не найден", context={"project_id": project_id})
            project_root_path = project.root_path
            runs = list(
                (
                    await session.execute(select(AnalysisRun).where(AnalysisRun.project_id == project_id))
                )
                .scalars()
                .all()
            )
            snapshots = list(
                (
                    await session.execute(select(RepoSnapshot).where(RepoSnapshot.project_id == project_id))
                )
                .scalars()
                .all()
            )
            snapshot_payloads: list[tuple[RepoSnapshot, dict]] = []
            shas, parsed_snapshot_payloads = await _collect_delete_artifacts_async(runs, snapshots)
            snapshot_shas = {
                str(snap.content_sha256)
                for snap, _ in parsed_snapshot_payloads
                if isinstance(snap.content_sha256, str) and snap.content_sha256
            }
            shared_counts = await _load_snapshot_ref_counts_async(session, project_id, snapshot_shas)
            for snap, payload in parsed_snapshot_payloads:
                if int(shared_counts.get(str(snap.content_sha256), 0)) > 0:
                    continue
                snapshot_payloads.append((snap, payload))
            await session.execute(delete(FileEdge).where(FileEdge.project_id == project_id))
            await session.execute(delete(FileNode).where(FileNode.project_id == project_id))
            await session.execute(delete(ModuleContract).where(ModuleContract.project_id == project_id))
            await session.execute(delete(ApiRoute).where(ApiRoute.project_id == project_id))
            await session.execute(delete(ApiCall).where(ApiCall.project_id == project_id))
            await session.execute(delete(ApiInclude).where(ApiInclude.project_id == project_id))
            await session.execute(delete(ApiRouteContract).where(ApiRouteContract.project_id == project_id))
            await session.execute(delete(ApiCallMeta).where(ApiCallMeta.project_id == project_id))
            await session.execute(delete(TsTypeDef).where(TsTypeDef.project_id == project_id))
            await session.execute(delete(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id))
            await session.execute(
                delete(AnalysisStageTelemetry).where(AnalysisStageTelemetry.project_id == project_id)
            )
            await session.execute(delete(AnalysisRun).where(AnalysisRun.project_id == project_id))
            await session.execute(delete(ProjectDoc).where(ProjectDoc.project_id == project_id))
            await session.execute(delete(FileText).where(FileText.project_id == project_id))
            await session.execute(delete(RepoSnapshot).where(RepoSnapshot.project_id == project_id))
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.commit()
        cache_rows: list[tuple[list[str], dict]] = []
        try:
            await delete_project_snapshot_root_async(project_root_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Project snapshot root delete failed",
                extra={
                    "project_id": project_id,
                    "root_path": project_root_path,
                    "error": str(exc),
                },
            )
            cache_rows.append(
                (
                    ["project_delete_failed", "project_root", str(project_id)],
                    {"project_id": project_id, "root_path": project_root_path, "error": str(exc)},
                )
            )
        patch_errors, snapshot_errors = await _delete_project_artifacts_async(
            shas,
            snapshot_payloads,
        )
        for sha, exc in patch_errors:
            logger.warning(
                "Patch blob delete failed",
                extra={"project_id": project_id, "sha": sha, "error": str(exc)},
            )
            cache_rows.append(
                (
                    ["project_delete_failed", "patch", sha],
                    {"project_id": project_id, "sha": sha, "error": str(exc)},
                )
            )

        for snap, payload, exc in snapshot_errors:
            logger.warning(
                "Snapshot delete failed",
                extra={
                    "project_id": project_id,
                    "snapshot_sha": snap.content_sha256,
                    "archive_name": snap.archive_name,
                    "error": str(exc),
                },
            )
            cache_rows.append(
                (
                    ["project_delete_failed", "snapshot", snap.content_sha256],
                    {
                        "project_id": project_id,
                        "archive_name": snap.archive_name,
                        "storage": payload.get("storage"),
                        "error": str(exc),
                    },
                )
            )
        await _cache_project_delete_failures_async(cache_rows)
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc
    await cache_invalidate_prefix_async([f"project:{project_id}"])


async def list_project_files_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    prefix: str | None = None,
    cursor: str | None = None,
    limit: int = 50_000,
) -> dict:
    project = await session.get(Project, project_id)
    if not project or project.org_id != org_id:
        raise NotFoundError("Проект не найден", context={"project_id": project_id})
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

    base = select(FileNode).where(FileNode.project_id == project_id)
    count_q = select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
    if prefix_norm:
        like = f"{prefix_norm}/%"
        base = base.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
        count_q = count_q.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
    if cursor_norm:
        base = base.where(FileNode.path > cursor_norm)

    total_row = (await session.execute(count_q)).one()
    total = int(total_row[0] if isinstance(total_row, (tuple, list)) else total_row)
    rows = list((await session.execute(base.order_by(FileNode.path).limit(int(limit) + 1))).scalars().all())

    files, truncated, next_cursor = await _build_project_files_payload_async(rows, limit=limit)
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


async def list_project_tree_entries_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    prefix: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
) -> dict:
    project = await session.get(Project, project_id)
    if not project or project.org_id != org_id:
        raise NotFoundError("Проект не найден", context={"project_id": project_id})
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

    base = select(FileNode).where(FileNode.project_id == project_id)
    if prefix_norm:
        like = f"{prefix_norm}/%"
        base = base.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
    if cursor_norm:
        base = base.where(FileNode.path > cursor_norm)

    scan_limit = min(20000, max(limit * 40, limit + 1))
    rows = list((await session.execute(base.order_by(FileNode.path).limit(scan_limit + 1))).scalars().all())
    has_more_rows = len(rows) > scan_limit

    entries, next_cursor, truncated = await _build_project_tree_payload_async(
        rows,
        prefix_norm=prefix_norm,
        limit=limit,
        scan_limit=scan_limit,
        has_more_rows=has_more_rows,
    )
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


async def get_file_dependencies_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    path: str,
    limit: int = 2000,
    cursor_in: str | None = None,
    cursor_out: str | None = None,
) -> dict:
    project = await session.get(Project, project_id)
    if not project or project.org_id != org_id:
        raise NotFoundError("Проект не найден", context={"project_id": project_id})
    if not isinstance(path, str) or not path.strip():
        raise BadRequestError("path обязателен")
    if limit < 1 or limit > 20_000:
        raise BadRequestError("limit должен быть в диапазоне 1..20000")

    root = await _normalize_project_root_async(project.root_path)
    _, rel_norm = await _resolve_under_root_async(
        root,
        path,
        max_length=settings.max_rel_path_chars,
    )

    cursor_in_norm = (
        cursor_in.strip().replace("\\", "/") if isinstance(cursor_in, str) and cursor_in.strip() else None
    )
    cursor_out_norm = (
        cursor_out.strip().replace("\\", "/")
        if isinstance(cursor_out, str) and cursor_out.strip()
        else None
    )

    inbound_count = (
        await session.execute(
            select(func.count()).select_from(FileEdge).where(
                FileEdge.project_id == project_id,
                FileEdge.dst_path == rel_norm,
            )
        )
    ).one()
    outbound_count = (
        await session.execute(
            select(func.count()).select_from(FileEdge).where(
                FileEdge.project_id == project_id,
                FileEdge.src_path == rel_norm,
            )
        )
    ).one()

    inbound_value = inbound_count[0] if isinstance(inbound_count, (tuple, list)) else inbound_count
    outbound_value = outbound_count[0] if isinstance(outbound_count, (tuple, list)) else outbound_count
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

    inbound_rows = list((await session.execute(inbound_query.limit(limit + 1))).scalars().all())
    outbound_rows = list((await session.execute(outbound_query.limit(limit + 1))).scalars().all())

    inbound = [r for r in inbound_rows if isinstance(r, str)]
    outbound = [r for r in outbound_rows if isinstance(r, str)]

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


async def _scan_and_update_graph_async(
    project_id: int,
    org_id: int,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if not project or project.org_id != org_id:
            raise NotFoundError("Проект не найден", context={"project_id": project_id})

    root = await _normalize_project_root_async(project.root_path)
    stats = await asyncio.to_thread(scan_project, project_id, org_id, root)

    try:
        async with AsyncSessionLocal() as session:
            async with project_lock_async(session, project_id):
                metrics_pending = await compute_graph_metrics_async(
                    session,
                    project_id,
                    background_tasks=background_tasks,
                )
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc

    await cache_invalidate_prefix_async([f"project:{project_id}"])
    return {"ok": True, "stats": stats, "metrics_pending": bool(metrics_pending)}


async def scan_with_background_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    background: bool = False,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    _ = background
    task_id, status = await _get_active_scan_task_async(session, project_id, org_id)
    if task_id and status in ("pending", "running"):
        return {"task_id": task_id, "status": status}

    task_id = await submit_scan_async(project_id, org_id)
    if background_tasks is not None:
        background_tasks.add_task(lambda: None)
    return {"task_id": task_id, "status": "pending"}


async def load_graph_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    limit_nodes: int | None = None,
) -> dict:
    project = await session.get(Project, project_id)
    if not project or project.org_id != org_id:
        raise ForbiddenError("Нет доступа к проекту")

    auto_limit = 8000
    auto_return = 2000
    sqlite_in_chunk = 400

    total_nodes = _as_int(
        (
            await session.execute(
                select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
            )
        ).scalar_one(),
        0,
    )
    total_edges = _as_int(
        (
            await session.execute(
                select(func.count()).select_from(FileEdge).where(FileEdge.project_id == project_id)
            )
        ).scalar_one(),
        0,
    )

    truncated = False
    force_full = (limit_nodes is not None) and (_as_int(limit_nodes, 0) <= 0)
    effective_limit = None if force_full else limit_nodes

    if effective_limit is None and (not force_full) and total_nodes > auto_limit:
        effective_limit = auto_return
        truncated = True

    if effective_limit is not None and effective_limit <= 0:
        effective_limit = None

    risk_expr = (0.3 * FileNode.complexity) + (0.7 * FileNode.fan_in) + (0.1 * FileNode.fan_out)

    if effective_limit is None:
        nodes = (
            (await session.execute(select(FileNode).where(FileNode.project_id == project_id)))
            .scalars()
            .all()
        )
    else:
        nodes = (
            (
                await session.execute(
                    select(FileNode)
                    .where(FileNode.project_id == project_id)
                    .order_by(risk_expr.desc(), FileNode.path.asc())
                    .limit(int(effective_limit))
                )
            )
            .scalars()
            .all()
        )

    node_payload, node_paths = await _build_graph_node_payload_async(nodes)

    node_set = set(node_paths)
    edges: list[FileEdge] = []
    if effective_limit is None:
        edges = (
            (await session.execute(select(FileEdge).where(FileEdge.project_id == project_id)))
            .scalars()
            .all()
        )
    elif node_paths:
        for i in range(0, len(node_paths), sqlite_in_chunk):
            chunk = node_paths[i : i + sqlite_in_chunk]
            rows = (
                (
                    await session.execute(
                        select(FileEdge).where(
                            FileEdge.project_id == project_id,
                            FileEdge.src_path.in_(chunk),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for edge in rows:
                dst = edge.dst_path if isinstance(edge.dst_path, str) else ""
                if dst and dst in node_set:
                    edges.append(edge)

    edge_payload = await _build_graph_edge_payload_async(
        edges,
        effective_limit=effective_limit,
        node_set=node_set,
    )

    if effective_limit is not None and total_nodes > int(effective_limit):
        truncated = True

    meta = {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "returned_nodes": len(node_payload),
        "returned_edges": len(edge_payload),
        "truncated": bool(truncated),
        "limit_nodes": (effective_limit if effective_limit is not None else 0),
        "auto_limit_threshold": auto_limit,
    }

    return {"nodes": node_payload, "edges": edge_payload, "meta": meta}


async def load_local_graph_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    path: str,
    hops: int,
    max_nodes: int,
    max_edges: int,
) -> dict:
    project = await session.get(Project, project_id)
    if not project or project.org_id != org_id:
        raise ForbiddenError("Нет доступа к проекту")
    if hops < 0:
        raise BadRequestError("Количество шагов не может быть отрицательным")
    if max_nodes <= 0 or max_edges <= 0:
        raise BadRequestError("Лимиты графа должны быть положительными")

    root = await _normalize_project_root_async(project.root_path)
    _, rel_norm = await _resolve_under_root_async(
        root,
        path,
        max_length=settings.max_rel_path_chars,
    )

    hops_eff = max(0, min(hops, 6))
    max_nodes_eff = max(1, max_nodes)
    max_edges_eff = max(0, max_edges)
    sqlite_in_chunk = 400

    center = (
        (
            await session.execute(
                select(FileNode).where(FileNode.project_id == project_id, FileNode.path == rel_norm)
            )
        )
        .scalars()
        .first()
    )
    if not center:
        return {"nodes": [], "edges": [], "meta": {"center": rel_norm, "found": False}}

    nodes_set: set[str] = {rel_norm}
    edge_set: set[tuple[str, str, str]] = set()
    frontier: list[str] = [rel_norm]

    for _ in range(hops_eff):
        if not frontier or len(nodes_set) >= max_nodes_eff:
            break
        nxt: list[str] = []
        frontier = list(dict.fromkeys(frontier))
        for i in range(0, len(frontier), sqlite_in_chunk):
            chunk = frontier[i : i + sqlite_in_chunk]
            rows = (
                await session.execute(
                    select(FileEdge.src_path, FileEdge.dst_path, FileEdge.kind).where(
                        FileEdge.project_id == project_id,
                        (FileEdge.src_path.in_(chunk)) | (FileEdge.dst_path.in_(chunk)),
                    )
                )
            ).all()
            for src, dst, kind in rows:
                src_val = src if isinstance(src, str) else ""
                dst_val = dst if isinstance(dst, str) else ""
                kind_val = kind if isinstance(kind, str) else ""
                if src_val and dst_val and max_edges_eff > 0 and len(edge_set) < max_edges_eff:
                    edge_set.add((src_val, dst_val, kind_val))
                for neighbor in (src_val, dst_val):
                    if neighbor and neighbor not in nodes_set and len(nodes_set) < max_nodes_eff:
                        nodes_set.add(neighbor)
                        nxt.append(neighbor)
        frontier = nxt

    node_rows = (
        (
            await session.execute(
                select(FileNode)
                .where(FileNode.project_id == project_id, FileNode.path.in_(list(nodes_set)))
                .order_by(FileNode.path)
            )
        )
        .scalars()
        .all()
    )

    node_payload, edge_payload = await _build_local_graph_payload_async(
        node_rows,
        edge_set,
        nodes_set,
    )

    truncated_edges = bool(max_edges_eff > 0 and len(edge_set) >= max_edges_eff)
    meta = {
        "center": rel_norm,
        "found": True,
        "hops": hops_eff,
        "returned_nodes": len(node_payload),
        "returned_edges": len(edge_payload),
        "truncated": len(nodes_set) >= max_nodes_eff or truncated_edges,
    }
    return {"nodes": node_payload, "edges": edge_payload, "meta": meta}


async def search_project_nodes_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    query: str,
    limit: int = 20,
) -> list[dict]:
    project = await session.get(Project, project_id)
    if not project or project.org_id != org_id:
        raise ForbiddenError("Нет доступа к проекту")
    if not isinstance(query, str) or not query.strip():
        raise BadRequestError("Параметр q обязателен")
    if limit < 1 or limit > 200:
        raise BadRequestError("Лимит выдачи должен быть между 1 и 200")

    cache_key = [f"project:{project_id}", "search_nodes", query.strip(), str(limit)]
    cached = await cache_get_json_async(cache_key)
    if isinstance(cached, list):
        return cached

    pattern = f"%{query.strip()}%"
    rows = (
        await session.execute(
            select(FileNode.path, FileNode.language, FileNode.fan_in, FileNode.fan_out)
            .where(FileNode.project_id == project_id, FileNode.path.like(pattern))
            .order_by(FileNode.path)
            .limit(limit)
        )
    ).all()

    result: list[dict] = []
    for row in rows:
        if isinstance(row, (tuple, list)):
            path, lang, fan_in, fan_out = row[0], row[1], row[2], row[3]
        else:
            path = getattr(row, "path", "")
            lang = getattr(row, "language", "")
            fan_in = getattr(row, "fan_in", 0)
            fan_out = getattr(row, "fan_out", 0)
        if not isinstance(path, str) or not path:
            continue
        result.append(
            {
                "path": path,
                "language": lang,
                "fan_in": int(fan_in or 0),
                "fan_out": int(fan_out or 0),
            }
        )

    await cache_set_json_async(cache_key, result)
    return result


async def search_project_semantic_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    query: str,
    *,
    limit: int = 20,
    prefix: str | None = None,
) -> dict:
    project = await session.get(Project, project_id)
    if not project or project.org_id != org_id:
        raise ForbiddenError("Нет доступа к проекту")
    if not isinstance(query, str) or not query.strip():
        raise BadRequestError("Параметр q обязателен")
    if limit < 1 or limit > 200:
        raise BadRequestError("Лимит выдачи должен быть между 1 и 200")

    ent_embeddings_enabled = await get_entitlement_bool_async(session, org_id, "embeddings_enabled")
    usage_enabled = settings.embeddings_enabled and ent_embeddings_enabled is not False
    query_limit: int | None = None
    if usage_enabled:
        query_limit = await get_entitlement_int_async(
            session,
            org_id,
            "embeddings_daily_query_limit",
        )
        await check_usage_limit_async(
            session,
            org_id,
            EMBEDDING_QUERY_KIND,
            1,
            query_limit if query_limit is not None else settings.embeddings_daily_query_limit,
        )
    elif ent_embeddings_enabled is False:
        raise ForbiddenError("Семантический поиск недоступен по плану")

    if not bool(getattr(settings, "embeddings_enabled", False)):
        raise BadRequestError("Embeddings are disabled in settings.", context={"reason": "embeddings_disabled"})
    if not settings.openai_api_key:
        raise BadRequestError("OPENAI_API_KEY is not configured.", context={"reason": "missing_api_key"})

    root = await _normalize_project_root_async(project.root_path)
    q = query.strip()

    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    max_candidates = int(getattr(settings, "embeddings_search_max_candidates", 500))
    max_results_eff = int(getattr(settings, "embeddings_search_max_results", 20))
    max_results_eff = min(max_results_eff, max(1, int(limit)))

    filters = [FileChunkEmbedding.project_id == project_id]
    if prefix_norm:
        like = f"{prefix_norm}/%"
        filters.append((FileChunkEmbedding.path == prefix_norm) | (FileChunkEmbedding.path.like(like)))

    total_candidates = int(
        (
            await session.execute(select(func.count()).select_from(FileChunkEmbedding).where(*filters))
        ).scalar_one()
    )
    if total_candidates == 0:
        raise BadRequestError(
            "No embeddings found for this project. Please rescan the project with embeddings enabled.",
            context={"reason": "no_embeddings"},
        )

    rows = (
        await session.execute(
            select(
                FileChunkEmbedding.path,
                FileChunkEmbedding.chunk_index,
                FileChunkEmbedding.embedding_json,
                FileChunkEmbedding.symbol_name,
                FileChunkEmbedding.symbol_start_line,
                FileChunkEmbedding.symbol_end_line,
            )
            .where(*filters)
            .order_by(FileChunkEmbedding.path.asc(), FileChunkEmbedding.chunk_index.asc())
            .limit(int(max_candidates))
        )
    ).all()

    try:
        client = get_async_openai_client()
        resp = await client.embeddings.create(model=settings.embeddings_model, input=[q])
    except Exception as e:  # noqa: BLE001
        raise BadRequestError("Failed to get embedding", context={"reason": str(e)})

    data = getattr(resp, "data", None) or []
    if not data:
        raise BadRequestError("Embedding response is empty.", context={"reason": "embedding_empty"})

    query_embedding = getattr(data[0], "embedding", None)
    if not isinstance(query_embedding, list) or not query_embedding:
        raise BadRequestError("Embedding vector is missing.", context={"reason": "embedding_empty"})

    candidate_paths: list[str] = []
    seen_candidate_paths: set[str] = set()
    for row in rows:
        path = row[0] if isinstance(row, (tuple, list)) else None
        if isinstance(path, str) and path and path not in seen_candidate_paths:
            seen_candidate_paths.add(path)
            candidate_paths.append(path)

    file_cache = await _read_project_files_async(
        root,
        candidate_paths,
        max_chars=int(settings.embeddings_max_file_chars),
    )

    chunk_size = int(settings.embeddings_chunk_size)
    overlap = int(settings.embeddings_chunk_overlap)
    step = max(1, chunk_size - overlap)

    compared, scored = await _score_semantic_rows_async(
        rows,
        query_embedding=query_embedding,
        file_cache=file_cache,
        chunk_size=chunk_size,
        step=step,
    )

    scored.sort(key=lambda item: item["score"], reverse=True)
    results = scored[:max_results_eff]
    truncated = total_candidates > max_candidates or len(scored) > max_results_eff

    response = {
        "query": q,
        "prefix": prefix_norm or "",
        "results": results,
        "meta": {
            "compared": int(compared),
            "total_candidates": int(total_candidates),
            "max_candidates": int(max_candidates),
            "max_results": int(max_results_eff),
            "returned": int(len(results)),
            "truncated": bool(truncated),
            "reason": "",
        },
    }

    if usage_enabled:
        await check_and_increment_async(
            session,
            org_id,
            EMBEDDING_QUERY_KIND,
            1,
            query_limit if query_limit is not None else settings.embeddings_daily_query_limit,
        )
    return response


async def search_project_text_async(
    session: AsyncSession,
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
    project = await session.get(Project, project_id)
    if not project or project.org_id != org_id:
        raise ForbiddenError("Нет доступа к проекту")
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
    cached = await cache_get_json_async(cache_key)
    if isinstance(cached, dict):
        return cached

    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    row = (
        (await session.execute(select(FileNode.id).where(FileNode.project_id == project_id).limit(1)))
        .first()
    )
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
        await cache_set_json_async(cache_key, result)
        return result

    root = await _normalize_project_root_async(project.root_path)

    scan_max_chars = max(1, min(int(settings.llm_agentic_max_file_chars), 200_000))
    index_scan_max_chars = max(1, int(SEARCH_INDEX_MAX_CHARS))

    paths: list[str] = []
    try:
        paths = await search_text_paths_async(
            session,
            project_id,
            needle,
            limit=limit_files,
            prefix=prefix_norm,
        )
    except Exception:
        paths = []

    if not paths:
        q = select(FileNode.path).where(FileNode.project_id == project_id)
        if prefix_norm:
            like = f"{prefix_norm}/%"
            q = q.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
        q = q.order_by(FileNode.fan_in.desc(), FileNode.path.asc()).limit(int(limit_files))
        rows = (await session.execute(q)).all()
        for row in rows:
            rel_path = row[0] if isinstance(row, (tuple, list)) else row
            if isinstance(rel_path, str) and rel_path:
                paths.append(rel_path)

    needle_cmp = needle if case_sensitive else needle.lower()

    matches: list[dict] = []
    scanned = 0
    matched_files: set[str] = set()
    truncated_files = 0

    indexed_text: dict[str, str] = {}
    if paths:
        sqlite_in_chunk = 400
        for i in range(0, len(paths), sqlite_in_chunk):
            chunk = paths[i : i + sqlite_in_chunk]
            rows = (
                await session.execute(
                    select(FileText.path, FileText.content).where(
                        FileText.project_id == project_id,
                        FileText.path.in_(chunk),
                    )
                )
            ).all()
            for row in rows:
                if isinstance(row, (tuple, list)) and len(row) >= 2:
                    rel_path, content = row[0], row[1]
                else:
                    rel_path, content = None, None
                if isinstance(rel_path, str) and rel_path and isinstance(content, str):
                    indexed_text[rel_path] = content

    non_indexed_paths = [path for path in paths if path not in indexed_text]
    fs_text = await _read_project_files_async(
        root,
        non_indexed_paths,
        max_chars=int(scan_max_chars) + 1,
    )

    resolved_paths = await _resolve_project_paths_async(root, paths)

    async def _search_in_file(
        rel_candidate: str,
        remaining_limit: int,
    ) -> tuple[str, list[dict], bool] | None:
        resolved = resolved_paths.get(rel_candidate)
        if resolved is None:
            return None
        abs_path, rel_norm = resolved

        text_source = indexed_text.get(rel_norm)
        from_index = text_source is not None
        if text_source is None:
            text_source = fs_text.get(rel_norm)
            if text_source is None:
                return None

        effective_limit = max(1, min(int(remaining_limit), int(limit_matches)))
        truncated_initial = len(text_source) > scan_max_chars
        text_payload = text_source[:scan_max_chars] if truncated_initial else text_source
        truncated = truncated_initial
        file_matches, matched = await _find_text_matches_in_payload_async(
            text_payload,
            needle=needle,
            needle_cmp=needle_cmp,
            case_sensitive=case_sensitive,
            context_chars=context_chars,
            limit_matches=effective_limit,
            start_count=0,
            truncated_flag=truncated,
        )

        if truncated_initial and not matched and scan_max_chars < index_scan_max_chars:
            if from_index:
                text_payload = text_source[: int(index_scan_max_chars) + 1]
                truncated = len(text_payload) > index_scan_max_chars
                if truncated:
                    text_payload = text_payload[:index_scan_max_chars]
            else:
                text_payload = await _read_text_if_file_async(abs_path, int(index_scan_max_chars) + 1)
                if text_payload is None:
                    return None
                truncated = len(text_payload) > index_scan_max_chars
                if truncated:
                    text_payload = text_payload[:index_scan_max_chars]

            file_matches, _ = await _find_text_matches_in_payload_async(
                text_payload,
                needle=needle,
                needle_cmp=needle_cmp,
                case_sensitive=case_sensitive,
                context_chars=context_chars,
                limit_matches=effective_limit,
                start_count=0,
                truncated_flag=truncated,
            )

        return rel_norm, file_matches, truncated

    max_parallel = max(1, min(int(getattr(settings, "search_text_max_parallel", 16)), 128))
    for i in range(0, len(paths), max_parallel):
        if len(matches) >= limit_matches:
            break
        batch = paths[i : i + max_parallel]
        remaining_limit = limit_matches - len(matches)
        searched_rows = await asyncio.gather(
            *[_search_in_file(path, remaining_limit) for path in batch]
        )
        for row in searched_rows:
            if row is None:
                continue
            rel_norm, file_matches, truncated = row
            scanned += 1
            if truncated:
                truncated_files += 1
            if file_matches:
                matched_files.add(rel_norm)
                for item in file_matches:
                    matches.append(
                        {
                            "path": rel_norm,
                            "line": int(item.get("line") or 0),
                            "col": int(item.get("col") or 0),
                            "snippet": str(item.get("snippet") or ""),
                            "truncated_file": bool(item.get("truncated_file")),
                        }
                    )
                    if len(matches) >= limit_matches:
                        break
            if len(matches) >= limit_matches:
                break

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
    await cache_set_json_async(cache_key, result)
    return result
