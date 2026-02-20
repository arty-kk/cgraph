# backend/app/context_pack.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .async_db import AsyncSessionLocal
from .contracts import get_or_build_contract_async
from .infra.fs_runtime import run_fs_io_async
from .infra.cache import cache_get_json_async, cache_set_json_async
from .logging import get_logger
from .models import FileEdge, FileNode

logger = get_logger("stubgraph.context_pack")


@dataclass
class PackedContext:
    target_path: str
    files: list[dict]
    graph: dict


async def _neighbors_async(
    session: AsyncSession,
    project_id: int,
    start: str,
    depth: int,
    direction: str = "out",
) -> list[str]:
    if depth <= 0:
        return []

    visited: set[str] = {start}
    ordered: list[str] = []
    frontier: list[str] = [start]
    for _ in range(depth):
        if not frontier:
            break
        if direction == "in":
            rows = (
                await session.execute(
                    select(FileEdge.src_path, FileEdge.dst_path)
                    .where(FileEdge.project_id == project_id, FileEdge.dst_path.in_(frontier))
                    .order_by(FileEdge.src_path, FileEdge.dst_path)
                )
            ).all()
        else:
            rows = (
                await session.execute(
                    select(FileEdge.src_path, FileEdge.dst_path)
                    .where(FileEdge.project_id == project_id, FileEdge.src_path.in_(frontier))
                    .order_by(FileEdge.src_path, FileEdge.dst_path)
                )
            ).all()
        nxt: list[str] = []
        for src, dst in rows:
            src_val = src if isinstance(src, str) else ""
            dst_val = dst if isinstance(dst, str) else ""
            candidate = src_val if direction == "in" else dst_val
            if not candidate:
                continue
            if candidate in visited:
                continue
            visited.add(candidate)
            ordered.append(candidate)
            nxt.append(candidate)
        frontier = nxt
    return ordered


async def _file_hash_async(session: AsyncSession, project_id: int, path: str) -> str | None:
    row = (
        await session.execute(
            select(FileNode.file_hash).where(FileNode.project_id == project_id, FileNode.path == path)
        )
    ).first()
    if isinstance(row, (tuple, list)):
        row = row[0] if row else None
    return row if isinstance(row, str) and row else None


def _read_file(path: Path, max_chars: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""


async def _read_file_async(path: Path, max_chars: int) -> str:
    return await run_fs_io_async(_read_file, path, max_chars, operation="context_pack.read_file")


def _path_exists_and_is_file(path: Path) -> bool:
    return path.exists() and path.is_file()


async def _path_exists_and_is_file_async(path: Path) -> bool:
    return await run_fs_io_async(_path_exists_and_is_file, path, operation="context_pack.path_is_file")


async def pack_context_async(
    project_id: int,
    project_root: Path,
    target_rel: str,
    depth: int,
    dep_mode: str = "contracts",
    max_files: int = 25,
    max_chars_per_file: int = 12000,
    mode: str = "analyze",
    max_total_chars: int = 120000,
    *,
    session: AsyncSession | None = None,
) -> PackedContext:
    project_root = await run_fs_io_async(project_root.resolve, operation="context_pack.resolve_root")
    cache_hits = {"file": 0, "contract": 0}

    async def _read_file_cached(path: str, max_chars: int) -> str:
        file_hash = await _file_hash_async(active_session, project_id, path)
        cache_key = (
            [f"project:{project_id}", "pack", "file", path, file_hash]
            if file_hash
            else None
        )
        if cache_key:
            cached = await cache_get_json_async(cache_key)
            if isinstance(cached, dict) and isinstance(cached.get("content"), str):
                cache_hits["file"] += 1
                return cached["content"][:max_chars]
        content = await _read_file_async(project_root / path, max_chars)
        if cache_key:
            await cache_set_json_async(cache_key, {"content": content})
        return content

    async def _get_contract(path: str) -> tuple[dict | None, list[str]]:
        try:
            file_hash = await _file_hash_async(active_session, project_id, path)
            contract_key = (
                [f"project:{project_id}", "pack", "contract", path, file_hash]
                if file_hash
                else None
            )
            cached_contract = await cache_get_json_async(contract_key) if contract_key else None
            contract = (
                cached_contract
                if isinstance(cached_contract, dict)
                else await get_or_build_contract_async(active_session, project_id, project_root, path)
            )
            if isinstance(cached_contract, dict):
                cache_hits["contract"] += 1
            if contract_key and isinstance(contract, dict):
                await cache_set_json_async(contract_key, contract)
            exports = [str(x) for x in contract.get("exports", []) if isinstance(x, str)]
            return contract if isinstance(contract, dict) else None, exports
        except Exception:
            return None, []

    async def _run() -> PackedContext:
        target_text = await _read_file_cached(target_rel, max_chars_per_file)

        _target_contract, exports = await _get_contract(target_rel)

        out_deps = await _neighbors_async(active_session, project_id, target_rel, depth, direction="out")
        in_depth = max(0, min(depth, 2))
        in_deps = await _neighbors_async(active_session, project_id, target_rel, in_depth, direction="in")

        def _uniq(seq: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for x in seq:
                if x in seen:
                    continue
                seen.add(x)
                out.append(x)
            return out

        prioritized = _uniq(in_deps + out_deps)
        if mode == "fix":
            prioritized = _uniq(in_deps + prioritized + out_deps)

        files: list[dict] = []
        total_chars = 0

        async def _add_file(path: str, kind: str) -> None:
            nonlocal total_chars
            if len(files) >= max_files:
                return
            if total_chars >= max_total_chars:
                return
            abs_p = project_root / path
            if not await _path_exists_and_is_file_async(abs_p):
                return
            content = await _read_file_cached(path, max_chars_per_file)
            if not content:
                return
            if total_chars + len(content) > max_total_chars:
                return
            total_chars += len(content)
            files.append({"path": path, "kind": kind, "content": content})

        files.append({"path": target_rel, "kind": "target", "content": target_text})
        total_chars += len(target_text)

        symbol_mentions: list[str] = []
        if exports:
            nodes = (
                await active_session.execute(
                    select(FileNode.path)
                    .where(FileNode.project_id == project_id)
                    .order_by(FileNode.fan_in.desc())
                    .limit(200)
                )
            ).all()
            candidates = [
                r[0] if isinstance(r, (tuple, list)) else getattr(r, "path", "") for r in nodes
            ]
            candidates = [
                c
                for c in candidates
                if isinstance(c, str) and c and c not in prioritized and c != target_rel
            ]
            for c in candidates:
                text = await _read_file_async(project_root / c, max_chars_per_file)
                if not text:
                    continue
                for sym in exports:
                    if sym and sym in text:
                        symbol_mentions.append(c)
                        break
            symbol_mentions = symbol_mentions[: max(0, max_files - len(prioritized))]

        ordered_deps = _uniq(prioritized + symbol_mentions)
        for d in ordered_deps:
            if len(files) >= max_files or total_chars >= max_total_chars:
                break
            try:
                if dep_mode == "full" or mode == "fix":
                    await _add_file(d, "dep_full")
                else:
                    contract, _ = await _get_contract(d)
                    if not isinstance(contract, dict):
                        continue
                    contract_size = len(json.dumps(contract, ensure_ascii=False))
                    if total_chars + contract_size > max_total_chars:
                        continue
                    files.append({"path": d, "kind": "dep_contract", "contract": contract})
                    total_chars += contract_size
            except Exception:
                continue

        graph = {
            "target": target_rel,
            "deps": ordered_deps,
            "inbound": in_deps,
            "outbound": out_deps,
        }
        logger.info(
            "Context pack cache",
            extra={
                "project_id": project_id,
                "target": target_rel,
                "file_cache_hits": cache_hits["file"],
                "contract_cache_hits": cache_hits["contract"],
            },
        )
        return PackedContext(target_path=target_rel, files=files, graph=graph)

    if session is not None:
        active_session = session
        return await _run()

    async with AsyncSessionLocal() as active_session:
        return await _run()
