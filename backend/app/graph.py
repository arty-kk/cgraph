# backend/app/graph.py
from __future__ import annotations

import asyncio
import json
import logging
import math
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks
import networkx as nx
from sqlalchemy import func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .config import settings
from .async_db import AsyncSessionLocal
from .llm.client import get_async_openai_client
from .infra.cpu_runtime import run_cpu_io_async
from .infra.external_io_runtime import run_openai_io_async
from .infra.fs_runtime import run_fs_io_async
from .models import FileChunkEmbedding, FileEdge, FileNode
from .utils import _chunk_text, resolve_under_root

logger = logging.getLogger(__name__)


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _should_defer_graph_metrics(node_count: int, edge_count: int) -> bool:
    max_nodes = _as_int(getattr(settings, "graph_metrics_async_node_threshold", 0), 0)
    max_edges = _as_int(getattr(settings, "graph_metrics_async_edge_threshold", 0), 0)
    if max_nodes <= 0 or max_edges <= 0:
        return False
    return node_count >= max_nodes or edge_count >= max_edges




async def _maybe_compute_graph_metrics_async(
    session: AsyncSession,
    project_id: int,
    background_tasks: BackgroundTasks | None,
) -> bool:
    node_count, edge_count = await _graph_counts_async(session, project_id)
    if background_tasks and _should_defer_graph_metrics(node_count, edge_count):
        background_tasks.add_task(_compute_graph_metrics_background_async, project_id)
        return True
    await compute_graph_metrics_async(session, project_id)
    return False


async def _graph_counts_async(session: AsyncSession, project_id: int) -> tuple[int, int]:
    node_count = _as_int(
        (
            await session.execute(
                select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
            )
        ).scalar_one(),
        0,
    )
    edge_count = _as_int(
        (
            await session.execute(
                select(func.count()).select_from(FileEdge).where(FileEdge.project_id == project_id)
            )
        ).scalar_one(),
        0,
    )
    return node_count, edge_count


async def _read_graph_metrics_input_async(
    session: AsyncSession,
    project_id: int,
    *,
    node_count: int,
    edge_count: int,
) -> dict[str, Any]:
    node_rows = (
        await session.execute(
            select(FileNode.id, FileNode.path).where(FileNode.project_id == project_id)
        )
    ).all()
    indeg_rows = (
        await session.execute(
            select(FileEdge.dst_path, func.count())
            .where(FileEdge.project_id == project_id)
            .group_by(FileEdge.dst_path)
        )
    ).all()
    outdeg_rows = (
        await session.execute(
            select(FileEdge.src_path, func.count())
            .where(FileEdge.project_id == project_id)
            .group_by(FileEdge.src_path)
        )
    ).all()

    compute_scc = bool(getattr(settings, "compute_scc", True))
    scc_max_nodes = _as_int(getattr(settings, "scc_max_nodes", 4000), 4000)
    scc_max_edges = _as_int(getattr(settings, "scc_max_edges", 20000), 20000)

    edge_rows: list[tuple[Any, Any]] = []
    if compute_scc and node_count <= scc_max_nodes and edge_count <= scc_max_edges:
        edge_rows = (
            await session.execute(
                select(FileEdge.src_path, FileEdge.dst_path).where(FileEdge.project_id == project_id)
            )
        ).all()

    return {
        "node_rows": [(nid, path) for nid, path in node_rows],
        "indeg_rows": [(p, c) for p, c in indeg_rows],
        "outdeg_rows": [(p, c) for p, c in outdeg_rows],
        "edge_rows": [(src, dst) for src, dst in edge_rows],
        "compute_scc": compute_scc,
        "scc_max_nodes": scc_max_nodes,
        "scc_max_edges": scc_max_edges,
    }


def _compute_graph_metrics_cpu(graph_input: dict[str, Any]) -> list[dict[str, int]]:
    node_rows = graph_input["node_rows"]
    indeg_rows = graph_input["indeg_rows"]
    outdeg_rows = graph_input["outdeg_rows"]
    edge_rows = graph_input["edge_rows"]

    indeg: dict[str, int] = {}
    for p, c in indeg_rows:
        if isinstance(p, str) and p:
            indeg[p] = _as_int(c, 0)

    outdeg: dict[str, int] = {}
    for p, c in outdeg_rows:
        if isinstance(p, str) and p:
            outdeg[p] = _as_int(c, 0)

    scc_map: dict[str, int] = {}
    if graph_input["compute_scc"]:
        node_count = len(node_rows)
        edge_count = len(edge_rows)
        if (
            node_count <= graph_input["scc_max_nodes"]
            and edge_count <= graph_input["scc_max_edges"]
        ):
            g = nx.DiGraph()
            for _nid, path in node_rows:
                if isinstance(path, str) and path:
                    g.add_node(path)
            for src, dst in edge_rows:
                if isinstance(src, str) and src and isinstance(dst, str) and dst:
                    g.add_edge(src, dst)
            for i, comp in enumerate(nx.strongly_connected_components(g)):
                for path in comp:
                    scc_map[path] = i

    params: list[dict[str, int]] = []
    for nid, path in node_rows:
        if nid is None or not isinstance(path, str) or not path:
            continue
        params.append(
            {
                "id": int(nid),
                "fan_in": _as_int(indeg.get(path, 0), 0),
                "fan_out": _as_int(outdeg.get(path, 0), 0),
                "scc_id": _as_int(scc_map.get(path, -1), -1),
            }
        )
    return params


async def _write_graph_metrics_async(session: AsyncSession, params: list[dict[str, int]]) -> None:
    if not params:
        return
    await session.execute(
        text("UPDATE filenode SET fan_in=:fan_in, fan_out=:fan_out, scc_id=:scc_id WHERE id=:id"),
        params,
    )
    await session.commit()


async def _compute_graph_metrics_background_async(project_id: int) -> None:
    async with AsyncSessionLocal() as session:
        await compute_graph_metrics_async(session, project_id)


async def compute_graph_metrics_async(
    session: AsyncSession,
    project_id: int,
    background_tasks: BackgroundTasks | None = None,
) -> bool:
    node_count, edge_count = await _graph_counts_async(session, project_id)
    if background_tasks and _should_defer_graph_metrics(node_count, edge_count):
        background_tasks.add_task(_compute_graph_metrics_background_async, project_id)
        return True

    graph_input = await _read_graph_metrics_input_async(
        session,
        project_id,
        node_count=node_count,
        edge_count=edge_count,
    )
    if not graph_input["node_rows"]:
        return False

    params = await run_cpu_io_async(
        _compute_graph_metrics_cpu,
        graph_input,
        operation="graph.compute_graph_metrics",
    )
    await _write_graph_metrics_async(session, params)
    return False


async def update_graph_metrics_incremental_async(
    session: AsyncSession,
    project_id: int,
    modified_paths: list[str],
    removed_edge_neighbors: list[str] | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> bool:
    normalized: list[str] = []
    seen: set[str] = set()
    for p in modified_paths:
        if not isinstance(p, str) or not p:
            continue
        if p in seen:
            continue
        seen.add(p)
        normalized.append(p)

    if not normalized:
        return False

    max_paths = _as_int(getattr(settings, "graph_metrics_incremental_max_paths", 200), 200)
    if len(normalized) > max_paths:
        return await _maybe_compute_graph_metrics_async(session, project_id, background_tasks)

    max_component_nodes = _as_int(
        getattr(settings, "graph_metrics_incremental_max_component_nodes", 2000), 2000
    )
    max_component_edges = _as_int(
        getattr(settings, "graph_metrics_incremental_max_component_edges", 5000), 5000
    )
    compute_scc = bool(getattr(settings, "compute_scc", True))

    SQLITE_IN_CHUNK = 400

    def _iter_chunks(seq: list[str], size: int):
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    async def _fetch_edges_for_paths(paths: list[str]) -> list[tuple[str, str]]:
        if not paths:
            return []
        edges: list[tuple[str, str]] = []
        for chunk in _iter_chunks(paths, SQLITE_IN_CHUNK):
            rows = (
                await session.execute(
                    select(FileEdge.src_path, FileEdge.dst_path).where(
                        FileEdge.project_id == project_id,
                        or_(FileEdge.src_path.in_(chunk), FileEdge.dst_path.in_(chunk)),
                    )
                )
            ).all()
            edges.extend(rows)
        return edges

    component_paths = set(normalized)
    component_edges: set[tuple[str, str]] = set()
    frontier = set(normalized)
    too_large = False

    while frontier:
        rows = await _fetch_edges_for_paths(list(frontier))
        next_frontier: set[str] = set()
        for src, dst in rows:
            if not (isinstance(src, str) and src and isinstance(dst, str) and dst):
                continue
            component_edges.add((src, dst))
            if src not in component_paths:
                component_paths.add(src)
                next_frontier.add(src)
            if dst not in component_paths:
                component_paths.add(dst)
                next_frontier.add(dst)
        if len(component_paths) > max_component_nodes or len(component_edges) > max_component_edges:
            too_large = True
            break
        frontier = next_frontier

    if too_large:
        return await _maybe_compute_graph_metrics_async(session, project_id, background_tasks)

    affected_paths = set(normalized)
    if removed_edge_neighbors:
        for path in removed_edge_neighbors:
            if isinstance(path, str) and path:
                affected_paths.add(path)
    for src, dst in await _fetch_edges_for_paths(normalized):
        if isinstance(src, str) and src:
            affected_paths.add(src)
        if isinstance(dst, str) and dst:
            affected_paths.add(dst)

    indeg: dict[str, int] = {}
    outdeg: dict[str, int] = {}

    affected_list = sorted(affected_paths)
    for chunk in _iter_chunks(affected_list, SQLITE_IN_CHUNK):
        indeg_rows = (
            await session.execute(
                select(FileEdge.dst_path, func.count())
                .where(FileEdge.project_id == project_id, FileEdge.dst_path.in_(chunk))
                .group_by(FileEdge.dst_path)
            )
        ).all()
        for p, c in indeg_rows:
            if isinstance(p, str) and p:
                indeg[p] = _as_int(c, 0)

        outdeg_rows = (
            await session.execute(
                select(FileEdge.src_path, func.count())
                .where(FileEdge.project_id == project_id, FileEdge.src_path.in_(chunk))
                .group_by(FileEdge.src_path)
            )
        ).all()
        for p, c in outdeg_rows:
            if isinstance(p, str) and p:
                outdeg[p] = _as_int(c, 0)

    normalized_list = sorted(normalized)
    if normalized_list:
        previous_rows = (
            await session.execute(
                select(FileNode.path, FileNode.fan_in, FileNode.fan_out).where(
                    FileNode.project_id == project_id,
                    FileNode.path.in_(normalized_list),
                )
            )
        ).all()
        existing_paths = {path for path, _, _ in previous_rows if isinstance(path, str) and path}
        if set(normalized_list) - existing_paths:
            return await _maybe_compute_graph_metrics_async(session, project_id, background_tasks)
        for path, fan_in, fan_out in previous_rows:
            if not isinstance(path, str) or not path:
                continue
            new_in = _as_int(indeg.get(path, 0), 0)
            new_out = _as_int(outdeg.get(path, 0), 0)
            if new_in < _as_int(fan_in, 0) or new_out < _as_int(fan_out, 0):
                return await _maybe_compute_graph_metrics_async(session, project_id, background_tasks)

    node_rows = (
        await session.execute(
            select(FileNode.id, FileNode.path).where(
                FileNode.project_id == project_id,
                FileNode.path.in_(affected_list),
            )
        )
    ).all()
    fan_params: list[dict[str, int]] = []
    for nid, path in node_rows:
        if nid is None or not isinstance(path, str) or not path:
            continue
        fan_params.append(
            {
                "id": int(nid),
                "fan_in": _as_int(indeg.get(path, 0), 0),
                "fan_out": _as_int(outdeg.get(path, 0), 0),
            }
        )
    if fan_params:
        await session.execute(
            text("UPDATE filenode SET fan_in=:fan_in, fan_out=:fan_out WHERE id=:id"),
            fan_params,
        )

    if compute_scc:
        g = nx.DiGraph()
        for path in component_paths:
            if isinstance(path, str) and path:
                g.add_node(path)
        for src, dst in component_edges:
            if src in component_paths and dst in component_paths:
                g.add_edge(src, dst)

        scc_map: dict[str, int] = {}
        sccs = list(nx.strongly_connected_components(g))
        for i, comp in enumerate(sccs):
            for p in comp:
                scc_map[p] = i

        component_list = sorted(component_paths)
        component_nodes = (
            await session.execute(
                select(FileNode.id, FileNode.path).where(
                    FileNode.project_id == project_id,
                    FileNode.path.in_(component_list),
                )
            )
        ).all()
        scc_params: list[dict[str, int]] = []
        for nid, path in component_nodes:
            if nid is None or not isinstance(path, str) or not path:
                continue
            scc_params.append({"id": int(nid), "scc_id": _as_int(scc_map.get(path, -1), -1)})
        if scc_params:
            await session.execute(
                text("UPDATE filenode SET scc_id=:scc_id WHERE id=:id"),
                scc_params,
            )

    await session.commit()
    return False





def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
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
    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom <= 0:
        return 0.0
    return dot / denom


def _score_semantic_candidates_cpu(
    rows: list[tuple[Any, ...]],
    *,
    query_embedding: list[float],
    file_cache: dict[str, str],
    chunk_size: int,
    overlap: int,
) -> tuple[int, list[dict[str, Any]]]:
    compared = 0
    scored: list[dict[str, Any]] = []

    step = max(1, chunk_size - overlap)

    for row in rows:
        if isinstance(row, (tuple, list)):
            path, chunk_index, embedding_json, symbol_name, symbol_start_line, symbol_end_line = (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
            )
        else:
            path = getattr(row, "path", "")
            chunk_index = getattr(row, "chunk_index", 0)
            embedding_json = getattr(row, "embedding_json", "")
            symbol_name = getattr(row, "symbol_name", "")
            symbol_start_line = getattr(row, "symbol_start_line", 0)
            symbol_end_line = getattr(row, "symbol_end_line", 0)
        if not isinstance(path, str) or not path:
            continue
        try:
            embedding = json.loads(embedding_json) if isinstance(embedding_json, str) else None
        except Exception:
            continue
        if not isinstance(embedding, list) or not embedding:
            continue
        try:
            score = _cosine_similarity(query_embedding, embedding)
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
                try:
                    start = max(0, int(chunk_index) * step)
                except Exception:
                    start = 0
                end = start + chunk_size
                if start < len(text):
                    snippet = text[start:end]
                else:
                    chunks = _chunk_text(text, chunk_size, overlap)
                    if isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks):
                        snippet = chunks[chunk_index]

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


def _resolve_and_read_semantic_candidate_file(
    root: Path,
    rel_path: str,
    *,
    max_rel_path_length: int,
    max_chars: int,
) -> tuple[str, str] | None:
    try:
        abs_path, _rel_norm = resolve_under_root(root, rel_path, max_length=max_rel_path_length)
    except Exception:
        return rel_path, ""
    if not abs_path.exists() or not abs_path.is_file():
        return rel_path, ""
    try:
        with abs_path.open("r", encoding="utf-8", errors="replace") as f:
            payload = f.read(max_chars)
    except Exception:
        payload = ""
    return rel_path, payload if isinstance(payload, str) else ""


async def read_semantic_candidate_files_async(
    root: Path,
    rel_paths: list[str],
    *,
    max_parallel: int,
    max_rel_path_length: int,
    max_chars: int,
) -> dict[str, str]:
    selected_paths: list[str] = []
    seen: set[str] = set()
    for path in rel_paths:
        if not isinstance(path, str) or not path or path in seen:
            continue
        seen.add(path)
        selected_paths.append(path)
    if not selected_paths:
        return {}

    semaphore = asyncio.Semaphore(max(1, int(max_parallel)))

    async def _load_one(path: str) -> tuple[str, str] | None:
        async with semaphore:
            return await run_fs_io_async(
                _resolve_and_read_semantic_candidate_file,
                root,
                path,
                max_rel_path_length=max_rel_path_length,
                max_chars=max_chars,
                operation="graph.semantic.read_candidate",
            )

    rows = await asyncio.gather(*[_load_one(path) for path in selected_paths])
    file_cache: dict[str, str] = {}
    for row in rows:
        if row is None:
            continue
        path, payload = row
        if path not in file_cache:
            file_cache[path] = payload if isinstance(payload, str) else ""
    return file_cache


async def search_semantic_async(
    session: AsyncSession,
    project_id: int,
    root: Path,
    query: str,
    *,
    max_results: int | None = None,
    prefix: str | None = None,
) -> dict:
    if not isinstance(query, str) or not query.strip():
        return {"error": "bad_args", "message": "query is required", "meta": {"reason": "bad_args"}}

    if not bool(getattr(settings, "embeddings_enabled", False)):
        return {
            "error": "embeddings_disabled",
            "message": "Embeddings are disabled in settings.",
            "meta": {"reason": "embeddings_disabled"},
        }

    if not settings.openai_api_key:
        return {
            "error": "missing_api_key",
            "message": "OPENAI_API_KEY is not configured.",
            "meta": {"reason": "missing_api_key"},
        }

    q = query.strip()
    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    max_candidates = int(getattr(settings, "embeddings_search_max_candidates", 500))
    max_results_eff = int(getattr(settings, "embeddings_search_max_results", 20))
    if max_results is not None:
        try:
            max_results_eff = min(max_results_eff, max(1, int(max_results)))
        except Exception:
            max_results_eff = max_results_eff

    filters = [FileChunkEmbedding.project_id == project_id]
    if prefix_norm:
        like = f"{prefix_norm}/%"
        filters.append((FileChunkEmbedding.path == prefix_norm) | (FileChunkEmbedding.path.like(like)))

    total_candidates = _as_int(
        (
            await session.execute(select(func.count()).select_from(FileChunkEmbedding).where(*filters))
        ).scalar_one(),
        0,
    )
    if total_candidates == 0:
        return {
            "error": "embeddings_empty",
            "message": (
                "No embeddings found for this project. "
                "Please rescan the project with embeddings enabled."
            ),
            "meta": {"reason": "no_embeddings"},
        }

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
        async with asyncio.timeout(float(settings.openai_timeout_seconds)):
            resp = await run_openai_io_async(
                lambda: client.embeddings.create(model=settings.embeddings_model, input=[q]),
                kind="short",
            )
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        return {
            "error": "embedding_failed",
            "message": f"Failed to get embedding: {e}",
            "meta": {"reason": "embedding_failed"},
        }

    data = getattr(resp, "data", None) or []
    if not data:
        return {
            "error": "embedding_empty",
            "message": "Embedding response is empty.",
            "meta": {"reason": "embedding_empty"},
        }

    query_embedding = getattr(data[0], "embedding", None)
    if not isinstance(query_embedding, list) or not query_embedding:
        return {
            "error": "embedding_empty",
            "message": "Embedding vector is missing.",
            "meta": {"reason": "embedding_empty"},
        }

    candidate_paths: list[str] = []
    seen_candidate_paths: set[str] = set()
    for row in rows:
        path = row[0] if isinstance(row, (tuple, list)) else getattr(row, "path", "")
        if not isinstance(path, str) or not path or path in seen_candidate_paths:
            continue
        seen_candidate_paths.add(path)
        candidate_paths.append(path)

    file_cache = await read_semantic_candidate_files_async(
        root,
        candidate_paths,
        max_parallel=8,
        max_rel_path_length=int(settings.max_rel_path_chars),
        max_chars=int(settings.embeddings_max_file_chars),
    )

    compared, scored = await run_cpu_io_async(
        _score_semantic_candidates_cpu,
        rows,
        query_embedding=query_embedding,
        file_cache=file_cache,
        chunk_size=int(settings.embeddings_chunk_size),
        overlap=int(settings.embeddings_chunk_overlap),
        operation="graph.score_semantic_candidates",
    )

    scored.sort(key=lambda x: x["score"], reverse=True)
    results = scored[:max_results_eff]
    truncated = total_candidates > max_candidates or len(scored) > max_results_eff
    if truncated:
        logger.info(
            "Semantic search truncated results for project %s (candidates=%s, returned=%s).",
            project_id,
            max_candidates,
            max_results_eff,
        )

    return {
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
