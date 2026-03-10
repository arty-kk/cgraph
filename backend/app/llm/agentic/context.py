from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import literal, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ...async_db import AsyncSessionLocal
from ...config import settings
from ...contracts import get_or_build_contract_async
from ...graph_traversal import neighbors_limited_recursive_cte_async
from ...infra.fs_runtime import run_fs_io_async
from ...models import ApiCall, ApiRoute, FileNode
from ...utils import resolve_under_root

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_SEED_FS_SEMAPHORE: asyncio.Semaphore | None = None
_SEED_FS_SEMAPHORE_LOOP: asyncio.AbstractEventLoop | None = None
_SEED_FS_SEMAPHORE_LOCK: asyncio.Lock | None = None
_SEED_FS_SEMAPHORE_LOCK_LOOP: asyncio.AbstractEventLoop | None = None


def _get_seed_fs_semaphore_lock() -> asyncio.Lock:
    global _SEED_FS_SEMAPHORE_LOCK, _SEED_FS_SEMAPHORE_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _SEED_FS_SEMAPHORE_LOCK is None or _SEED_FS_SEMAPHORE_LOCK_LOOP is not loop:
        _SEED_FS_SEMAPHORE_LOCK = asyncio.Lock()
        _SEED_FS_SEMAPHORE_LOCK_LOOP = loop
    return _SEED_FS_SEMAPHORE_LOCK


def _seed_fs_limit() -> int:
    llm_limit = max(1, int(settings.llm_agentic_fs_ops_concurrency))
    runtime_limit = max(1, int(getattr(settings, "fs_runtime_interactive_max_concurrency", llm_limit)))
    return min(llm_limit, runtime_limit)


async def _seed_fs_semaphore_async() -> asyncio.Semaphore:
    global _SEED_FS_SEMAPHORE, _SEED_FS_SEMAPHORE_LOOP
    loop = asyncio.get_running_loop()
    sem = _SEED_FS_SEMAPHORE
    if sem is not None and _SEED_FS_SEMAPHORE_LOOP is loop:
        return sem
    async with _get_seed_fs_semaphore_lock():
        if _SEED_FS_SEMAPHORE is None or _SEED_FS_SEMAPHORE_LOOP is not loop:
            _SEED_FS_SEMAPHORE = asyncio.Semaphore(_seed_fs_limit())
            _SEED_FS_SEMAPHORE_LOOP = loop
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
    limit = max(1, min(int(max_file_chars), 200_000))
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
        with open(abs_target, encoding="utf-8", errors="replace") as file_obj:
            target_text = file_obj.read(limit + 1)
    except Exception:
        return target_norm, ""
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
        max_depth=6,
        max_limit=2000,
    )


async def _load_contract_async(
    project_id: int,
    root: Path,
    target_norm: str,
    *,
    session_factory: Callable[[], Any],
) -> dict:
    try:
        async with session_factory() as session:
            return await get_or_build_contract_async(session, project_id, root, target_norm)
    except Exception:
        return {}


async def _load_target_node_metrics_async(
    project_id: int,
    target_norm: str,
    *,
    session_factory: Callable[[], Any],
) -> dict:
    try:
        async with session_factory() as session:
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
    except Exception:
        return {}
    if not node:
        return {}
    return {
        "path": node.path,
        "language": node.language,
        "loc": node.loc,
        "complexity": node.complexity,
        "fan_in": node.fan_in,
        "fan_out": node.fan_out,
        "scc_id": node.scc_id,
        "status": node.status,
    }


async def _load_api_hints_async(
    project_id: int,
    target_norm: str,
    *,
    session_factory: Callable[[], Any],
) -> tuple[list[dict], list[dict]]:
    routes_in_file: list[dict] = []
    calls_in_file: list[dict] = []
    try:
        routes_stmt = (
            select(
                literal("route").label("kind"),
                ApiRoute.method.label("method"),
                ApiRoute.path.label("path"),
                ApiRoute.handler_name.label("name"),
                ApiRoute.lineno.label("lineno"),
            )
            .where(ApiRoute.project_id == project_id, ApiRoute.source_path == target_norm)
            .order_by(ApiRoute.path.asc())
            .limit(20)
        )
        calls_stmt = (
            select(
                literal("call").label("kind"),
                ApiCall.method.label("method"),
                ApiCall.path.label("path"),
                ApiCall.client.label("name"),
                ApiCall.lineno.label("lineno"),
            )
            .where(ApiCall.project_id == project_id, ApiCall.source_path == target_norm)
            .order_by(ApiCall.path.asc())
            .limit(20)
        )
        async with session_factory() as session:
            rows = (await session.execute(union_all(routes_stmt, calls_stmt))).all()
        for row in rows:
            if hasattr(row, "_mapping"):
                kind = row._mapping.get("kind")
                method = row._mapping.get("method")
                path = row._mapping.get("path")
                name = row._mapping.get("name")
                lineno = row._mapping.get("lineno")
            elif isinstance(row, (tuple, list)) and len(row) >= 5:
                kind, method, path, name, lineno = row[0], row[1], row[2], row[3], row[4]
            else:
                continue
            if kind == "route":
                routes_in_file.append(
                    {
                        "method": method,
                        "path": path,
                        "handler_name": name,
                        "lineno": int(lineno or 0),
                    }
                )
                continue
            if kind == "call":
                calls_in_file.append(
                    {
                        "method": method,
                        "path": path,
                        "client": name,
                        "lineno": int(lineno or 0),
                    }
                )
    except Exception:
        return [], []
    routes_in_file.sort(key=lambda row: str(row.get("path") or ""))
    calls_in_file.sort(key=lambda row: str(row.get("path") or ""))
    return routes_in_file, calls_in_file


async def _load_outbound_hint_async(
    project_id: int,
    target_norm: str,
    out_depth: int,
    *,
    session_factory: Callable[[], Any],
) -> list[str]:
    async with session_factory() as session:
        return await _neighbors_limited_async(
            session, project_id, target_norm, direction="out", depth=out_depth, limit=200
        )


async def _load_inbound_hint_async(
    project_id: int,
    target_norm: str,
    in_depth: int,
    *,
    session_factory: Callable[[], Any],
) -> list[str]:
    async with session_factory() as session:
        return await _neighbors_limited_async(
            session, project_id, target_norm, direction="in", depth=in_depth, limit=200
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
    session_factory: Callable[[], Any] | None = None,
) -> dict:
    _ = session
    if session_factory is None:
        session_factory = AsyncSessionLocal
    max_file_chars = max(1, min(int(max_file_chars), 200_000))
    target_norm, target_text = await _run_seed_fs_io_async(
        _resolve_and_read_seed_file_sync,
        root,
        target_rel,
        max_file_chars=max_file_chars,
    )

    out_depth = max(0, min(depth, 6))
    in_depth = max(0, min(depth, 2))
    (
        contract_result,
        node_metrics_result,
        api_hints_result,
        outbound_result,
        inbound_result,
    ) = await asyncio.gather(
        _load_contract_async(project_id, root, target_norm, session_factory=session_factory),
        _load_target_node_metrics_async(
            project_id, target_norm, session_factory=session_factory
        ),
        _load_api_hints_async(project_id, target_norm, session_factory=session_factory),
        _load_outbound_hint_async(project_id, target_norm, out_depth, session_factory=session_factory),
        _load_inbound_hint_async(project_id, target_norm, in_depth, session_factory=session_factory),
        return_exceptions=True,
    )

    contract = contract_result if isinstance(contract_result, dict) else {}
    node_metrics = node_metrics_result if isinstance(node_metrics_result, dict) else {}
    routes_in_file: list[dict] = []
    calls_in_file: list[dict] = []
    if isinstance(api_hints_result, tuple) and len(api_hints_result) == 2:
        routes_in_file, calls_in_file = api_hints_result

    if isinstance(outbound_result, Exception):
        raise outbound_result
    outbound = outbound_result if isinstance(outbound_result, list) else []

    if isinstance(inbound_result, Exception):
        raise inbound_result
    inbound = inbound_result if isinstance(inbound_result, list) else []

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
