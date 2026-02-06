from __future__ import annotations

import re
from pathlib import Path

from sqlmodel import select

from ...config import settings
from ...contracts import get_or_build_contract
from ...db import get_session
from ...models import ApiCall, ApiRoute, FileEdge, FileNode
from ...utils import resolve_under_root

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _neighbors_limited(
    project_id: int,
    start: str,
    *,
    direction: str,
    depth: int,
    limit: int,
) -> list[str]:
    if depth <= 0 or limit <= 0:
        return []
    depth = max(0, min(depth, 6))
    limit = max(1, min(limit, 2000))
    visited: set[str] = {start}
    ordered: list[str] = []
    frontier: list[str] = [start]

    def _chunks(seq: list[str], size: int) -> list[list[str]]:
        return [seq[i : i + size] for i in range(0, len(seq), size)]

    SQLITE_IN_CHUNK = 400

    with get_session() as s:
        for _ in range(depth):
            if not frontier or len(ordered) >= limit:
                break
            frontier = list(dict.fromkeys(frontier))
            nxt: list[str] = []
            stop = False
            for chunk in _chunks(frontier, SQLITE_IN_CHUNK):
                if direction == "in":
                    rows = s.exec(
                        select(FileEdge.src_path)
                        .where(FileEdge.project_id == project_id, FileEdge.dst_path.in_(chunk))
                        .order_by(FileEdge.src_path)
                    ).all()
                else:
                    rows = s.exec(
                        select(FileEdge.dst_path)
                        .where(FileEdge.project_id == project_id, FileEdge.src_path.in_(chunk))
                        .order_by(FileEdge.dst_path)
                    ).all()
                for row in rows:
                    val = row[0] if isinstance(row, (tuple, list)) else row
                    if not isinstance(val, str) or not val:
                        continue
                    if val in visited:
                        continue
                    visited.add(val)
                    ordered.append(val)
                    nxt.append(val)
                    if len(ordered) >= limit:
                        stop = True
                        break
                if stop:
                    break
            frontier = nxt
    return ordered[:limit]


def _fts_query_from_substring(q: str, *, max_tokens: int = 12) -> str | None:
    tokens = [t for t in _FTS_TOKEN_RE.findall(q or "") if t]
    if not tokens:
        return None
    tokens = tokens[: max(1, int(max_tokens))]
    esc = []
    for t in tokens:
        esc.append(t.replace('"', '""'))
    return " AND ".join([f'"{t}"' for t in esc if t])


def _seed_context(
    project_id: int, root: Path, target_rel: str, depth: int, *, max_file_chars: int
) -> dict:
    abs_target, target_norm = resolve_under_root(
        root, target_rel, max_length=settings.max_rel_path_chars
    )
    target_text = ""
    try:
        target_text = abs_target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        target_text = ""
    max_file_chars = max(1, min(int(max_file_chars), 200_000))
    if len(target_text) > max_file_chars:
        target_text = target_text[:max_file_chars]

    contract = {}
    try:
        contract = get_or_build_contract(project_id, root, target_norm)
    except Exception:
        contract = {}

    node = None
    with get_session() as s:
        node = s.exec(
            select(FileNode).where(FileNode.project_id == project_id, FileNode.path == target_norm)
        ).first()
    node_metrics = (
        {
            "path": node.path,
            "language": node.language,
            "loc": node.loc,
            "complexity": node.complexity,
            "fan_in": node.fan_in,
            "fan_out": node.fan_out,
            "scc_id": node.scc_id,
            "status": node.status,
        }
        if node
        else {}
    )

    routes_in_file: list[dict] = []
    calls_in_file: list[dict] = []
    try:
        with get_session() as s:
            rr = s.exec(
                select(ApiRoute.method, ApiRoute.path, ApiRoute.handler_name, ApiRoute.lineno)
                .where(ApiRoute.project_id == project_id, ApiRoute.source_path == target_norm)
                .order_by(ApiRoute.path.asc())
                .limit(20)
            ).all()
            for row in rr:
                if isinstance(row, (tuple, list)) and len(row) >= 4:
                    routes_in_file.append(
                        {
                            "method": row[0],
                            "path": row[1],
                            "handler_name": row[2],
                            "lineno": int(row[3] or 0),
                        }
                    )

            cc = s.exec(
                select(ApiCall.method, ApiCall.path, ApiCall.client, ApiCall.lineno)
                .where(ApiCall.project_id == project_id, ApiCall.source_path == target_norm)
                .order_by(ApiCall.path.asc())
                .limit(20)
            ).all()
            for row in cc:
                if isinstance(row, (tuple, list)) and len(row) >= 4:
                    calls_in_file.append(
                        {
                            "method": row[0],
                            "path": row[1],
                            "client": row[2],
                            "lineno": int(row[3] or 0),
                        }
                    )
    except Exception:
        routes_in_file = []
        calls_in_file = []

    out_depth = max(0, min(depth, 6))
    in_depth = max(0, min(depth, 2))
    outbound = _neighbors_limited(
        project_id, target_norm, direction="out", depth=out_depth, limit=200
    )
    inbound = _neighbors_limited(project_id, target_norm, direction="in", depth=in_depth, limit=200)

    return {
        "target_path": target_norm,
        "target_file": {"path": target_norm, "content": target_text, "max_chars": max_file_chars},
        "target_contract": contract,
        "target_node": node_metrics,
        "api_hint": {
            "routes_in_file": routes_in_file,
            "calls_in_file": calls_in_file,
            "note": "Use search_routes/search_api_calls/route_usages for project-wide API mapping.",
        },
        "graph_hint": {
            "inbound": inbound,
            "outbound": outbound,
            "in_depth": in_depth,
            "out_depth": out_depth,
            "note": "Lists are truncated hints. Use get_neighbors() to expand.",
        },
    }
