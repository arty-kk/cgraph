# backend/app/context_pack.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .async_db import AsyncSessionLocal
from .config import settings
from .contracts import get_or_build_contract_async
from .graph_traversal import neighbors_limited_recursive_cte_async
from .infra.cache import (
    cache_get_json_async,
    cache_mget_json_async,
    cache_mset_json_async,
    cache_set_json_async,
)
from .infra.fs_runtime import run_fs_io_async
from .logging import get_logger
from .models import FileNode

logger = get_logger("stubgraph.context_pack")


@dataclass
class PackedContext:
    target_path: str
    files: list[dict]
    graph: dict


def _read_file(path: Path, max_chars: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""


async def _read_file_async(path: Path, max_chars: int) -> str:
    return await run_fs_io_async(_read_file, path, max_chars, operation="context_pack.read_file")


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
    project_root = await run_fs_io_async(
        project_root.resolve, operation="context_pack.resolve_root"
    )
    cache_hits = {"file": 0, "contract": 0}
    effective_context_pack_read_concurrency = max(
        1,
        min(
            int(getattr(settings, "context_pack_read_concurrency", 8)),
            int(getattr(settings, "fs_runtime_interactive_max_concurrency", 32)),
        ),
    )
    io_semaphore = asyncio.Semaphore(effective_context_pack_read_concurrency)
    # Contract builds touch the shared ``active_session``; AsyncSession forbids
    # concurrent operations, so serialize the DB-bound build path while leaving
    # the filesystem read batch free to run concurrently under ``io_semaphore``.
    contract_db_lock = asyncio.Lock()
    hash_by_path: dict[str, str] = {}

    async def _read_file_cached(path: str, max_chars: int) -> str:
        file_hash = hash_by_path.get(path)
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

    async def _get_contract(path: str, *, use_cache: bool = True) -> tuple[dict | None, list[str]]:
        try:
            file_hash = hash_by_path.get(path)
            contract_key = (
                [f"project:{project_id}", "pack", "contract", path, file_hash]
                if file_hash
                else None
            )
            cached_contract = (
                await cache_get_json_async(contract_key)
                if use_cache and contract_key
                else None
            )
            contract = (
                cached_contract
                if isinstance(cached_contract, dict)
                else await get_or_build_contract_async(
                    active_session, project_id, project_root, path
                )
            )
            if isinstance(cached_contract, dict):
                cache_hits["contract"] += 1
            if use_cache and contract_key and isinstance(contract, dict):
                await cache_set_json_async(contract_key, contract)
            exports = [str(x) for x in contract.get("exports", []) if isinstance(x, str)]
            return contract if isinstance(contract, dict) else None, exports
        except Exception:
            return None, []

    async def _load_hashes(paths: list[str]) -> None:
        unique_paths = list(dict.fromkeys(p for p in paths if isinstance(p, str) and p))
        if not unique_paths:
            return
        rows = (
            await active_session.execute(
                select(FileNode.path, FileNode.file_hash).where(
                    FileNode.project_id == project_id,
                    FileNode.path.in_(unique_paths),
                )
            )
        ).all()
        for row in rows:
            path = row[0] if isinstance(row, (tuple, list)) else getattr(row, "path", "")
            file_hash = row[1] if isinstance(row, (tuple, list)) else getattr(row, "file_hash", "")
            if isinstance(path, str) and path and isinstance(file_hash, str) and file_hash:
                hash_by_path[path] = file_hash

    async def _read_files_cached_batch(
        paths: list[str],
        max_chars: int,
    ) -> dict[str, str]:
        keys_by_path: dict[str, list[str]] = {}
        cache_keys: list[list[str]] = []
        for path in paths:
            file_hash = hash_by_path.get(path)
            if not file_hash:
                continue
            key = [f"project:{project_id}", "pack", "file", path, file_hash]
            keys_by_path[path] = key
            cache_keys.append(key)
        cached_values = await cache_mget_json_async(cache_keys) if cache_keys else []
        cached_by_path: dict[str, str] = {}
        cache_key_to_path = {tuple(key): path for path, key in keys_by_path.items()}
        for key, payload in zip(cache_keys, cached_values):
            if isinstance(payload, dict) and isinstance(payload.get("content"), str):
                path = cache_key_to_path.get(tuple(key))
                if path:
                    cache_hits["file"] += 1
                    cached_by_path[path] = payload["content"][:max_chars]

        missing = [path for path in paths if path not in cached_by_path]

        async def _read_missing(path: str) -> tuple[str, str]:
            async with io_semaphore:
                return path, await _read_file_async(project_root / path, max_chars)

        loaded = await asyncio.gather(*[_read_missing(path) for path in missing])
        set_entries: list[tuple[list[str], dict[str, str]]] = []
        for path, content in loaded:
            cached_by_path[path] = content
            key = keys_by_path.get(path)
            if key:
                set_entries.append((key, {"content": content}))
        await cache_mset_json_async(set_entries)
        return cached_by_path

    async def _get_contracts_cached_batch(
        paths: list[str],
    ) -> dict[str, tuple[dict | None, list[str]]]:
        keys_by_path: dict[str, list[str]] = {}
        cache_keys: list[list[str]] = []
        for path in paths:
            file_hash = hash_by_path.get(path)
            if not file_hash:
                continue
            key = [f"project:{project_id}", "pack", "contract", path, file_hash]
            keys_by_path[path] = key
            cache_keys.append(key)

        cached_values = await cache_mget_json_async(cache_keys) if cache_keys else []
        result: dict[str, tuple[dict | None, list[str]]] = {}
        cache_key_to_path = {tuple(key): path for path, key in keys_by_path.items()}
        missing: list[str] = []
        for key, payload in zip(cache_keys, cached_values):
            path = cache_key_to_path.get(tuple(key))
            if not path:
                continue
            if isinstance(payload, dict):
                cache_hits["contract"] += 1
                exports = [str(x) for x in payload.get("exports", []) if isinstance(x, str)]
                result[path] = (payload, exports)
            else:
                missing.append(path)

        missing.extend(path for path in paths if path not in keys_by_path and path not in result)

        async def _load_missing(path: str) -> tuple[str, tuple[dict | None, list[str]]]:
            async with contract_db_lock:
                return path, await _get_contract(path, use_cache=False)

        loaded = await asyncio.gather(*[_load_missing(path) for path in missing])
        set_entries: list[tuple[list[str], dict]] = []
        for path, payload in loaded:
            contract, exports = payload
            result[path] = payload
            key = keys_by_path.get(path)
            if key and isinstance(contract, dict):
                set_entries.append((key, contract))
        await cache_mset_json_async(set_entries)
        return result

    async def _run() -> PackedContext:
        out_deps = await neighbors_limited_recursive_cte_async(
            active_session,
            project_id,
            target_rel,
            direction="out",
            depth=depth,
        )
        in_depth = max(0, min(depth, 2))
        in_deps = await neighbors_limited_recursive_cte_async(
            active_session,
            project_id,
            target_rel,
            direction="in",
            depth=in_depth,
        )

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

        nodes = (
            await active_session.execute(
                select(FileNode.path)
                .where(FileNode.project_id == project_id)
                .order_by(FileNode.fan_in.desc())
                .limit(200)
            )
        ).all()
        candidates = [
            r[0] if isinstance(r, (tuple, list)) else getattr(r, "path", "")
            for r in nodes
        ]
        candidates = [
            c
            for c in candidates
            if isinstance(c, str) and c and c not in prioritized and c != target_rel
        ]

        await _load_hashes([target_rel] + prioritized + candidates)

        target_text = await _read_file_cached(target_rel, max_chars_per_file)
        _target_contract, exports = await _get_contract(target_rel)

        files: list[dict] = []
        total_chars = 0
        files.append({"path": target_rel, "kind": "target", "content": target_text})
        total_chars += len(target_text)

        symbol_mentions: list[str] = []
        if exports and candidates:
            candidate_texts = await _read_files_cached_batch(candidates, max_chars_per_file)
            for c in candidates:
                text = candidate_texts.get(c, "")
                if not text:
                    continue
                for sym in exports:
                    if sym and sym in text:
                        symbol_mentions.append(c)
                        break
            symbol_mentions = symbol_mentions[: max(0, max_files - len(prioritized))]

        ordered_deps = _uniq(prioritized + symbol_mentions)
        dep_contracts = (
            await _get_contracts_cached_batch(ordered_deps)
            if dep_mode != "full" and mode != "fix"
            else {}
        )
        dep_full_texts = (
            await _read_files_cached_batch(ordered_deps, max_chars_per_file)
            if dep_mode == "full" or mode == "fix"
            else {}
        )

        for d in ordered_deps:
            if len(files) >= max_files or total_chars >= max_total_chars:
                break
            try:
                if dep_mode == "full" or mode == "fix":
                    content = dep_full_texts.get(d, "")
                    if not content:
                        continue
                    if total_chars + len(content) > max_total_chars:
                        continue
                    files.append({"path": d, "kind": "dep_full", "content": content})
                    total_chars += len(content)
                else:
                    contract, _ = dep_contracts.get(d, (None, []))
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
