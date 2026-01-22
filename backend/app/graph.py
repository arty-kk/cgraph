#backend/app/graph.py
from __future__ import annotations

from typing import Any
from pathlib import Path
import json
import logging
import math
from sqlmodel import select
from sqlalchemy import text, func
from .db import get_session
from .models import FileNode, FileEdge, FileChunkEmbedding
from .config import settings
from .llm.client import get_openai_client
from .utils import resolve_under_root
import networkx as nx

logger = logging.getLogger(__name__)

def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default

def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default

def compute_graph_metrics(project_id: int) -> None:
    with get_session() as s:
        node_rows = s.exec(select(FileNode.id, FileNode.path).where(FileNode.project_id == project_id)).all()
        if not node_rows:
            return

        indeg_rows = s.exec(
            select(FileEdge.dst_path, func.count())
            .where(FileEdge.project_id == project_id)
            .group_by(FileEdge.dst_path)
        ).all()
        outdeg_rows = s.exec(
            select(FileEdge.src_path, func.count())
            .where(FileEdge.project_id == project_id)
            .group_by(FileEdge.src_path)
        ).all()
 
        indeg: dict[str, int] = {}
        for p, c in indeg_rows:
            if isinstance(p, str) and p:
                indeg[p] = _as_int(c, 0)

        outdeg: dict[str, int] = {}
        for p, c in outdeg_rows:
            if isinstance(p, str) and p:
                outdeg[p] = _as_int(c, 0)

        scc_map: dict[str, int] = {}
        compute_scc = bool(getattr(settings, "compute_scc", True))
        max_nodes = _as_int(getattr(settings, "scc_max_nodes", 4000), 4000)
        max_edges = _as_int(getattr(settings, "scc_max_edges", 20000), 20000)

        if compute_scc:
            edge_count_row = s.exec(
                select(func.count()).select_from(FileEdge).where(FileEdge.project_id == project_id)
            ).one()
            if isinstance(edge_count_row, (tuple, list)):
                edge_count_val = edge_count_row[0] if edge_count_row else 0
            else:
                try:
                    edge_count_val = edge_count_row[0]
                except Exception:
                    edge_count_val = edge_count_row
            edge_count_int = _as_int(edge_count_val, 0)

            node_count_int = len(node_rows)
            if node_count_int <= max_nodes and edge_count_int <= max_edges:
                edge_rows = s.exec(
                    select(FileEdge.src_path, FileEdge.dst_path).where(FileEdge.project_id == project_id)
                ).all()
                g = nx.DiGraph()
                for _nid, path in node_rows:
                    if isinstance(path, str) and path:
                        g.add_node(path)
                for src, dst in edge_rows:
                    if isinstance(src, str) and src and isinstance(dst, str) and dst:
                        g.add_edge(src, dst)

                sccs = list(nx.strongly_connected_components(g))
                for i, comp in enumerate(sccs):
                    for p in comp:
                        scc_map[p] = i
            else:
                scc_map = {}

        params: list[dict] = []
        for nid, path in node_rows:
            if nid is None:
                continue
            p = path if isinstance(path, str) else ""
            if not p:
                continue
            params.append({
                "id": int(nid),
                "fan_in": _as_int(indeg.get(p, 0), 0),
                "fan_out": _as_int(outdeg.get(p, 0), 0),
                "scc_id": _as_int(scc_map.get(p, -1), -1),
            })

        if params:
            s.execute(
                text("UPDATE filenode SET fan_in=:fan_in, fan_out=:fan_out, scc_id=:scc_id WHERE id=:id"),
                params,
            )
            s.commit()

def graph_payload(project_id: int, limit_nodes: int | None = None) -> dict:

    AUTO_LIMIT = 8000
    AUTO_RETURN = 2000
    SQLITE_IN_CHUNK = 400

    with get_session() as s:
        total_nodes_row = s.exec(
            select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
        ).one()
        if isinstance(total_nodes_row, (tuple, list)):
            total_nodes = _as_int(total_nodes_row[0] if total_nodes_row else 0, 0)
        else:
            try:
                total_nodes = _as_int(total_nodes_row[0], 0)  # type: ignore[index]
            except Exception:
                total_nodes = _as_int(total_nodes_row, 0)

        total_edges_row = s.exec(
            select(func.count()).select_from(FileEdge).where(FileEdge.project_id == project_id)
        ).one()
        if isinstance(total_edges_row, (tuple, list)):
            total_edges = _as_int(total_edges_row[0] if total_edges_row else 0, 0)
        else:
            try:
                total_edges = _as_int(total_edges_row[0], 0)  # type: ignore[index]
            except Exception:
                total_edges = _as_int(total_edges_row, 0)

        truncated = False
        force_full = (limit_nodes is not None) and (_as_int(limit_nodes, 0) <= 0)
        effective_limit = None if force_full else limit_nodes

        if effective_limit is None and (not force_full) and total_nodes > AUTO_LIMIT:
            effective_limit = AUTO_RETURN
            truncated = True

        if effective_limit is not None and effective_limit <= 0:
            effective_limit = None
            force_full = True

        def risk_value(n: FileNode) -> float:
            complexity = _as_float(getattr(n, "complexity", 0), 0.0)
            fan_in = _as_float(getattr(n, "fan_in", 0), 0.0)
            fan_out = _as_float(getattr(n, "fan_out", 0), 0.0)
            return (0.3 * complexity) + (0.7 * fan_in) + (0.1 * fan_out)

        risk_expr = (0.3 * FileNode.complexity) + (0.7 * FileNode.fan_in) + (0.1 * FileNode.fan_out)

        if effective_limit is None:
            nodes = s.exec(select(FileNode).where(FileNode.project_id == project_id)).all()
        else:
            nodes = s.exec(
                select(FileNode)
                .where(FileNode.project_id == project_id)
                .order_by(risk_expr.desc(), FileNode.path.asc())
                .limit(int(effective_limit))
            ).all()

        node_payload: list[dict] = []
        node_paths: list[str] = []
        for n in nodes:
            path = n.path if isinstance(n.path, str) else ""
            if not path:
                continue
            node_paths.append(path)
            label = path.rsplit("/", 1)[-1]
            node_payload.append({
                "id": path,
                "label": label,
                "path": path,
                "language": n.language,
                "loc": _as_int(getattr(n, "loc", 0), 0),
                "complexity": _as_float(getattr(n, "complexity", 0), 0.0),
                "fan_in": _as_int(getattr(n, "fan_in", 0), 0),
                "fan_out": _as_int(getattr(n, "fan_out", 0), 0),
                "scc_id": _as_int(getattr(n, "scc_id", -1), -1),
                "status": n.status,
                "risk": risk_value(n),
            })

        node_set = set(node_paths)

        if effective_limit is None:
            edges = s.exec(select(FileEdge).where(FileEdge.project_id == project_id)).all()
        else:
            edges = []
            if node_paths:
                def _iter_chunks(seq: list[str], size: int):
                    for i in range(0, len(seq), size):
                        yield seq[i : i + size]

                for chunk in _iter_chunks(node_paths, SQLITE_IN_CHUNK):
                    rows = s.exec(
                        select(FileEdge).where(
                            FileEdge.project_id == project_id,
                            FileEdge.src_path.in_(chunk),
                        )
                    ).all()
                    for e in rows:
                        dst = e.dst_path if isinstance(e.dst_path, str) else ""
                        if dst and dst in node_set:
                            edges.append(e)

    edge_payload: list[dict] = []
    for e in edges:
        if not (isinstance(e.src_path, str) and e.src_path and isinstance(e.dst_path, str) and e.dst_path):
            continue
        if effective_limit is not None:
            if e.src_path not in node_set or e.dst_path not in node_set:
                continue
        edge_payload.append({"source": e.src_path, "target": e.dst_path, "kind": e.kind})

    edge_payload.sort(key=lambda x: (x["source"], x["target"], x.get("kind") or ""))

    if effective_limit is not None and total_nodes > int(effective_limit):
        truncated = True

    meta = {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "returned_nodes": len(node_payload),
        "returned_edges": len(edge_payload),
        "truncated": bool(truncated),
        "limit_nodes": (effective_limit if effective_limit is not None else 0),
        "auto_limit_threshold": AUTO_LIMIT,
    }

    return {"nodes": node_payload, "edges": edge_payload, "meta": meta}


def local_subgraph(
    project_id: int,
    center_path: str,
    hops: int = 1,
    max_nodes: int = 400,
    max_edges: int = 800,
) -> dict:
    hops = max(0, min(hops, 6))
    max_nodes = max(1, max_nodes)
    max_edges = max(0, max_edges)
    SQLITE_IN_CHUNK = 400

    with get_session() as s:
        center = s.exec(
            select(FileNode).where(FileNode.project_id == project_id, FileNode.path == center_path)
        ).first()
        if not center:
            return {"nodes": [], "edges": [], "meta": {"center": center_path, "found": False}}

        nodes_set: set[str] = {center_path}
        edge_set: set[tuple[str, str, str]] = set()
        frontier: list[str] = [center_path]

        def _iter_chunks(seq: list[str], size: int):
            for i in range(0, len(seq), size):
                yield seq[i : i + size]

        for _ in range(hops):
            if not frontier or len(nodes_set) >= max_nodes:
                break
            nxt: list[str] = []
            frontier = list(dict.fromkeys(frontier))
            for chunk in _iter_chunks(frontier, SQLITE_IN_CHUNK):
                rows = s.exec(
                    select(FileEdge.src_path, FileEdge.dst_path, FileEdge.kind)
                    .where(
                        FileEdge.project_id == project_id,
                        (FileEdge.src_path.in_(chunk)) | (FileEdge.dst_path.in_(chunk)),
                    )
                ).all()
                for src, dst, kind in rows:
                    src_val = src if isinstance(src, str) else ""
                    dst_val = dst if isinstance(dst, str) else ""
                    kind_val = kind if isinstance(kind, str) else ""
                    if src_val and dst_val and max_edges > 0 and len(edge_set) < max_edges:
                        edge_set.add((src_val, dst_val, kind_val))
                    for neighbor in (src_val, dst_val):
                        if neighbor and neighbor not in nodes_set and len(nodes_set) < max_nodes:
                            nodes_set.add(neighbor)
                            nxt.append(neighbor)
            frontier = nxt

        node_rows = s.exec(
            select(FileNode)
            .where(FileNode.project_id == project_id, FileNode.path.in_(list(nodes_set)))
            .order_by(FileNode.path)
        ).all()

    def risk_value(n: FileNode) -> float:
        complexity = _as_float(getattr(n, "complexity", 0), 0.0)
        fan_in = _as_float(getattr(n, "fan_in", 0), 0.0)
        fan_out = _as_float(getattr(n, "fan_out", 0), 0.0)
        return (0.3 * complexity) + (0.7 * fan_in) + (0.1 * fan_out)

    node_payload = [
        {
            "id": n.path,
            "label": n.path.rsplit("/", 1)[-1],
            "path": n.path,
            "language": n.language,
            "loc": _as_int(getattr(n, "loc", 0), 0),
            "complexity": _as_float(getattr(n, "complexity", 0), 0.0),
            "fan_in": _as_int(getattr(n, "fan_in", 0), 0),
            "fan_out": _as_int(getattr(n, "fan_out", 0), 0),
            "scc_id": _as_int(getattr(n, "scc_id", -1), -1),
            "status": n.status,
            "risk": risk_value(n),
        }
        for n in node_rows
    ]

    edge_payload = [
        {"source": s, "target": d, "kind": k}
        for s, d, k in edge_set
        if s in nodes_set and d in nodes_set
    ]

    truncated_edges = bool(max_edges > 0 and len(edge_set) >= max_edges)
    meta = {
        "center": center_path,
        "found": True,
        "hops": hops,
        "returned_nodes": len(node_payload),
        "returned_edges": len(edge_payload),
        "truncated": len(nodes_set) >= max_nodes or truncated_edges,
    }
    return {"nodes": node_payload, "edges": edge_payload, "meta": meta}


def search_nodes(project_id: int, query: str, limit: int = 20) -> list[dict]:
    if not query:
        return []
    pattern = f"%{query}%"
    limit = max(1, min(limit, 100))
    with get_session() as s:
        rows = s.exec(
            select(FileNode.path, FileNode.language, FileNode.fan_in, FileNode.fan_out)
            .where(FileNode.project_id == project_id, FileNode.path.like(pattern))
            .order_by(FileNode.path)
            .limit(limit)
        ).all()
    out: list[dict] = []
    for row in rows:
        if isinstance(row, (tuple, list)):
            path, lang, fi, fo = row[0], row[1], row[2], row[3]
        else:
            path = getattr(row, "path", "")
            lang = getattr(row, "language", "")
            fi = getattr(row, "fan_in", 0)
            fo = getattr(row, "fan_out", 0)
        if not isinstance(path, str) or not path:
            continue
        out.append(
            {
                "path": path,
                "language": lang,
                "fan_in": _as_int(fi, 0),
                "fan_out": _as_int(fo, 0),
            }
        )
    return out


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    if size <= 0:
        return []
    overlap = max(0, min(overlap, size - 1))
    step = max(1, size - overlap)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        end = start + size
        chunk = text[start:end]
        if chunk:
            chunks.append(chunk)
    return chunks


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


def search_semantic(
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

    try:
        client = get_openai_client()
        resp = client.embeddings.create(model=settings.embeddings_model, input=[q])
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

    filters = [FileChunkEmbedding.project_id == project_id]
    if prefix_norm:
        like = f"{prefix_norm}/%"
        filters.append((FileChunkEmbedding.path == prefix_norm) | (FileChunkEmbedding.path.like(like)))

    with get_session() as s:
        total_candidates_row = s.exec(
            select(func.count())
            .select_from(FileChunkEmbedding)
            .where(*filters)
        ).one()
        if isinstance(total_candidates_row, (tuple, list)):
            total_candidates = _as_int(total_candidates_row[0] if total_candidates_row else 0, 0)
        else:
            try:
                total_candidates = _as_int(total_candidates_row[0], 0)  # type: ignore[index]
            except Exception:
                total_candidates = _as_int(total_candidates_row, 0)

        if total_candidates == 0:
            return {
                "error": "embeddings_empty",
                "message": (
                    "No embeddings found for this project. "
                    "Please rescan the project with embeddings enabled."
                ),
                "meta": {"reason": "no_embeddings"},
            }

        rows = s.exec(
            select(
                FileChunkEmbedding.path,
                FileChunkEmbedding.chunk_index,
                FileChunkEmbedding.embedding_json,
            )
            .where(*filters)
            .order_by(FileChunkEmbedding.path.asc(), FileChunkEmbedding.chunk_index.asc())
            .limit(int(max_candidates))
        ).all()

    compared = 0
    scored: list[dict] = []

    file_cache: dict[str, str] = {}
    chunk_size = int(settings.embeddings_chunk_size)
    overlap = int(settings.embeddings_chunk_overlap)
    step = max(1, chunk_size - overlap)
    max_file_chars = int(settings.embeddings_max_file_chars)

    for row in rows:
        if isinstance(row, (tuple, list)):
            path, chunk_index, embedding_json = row[0], row[1], row[2]
        else:
            path = getattr(row, "path", "")
            chunk_index = getattr(row, "chunk_index", 0)
            embedding_json = getattr(row, "embedding_json", "")
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
        if path not in file_cache:
            try:
                abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
            except Exception:
                file_cache[path] = ""
            else:
                if abs_path.exists() and abs_path.is_file():
                    try:
                        with abs_path.open("r", encoding="utf-8", errors="replace") as f:
                            file_cache[path] = f.read(max_file_chars)
                    except Exception:
                        file_cache[path] = ""
                else:
                    file_cache[path] = ""
        text = file_cache.get(path, "")
        if text:
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

        scored.append({"path": path, "score": float(score), "snippet": snippet})

    scored.sort(key=lambda x: x["score"], reverse=True)
    results = scored[: max_results_eff]
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
