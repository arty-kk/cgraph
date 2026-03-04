from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ...config import settings
from ...contracts import get_or_build_contract_async
from ...graph_traversal import neighbors_limited_recursive_cte_async
from ...infra.fs_runtime import run_fs_io_async
from ...models import ApiCall, ApiRoute, FileNode
from ...utils import resolve_under_root

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_SEED_FS_SEMAPHORE: asyncio.Semaphore | None = None
_SEED_FS_SEMAPHORE_LOCK = asyncio.Lock()


def _seed_fs_limit() -> int:
    llm_limit = max(1, int(settings.llm_agentic_fs_ops_concurrency))
    runtime_limit = max(1, int(getattr(settings, "fs_runtime_max_concurrency", llm_limit)))
    return min(llm_limit, runtime_limit)


async def _seed_fs_semaphore_async() -> asyncio.Semaphore:
    global _SEED_FS_SEMAPHORE
    sem = _SEED_FS_SEMAPHORE
    if sem is not None:
        return sem
    async with _SEED_FS_SEMAPHORE_LOCK:
        if _SEED_FS_SEMAPHORE is None:
            _SEED_FS_SEMAPHORE = asyncio.Semaphore(_seed_fs_limit())
        return _SEED_FS_SEMAPHORE


async def _run_seed_fs_io_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
    semaphore = await _seed_fs_semaphore_async()
    async with semaphore:
        return await run_fs_io_async(fn, *args, operation="agentic.seed_context.fs", **kwargs)


def _resolve_and_read_seed_file_sync(
    root: Path,
    target_rel: str,
    *,
    max_file_chars: int,
) -> tuple[str, str]:
    abs_target, target_norm = resolve_under_root(
        root, target_rel, max_length=settings.max_rel_path_chars
    )
    try:
        stat_result = abs_target.stat()
    except Exception:
        return target_norm, ""
    if not stat_result or not abs_target.is_file():
        return target_norm, ""
    try:
        target_text = abs_target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return target_norm, ""
    limit = max(1, min(int(max_file_chars), 200_000))
    if len(target_text) > limit:
        target_text = target_text[:limit]
    return target_norm, target_text


async def _neighbors_limited_async(
    session: AsyncSession,
    project_id: int,
    start: str,
    *,
    direction: str,
    depth: int,
    limit: int,
) -> list[str]:
    return await neighbors_limited_recursive_cte_async(
        session,
        project_id,
        start,
        direction=direction,
        depth=depth,
        limit=limit,
    )


def _fts_query_from_substring(q: str, *, max_tokens: int = 12) -> str | None:
    tokens = [t for t in _FTS_TOKEN_RE.findall(q or "") if t]
    if not tokens:
        return None
    tokens = tokens[: max(1, int(max_tokens))]
    esc = []
    for t in tokens:
        esc.append(t.replace('"', '""'))
    return " AND ".join([f'"{t}"' for t in esc if t])


async def _seed_context_async(
    session: AsyncSession,
    project_id: int,
    root: Path,
    target_rel: str,
    depth: int,
    *,
    max_file_chars: int,
) -> dict:
    max_file_chars = max(1, min(int(max_file_chars), 200_000))
    target_norm, target_text = await _run_seed_fs_io_async(
        _resolve_and_read_seed_file_sync,
        root,
        target_rel,
        max_file_chars=max_file_chars,
    )

    try:
        contract = await get_or_build_contract_async(session, project_id, root, target_norm)
    except Exception:
        contract = {}

    node = (
        (
            await session.execute(
                select(FileNode).where(
                    FileNode.project_id == project_id,
                    FileNode.path == target_norm,
                )
            )
        )
        .scalars()
        .first()
    )
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
        rr = (
            (
                await session.execute(
                    select(
                        ApiRoute.method,
                        ApiRoute.path,
                        ApiRoute.handler_name,
                        ApiRoute.lineno,
                    )
                    .where(
                        ApiRoute.project_id == project_id,
                        ApiRoute.source_path == target_norm,
                    )
                    .order_by(ApiRoute.path.asc())
                    .limit(20)
                )
            )
            .all()
        )
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

        cc = (
            (
                await session.execute(
                    select(ApiCall.method, ApiCall.path, ApiCall.client, ApiCall.lineno)
                    .where(ApiCall.project_id == project_id, ApiCall.source_path == target_norm)
                    .order_by(ApiCall.path.asc())
                    .limit(20)
                )
            )
            .all()
        )
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
    outbound = await _neighbors_limited_async(
        session, project_id, target_norm, direction="out", depth=out_depth, limit=200
    )
    inbound = await _neighbors_limited_async(
        session, project_id, target_norm, direction="in", depth=in_depth, limit=200
    )

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
