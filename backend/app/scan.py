# backend/app/scan.py
from __future__ import annotations

import json
import os
import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterable, Tuple

from sqlalchemy import bindparam, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from .api_contracts import (
    extract_backend_route_contract_rows,
    extract_frontend_call_meta_rows,
    extract_ts_type_defs,
)
from .api_map import (
    extract_fastapi_includes,
    extract_fastapi_routes,
    extract_frontend_api_calls,
)
from .async_db import AsyncSessionLocal
from .config import settings
from .errors import LimitExceededError, LockedError
from .indexers import pick_indexer
from .indexers.infra_indexer import is_infra_file
from .llm.client import get_async_openai_client
from .infra.external_io_runtime import run_openai_io_async
from .infra.fs_runtime import run_fs_io_async
from .logging import get_logger
from .models import (
    ApiCall,
    ApiCallMeta,
    ApiInclude,
    ApiRoute,
    ApiRouteContract,
    FileChunkEmbedding,
    FileEdge,
    FileNode,
    FileText,
    OrgEntitlement,
    OrgUsage,
    TsTypeDef,
)
from .resolve import resolve_spec
from .services.entitlements_service import get_entitlement_bool_async, get_entitlement_int_async
from .services.usage_service import check_and_increment_async
from .utils import (
    ProjectLockTimeout,
    _chunk_text,
    project_lock_async,
    resolve_under_root,
    sha256_text,
)

PARSE_CACHE_LIMIT = 256
_parse_cache: OrderedDict[Tuple[str, str, str], tuple[int, list[dict]]] = OrderedDict()
_parse_cache_lock = Lock()
logger = get_logger("stubgraph.scan")

EMBEDDING_CHUNKS_KIND = "embedding_chunks"
SCAN_STAGE_BATCH_SIZE = 128
SCAN_STAGE_MAX_PARALLEL = 8


@dataclass
class ScanRuntime:
    batch_size: int
    max_parallel: int

    @property
    def queue_size(self) -> int:
        return self.max_parallel


def get_scan_runtime() -> ScanRuntime:
    max_parallel = max(1, int(SCAN_STAGE_MAX_PARALLEL))
    return ScanRuntime(
        batch_size=max(1, int(SCAN_STAGE_BATCH_SIZE)),
        max_parallel=max_parallel,
    )


async def close_scan_runtime() -> None:
    return


async def _run_scan_batch(sync_fn, *args):
    return await run_fs_io_async(sync_fn, *args, operation="scan_batch")


def _today_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date()


@dataclass(frozen=True)
class FileSnapshot:
    mtime_ns: int
    size: int
    file_hash: str
    hash_kind: str


@dataclass
class PreparedScanData:
    present: list[str]
    removed: list[str]
    node_rows: list[dict]
    edge_map: dict[tuple[str, str, str], FileEdge]
    search_rows: list[dict]
    route_rows: list[dict]
    call_rows: list[dict]
    include_rows: list[dict]
    route_contract_rows: list[dict]
    call_meta_rows: list[dict]
    ts_type_rows: list[dict]
    embedding_rows: list[dict]
    embedding_paths_to_delete: list[str]
    removed_edge_neighbors: set[str]
    snapshot: dict[str, FileSnapshot]


@dataclass(frozen=True)
class FileStatResult:
    rel: str
    exists: bool
    is_file: bool
    is_supported: bool
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class FileReadResult:
    rel: str
    text: str | None
    mtime_ns: int
    size: int
    oversized: bool


def _get_cached_parse(lang: str, file_hash: str, file_suffix: str) -> tuple[int, list[dict]] | None:
    key = (lang, file_hash, file_suffix)
    with _parse_cache_lock:
        cached = _parse_cache.get(key)
        if cached:
            _parse_cache.move_to_end(key)
        return cached


def _store_cached_parse(
    lang: str,
    file_hash: str,
    file_suffix: str,
    complexity: int,
    imports: list[dict],
) -> None:
    key = (lang, file_hash, file_suffix)
    with _parse_cache_lock:
        _parse_cache[key] = (complexity, imports)
        _parse_cache.move_to_end(key)
        if len(_parse_cache) > PARSE_CACHE_LIMIT:
            _parse_cache.popitem(last=False)


IGNORE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".turbo",
    ".nuxt",
    ".output",
}

ALLOWED_DOT_DIRS = {
    ".github",
    ".config",
}

CODE_EXTS = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".mts",
    ".cts",
    ".vue",
    ".json",
    ".go",
    ".java",
    ".kt",
    ".rs",
    ".rb",
    ".php",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
}

TS_TYPEDEF_EXTS = (".ts", ".tsx", ".mts", ".cts")

SEARCH_INDEX_MAX_CHARS = 200_000


def _is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in CODE_EXTS or is_infra_file(path)


def iter_code_files(root: Path) -> Iterable[Path]:
    """Yield supported files, skipping IGNORE_DIRS and non-allowlisted dot-directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in IGNORE_DIRS and (not d.startswith(".") or d in ALLOWED_DOT_DIRS)
        )
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if _is_supported_file(p) and p.is_file():
                yield p


def _chunks(seq: list[str], size: int = 400) -> list[list[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


async def _collect_file_stats_async(
    project_root: Path,
    rel_paths: list[str],
    precomputed_stats: dict[str, tuple[int, int]] | None = None,
    batch_size: int = SCAN_STAGE_BATCH_SIZE,
    max_parallel: int = SCAN_STAGE_MAX_PARALLEL,
) -> list[FileStatResult]:
    runtime = get_scan_runtime()
    batch_size = max(1, int(batch_size or runtime.batch_size))
    max_parallel = max(1, int(max_parallel or runtime.max_parallel))

    def _sync_collect_batch(batch: list[str]) -> list[FileStatResult]:
        batch_results: list[FileStatResult] = []
        for rel in batch:
            p = project_root / rel
            exists = p.exists()
            is_file = p.is_file() if exists else False
            is_supported = _is_supported_file(p) if is_file else False
            if precomputed_stats and rel in precomputed_stats:
                mtime_ns, size = precomputed_stats[rel]
                batch_results.append(
                    FileStatResult(
                        rel=rel,
                        exists=exists,
                        is_file=is_file,
                        is_supported=is_supported,
                        mtime_ns=int(mtime_ns),
                        size=int(size),
                    )
                )
                continue
            try:
                st = p.stat()
                batch_results.append(
                    FileStatResult(
                        rel=rel,
                        exists=exists,
                        is_file=is_file,
                        is_supported=is_supported,
                        mtime_ns=int(st.st_mtime_ns),
                        size=int(st.st_size),
                    )
                )
            except OSError:
                batch_results.append(
                    FileStatResult(
                        rel=rel,
                        exists=exists,
                        is_file=is_file,
                        is_supported=is_supported,
                        mtime_ns=0,
                        size=0,
                    )
                )
        return batch_results

    batches = [rel_paths[i : i + batch_size] for i in range(0, len(rel_paths), batch_size)]
    semaphore = asyncio.Semaphore(max_parallel)

    async def _run(index: int, batch: list[str]) -> tuple[int, list[FileStatResult]]:
        async with semaphore:
            return index, await _run_scan_batch(_sync_collect_batch, batch)

    indexed = await asyncio.gather(*(_run(index, batch) for index, batch in enumerate(batches)))
    indexed.sort(key=lambda item: item[0])
    return [item for _, batch in indexed for item in batch]


async def _read_file_batch_async(
    project_root: Path,
    batch_paths: list[str],
    stats_map: dict[str, tuple[int, int]],
    max_file_bytes: int,
    max_parallel: int = SCAN_STAGE_MAX_PARALLEL,
) -> list[FileReadResult]:
    runtime = get_scan_runtime()
    batch_size = runtime.batch_size
    max_parallel = max(1, int(max_parallel or runtime.max_parallel))

    def _sync_read_batch(paths: list[str]) -> list[FileReadResult]:
        out: list[FileReadResult] = []
        for rel in paths:
            p = project_root / rel
            stat_mtime_ns, stat_size = stats_map.get(rel, (0, 0))
            oversized = max_file_bytes > 0 and int(stat_size) > max_file_bytes
            if oversized:
                out.append(FileReadResult(rel=rel, text=None, mtime_ns=int(stat_mtime_ns), size=int(stat_size), oversized=True))
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = None
            out.append(
                FileReadResult(
                    rel=rel,
                    text=text,
                    mtime_ns=int(stat_mtime_ns),
                    size=int(stat_size),
                    oversized=False,
                )
            )
        return out

    batches = [batch_paths[i : i + batch_size] for i in range(0, len(batch_paths), batch_size)]
    semaphore = asyncio.Semaphore(max_parallel)

    async def _run(index: int, batch: list[str]) -> tuple[int, list[FileReadResult]]:
        async with semaphore:
            return index, await _run_scan_batch(_sync_read_batch, batch)

    indexed = await asyncio.gather(*(_run(index, batch) for index, batch in enumerate(batches)))
    indexed.sort(key=lambda item: item[0])
    return [item for _, batch in indexed for item in batch]


async def _parse_index_batch_async(
    project_id: int,
    project_root: Path,
    file_batch: list[FileReadResult],
) -> list[dict]:
    def _sync_parse() -> list[dict]:
        parsed: list[dict] = []
        js_ts_exts = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
        for file_item in file_batch:
            rel = file_item.rel
            text = file_item.text
            stat_mtime_ns = file_item.mtime_ns
            stat_size = file_item.size
            stat_mtime = float(stat_mtime_ns) / 1_000_000_000 if stat_mtime_ns else 0.0
            if file_item.oversized:
                idx = pick_indexer(rel)
                lang = idx.language()
                file_hash = sha256_text(f"oversized:{stat_size}:{stat_mtime_ns}")
                parsed.append(
                    {
                        "rel": rel,
                        "stat_mtime": stat_mtime,
                        "stat_mtime_ns": int(stat_mtime_ns),
                        "stat_size": int(stat_size),
                        "file_hash": file_hash,
                        "snapshot_kind": "oversized",
                        "node_row": {
                            "project_id": project_id,
                            "path": rel,
                            "language": lang,
                            "loc": 0,
                            "complexity": 0,
                            "file_hash": file_hash,
                            "file_mtime": float(stat_mtime),
                            "file_mtime_ns": int(stat_mtime_ns),
                            "file_size": int(stat_size),
                        },
                        "search_row": None,
                        "cached_imports": [],
                        "route_rows": [],
                        "call_rows": [],
                        "include_rows": [],
                        "route_contract_rows": [],
                        "call_meta_rows": [],
                        "ts_type_rows": [],
                        "text": None,
                    }
                )
                continue
            if text is None:
                parsed.append(
                    {
                        "rel": rel,
                        "stat_mtime": stat_mtime,
                        "stat_mtime_ns": int(stat_mtime_ns),
                        "stat_size": int(stat_size),
                        "file_hash": "",
                        "snapshot_kind": "stat_only",
                        "node_row": None,
                        "search_row": None,
                        "cached_imports": [],
                        "route_rows": [],
                        "call_rows": [],
                        "include_rows": [],
                        "route_contract_rows": [],
                        "call_meta_rows": [],
                        "ts_type_rows": [],
                        "text": None,
                    }
                )
                continue

            rel_l = rel.lower()
            route_rows: list[dict] = []
            call_rows: list[dict] = []
            include_rows: list[dict] = []
            route_contract_rows: list[dict] = []
            call_meta_rows: list[dict] = []
            ts_type_rows: list[dict] = []
            if rel_l.endswith(".py"):
                routes_here = []
                try:
                    routes_here = extract_fastapi_routes(rel, text) or []
                except Exception:
                    routes_here = []
                for r in routes_here:
                    if not isinstance(r, dict):
                        continue
                    r.setdefault("project_id", int(project_id))
                    r.setdefault("source_path", rel)
                    route_rows.append(r)
                try:
                    route_contract_rows.extend(
                        extract_backend_route_contract_rows(project_id, rel, text, routes_here) or []
                    )
                except Exception:
                    pass
                raw_includes = []
                try:
                    raw_includes = extract_fastapi_includes(rel, text) or []
                except Exception:
                    raw_includes = []
                for inc in raw_includes:
                    if not isinstance(inc, dict):
                        continue
                    mod_spec = str(inc.get("child_module_spec") or "").strip()
                    child_src = ""
                    if mod_spec:
                        try:
                            child_src = resolve_spec(project_root, rel, mod_spec) or ""
                        except Exception:
                            child_src = ""
                    else:
                        child_src = rel
                    include_rows.append(
                        {
                            "project_id": int(project_id),
                            "parent_source_path": rel,
                            "parent_instance": str(inc.get("parent_instance") or ""),
                            "child_source_path": str(child_src or ""),
                            "child_instance": str(inc.get("child_instance") or ""),
                            "child_ref": str(inc.get("child_ref") or ""),
                            "child_module_spec": str(inc.get("child_module_spec") or ""),
                            "prefix": str(inc.get("prefix") or ""),
                            "lineno": int(inc.get("lineno") or 0),
                        }
                    )
            elif rel_l.endswith(js_ts_exts):
                calls_here = []
                try:
                    calls_here = extract_frontend_api_calls(rel, text) or []
                except Exception:
                    calls_here = []
                for c in calls_here:
                    if not isinstance(c, dict):
                        continue
                    c.setdefault("project_id", int(project_id))
                    c.setdefault("source_path", rel)
                    call_rows.append(c)
                try:
                    call_meta_rows.extend(extract_frontend_call_meta_rows(project_id, rel, text, calls_here) or [])
                except Exception:
                    pass
                if rel_l.endswith(TS_TYPEDEF_EXTS):
                    try:
                        rows = extract_ts_type_defs(project_id, rel, text) or []
                        for t in rows:
                            if not isinstance(t, dict):
                                continue
                            t.setdefault("project_id", int(project_id))
                            t.setdefault("source_path", rel)
                            ts_type_rows.append(t)
                    except Exception:
                        pass

            idx = pick_indexer(rel)
            lang = idx.language()
            file_hash = sha256_text(text)
            file_suffix = Path(rel).suffix.lower()
            loc = sum(1 for line in text.splitlines() if line.strip())
            cached = _get_cached_parse(lang, file_hash, file_suffix)
            if cached:
                complexity, cached_imports = cached
            else:
                complexity = idx.naive_complexity(text)
                cached_imports = []
                try:
                    for imp in idx.parse_imports(project_root / rel, text) or []:
                        cached_imports.append(
                            {
                                "spec": str(getattr(imp, "spec", "") or "").strip(),
                                "kind": str(getattr(imp, "kind", "import") or "import"),
                                "raw": str(getattr(imp, "raw", "") or ""),
                            }
                        )
                except Exception:
                    cached_imports = []
                _store_cached_parse(lang, file_hash, file_suffix, complexity, cached_imports)

            parsed.append(
                {
                    "rel": rel,
                    "stat_mtime": stat_mtime,
                    "stat_mtime_ns": int(stat_mtime_ns),
                    "stat_size": int(stat_size),
                    "file_hash": file_hash,
                    "snapshot_kind": "content",
                    "node_row": {
                        "project_id": project_id,
                        "path": rel,
                        "language": lang,
                        "loc": int(loc),
                        "complexity": int(complexity),
                        "file_hash": file_hash,
                        "file_mtime": float(stat_mtime),
                        "file_mtime_ns": int(stat_mtime_ns),
                        "file_size": int(stat_size),
                    },
                    "search_row": {"project_id": int(project_id), "path": rel, "content": text[:SEARCH_INDEX_MAX_CHARS]},
                    "cached_imports": cached_imports,
                    "route_rows": route_rows,
                    "call_rows": call_rows,
                    "include_rows": include_rows,
                    "route_contract_rows": route_contract_rows,
                    "call_meta_rows": call_meta_rows,
                    "ts_type_rows": ts_type_rows,
                    "text": text,
                }
            )
        return parsed

    return await _run_scan_batch(_sync_parse)


def _is_missing_table_error(e: Exception, table: str) -> bool:
    msg = str(e).lower()
    return (("no such table" in msg) or ("does not exist" in msg) or ("relation" in msg)) and (
        table.lower() in msg
    )


def _symbol_chunks(text: str, symbols: Iterable[object]) -> list[dict]:
    lines = text.splitlines(keepends=True)
    chunks: list[dict] = []
    for sym in symbols:
        start_line = int(getattr(sym, "start_line", 0) or 0)
        end_line = int(getattr(sym, "end_line", 0) or 0)
        chunk_text = ""
        if start_line > 0 and end_line >= start_line:
            chunk_text = "".join(lines[start_line - 1 : end_line])
        chunks.append(
            {
                "text": chunk_text,
                "symbol_name": str(getattr(sym, "name", "") or ""),
                "symbol_start_line": start_line,
                "symbol_end_line": end_line,
            }
        )
    return chunks


def _verify_scan_snapshot(
    project_root: Path,
    snapshot: dict[str, FileSnapshot],
    removed: list[str],
) -> tuple[bool, str]:
    for rel in removed:
        if (project_root / rel).exists():
            return False, f"removed_path_exists:{rel}"
    for rel, snap in snapshot.items():
        p = project_root / rel
        try:
            st = p.stat()
        except OSError:
            return False, f"missing:{rel}"
        if int(st.st_mtime_ns) != int(snap.mtime_ns) or int(st.st_size) != int(snap.size):
            return False, f"stat_changed:{rel}"
        if snap.hash_kind == "content":
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return False, f"read_failed:{rel}"
            if sha256_text(text) != snap.file_hash:
                return False, f"hash_changed:{rel}"
        elif snap.hash_kind == "oversized":
            if sha256_text(f"oversized:{snap.size}:{snap.mtime_ns}") != snap.file_hash:
                return False, f"hash_changed:{rel}"
        elif snap.hash_kind == "stat_only":
            continue
        else:
            return False, f"unknown_hash_kind:{rel}"
    return True, ""


async def _verify_scan_snapshot_async(
    project_root: Path,
    snapshot: dict[str, FileSnapshot],
    removed: list[str],
    *,
    batch_size: int = SCAN_STAGE_BATCH_SIZE,
    max_parallel: int = SCAN_STAGE_MAX_PARALLEL,
) -> tuple[bool, str]:
    runtime = get_scan_runtime()
    batch_size = max(1, int(batch_size or runtime.batch_size))
    max_parallel = max(1, int(max_parallel or runtime.max_parallel))
    semaphore = asyncio.Semaphore(max_parallel)

    def _check_removed_batch(batch: list[str]) -> tuple[bool, str]:
        for rel in batch:
            if (project_root / rel).exists():
                return False, f"removed_path_exists:{rel}"
        return True, ""

    def _check_snapshot_batch(batch: list[tuple[str, FileSnapshot]]) -> tuple[bool, str]:
        for rel, snap in batch:
            p = project_root / rel
            try:
                st = p.stat()
            except OSError:
                return False, f"missing:{rel}"
            if int(st.st_mtime_ns) != int(snap.mtime_ns) or int(st.st_size) != int(snap.size):
                return False, f"stat_changed:{rel}"
            if snap.hash_kind == "content":
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    return False, f"read_failed:{rel}"
                if sha256_text(text) != snap.file_hash:
                    return False, f"hash_changed:{rel}"
            elif snap.hash_kind == "oversized":
                if sha256_text(f"oversized:{snap.size}:{snap.mtime_ns}") != snap.file_hash:
                    return False, f"hash_changed:{rel}"
            elif snap.hash_kind == "stat_only":
                continue
            else:
                return False, f"unknown_hash_kind:{rel}"
        return True, ""

    async def _run(sync_fn, batch):
        async with semaphore:
            return await _run_scan_batch(sync_fn, batch)

    for i in range(0, len(removed), batch_size):
        ok, reason = await _run(_check_removed_batch, removed[i : i + batch_size])
        if not ok:
            return ok, reason

    snapshot_items = list(snapshot.items())
    for i in range(0, len(snapshot_items), batch_size):
        ok, reason = await _run(_check_snapshot_batch, snapshot_items[i : i + batch_size])
        if not ok:
            return ok, reason

    return True, ""


async def _search_index_delete_async(session: AsyncSession, project_id: int, paths: list[str]) -> None:
    if not paths:
        return
    stmt = delete(FileText).where(
        FileText.project_id == project_id,
        FileText.path.in_(bindparam("paths", expanding=True)),
    )
    for chunk in _chunks(paths, 400):
        await session.execute(stmt, {"paths": chunk})


async def _delete_embeddings_async(session: AsyncSession, project_id: int, paths: list[str]) -> None:
    if not paths:
        return
    for chunk in _chunks(paths, 400):
        await session.execute(
            delete(FileChunkEmbedding).where(
                FileChunkEmbedding.project_id == project_id,
                FileChunkEmbedding.path.in_(chunk),
            )
        )


async def _delete_api_indexes_async(session: AsyncSession, project_id: int, paths: list[str]) -> None:
    if not paths:
        return
    for chunk in _chunks(paths, 400):
        await session.execute(
            delete(ApiRoute).where(
                ApiRoute.project_id == project_id,
                ApiRoute.source_path.in_(chunk),
            )
        )
        await session.execute(
            delete(ApiCall).where(
                ApiCall.project_id == project_id,
                ApiCall.source_path.in_(chunk),
            )
        )
        await session.execute(
            delete(ApiRouteContract).where(
                ApiRouteContract.project_id == project_id,
                ApiRouteContract.source_path.in_(chunk),
            )
        )
        await session.execute(
            delete(ApiCallMeta).where(
                ApiCallMeta.project_id == project_id,
                ApiCallMeta.source_path.in_(chunk),
            )
        )
        await session.execute(
            delete(TsTypeDef).where(
                TsTypeDef.project_id == project_id,
                TsTypeDef.source_path.in_(chunk),
            )
        )
        await session.execute(
            delete(ApiInclude).where(
                ApiInclude.project_id == project_id,
                (ApiInclude.parent_source_path.in_(chunk))
                | (ApiInclude.child_source_path.in_(chunk)),
            )
        )


async def scan_project_async(project_id: int, org_id: int, project_root: Path) -> dict:
    project_root = project_root.resolve()
    scan_metrics: dict[str, dict[str, float | int]] = {
        "producer": {
            "duration_s": 0.0,
            "batches": 0,
            "paths": 0,
        },
        "read": {"duration_s": 0.0, "batches": 0, "files": 0},
        "parse": {"duration_s": 0.0, "batches": 0, "files": 0},
        "db": {"duration_s": 0.0, "batches": 0},
    }
    try:
        async with AsyncSessionLocal() as session:
            existing = (
                await session.execute(
                    select(
                        FileNode.path,
                        FileNode.file_mtime,
                        FileNode.file_mtime_ns,
                        FileNode.file_size,
                        FileNode.file_hash,
                    ).where(FileNode.project_id == project_id)
                )
            ).all()

        existing_map: dict[str, tuple[int, int, str]] = {}
        for row in existing:
            if isinstance(row, tuple) and len(row) >= 5:
                path, mtime, mtime_ns, size, h = row[0], row[1], row[2], row[3], row[4]
            else:
                path = getattr(row, "path", "")
                mtime = getattr(row, "file_mtime", 0)
                mtime_ns = getattr(row, "file_mtime_ns", 0)
                size = getattr(row, "file_size", 0)
                h = getattr(row, "file_hash", "")
            if isinstance(path, str) and path:
                resolved_mtime_ns = int(mtime_ns or 0)
                if not resolved_mtime_ns:
                    resolved_mtime_ns = int(float(mtime or 0) * 1_000_000_000)
                existing_map[path] = (resolved_mtime_ns, int(size or 0), str(h or ""))

        existing_keys = set(existing_map.keys())
        seen_paths: set[str] = set()
        candidate_set: set[str] = set()
        candidates: list[str] = []
        candidate_stats: dict[str, tuple[int, int]] = {}
        hash_verify_max_bytes = int(
            settings.scan_hash_verify_max_file_bytes or settings.snapshot_max_file_bytes
        )

        def _mark_candidate(rel: str, mtime_ns: int, size: int) -> None:
            if rel not in candidate_set:
                candidate_set.add(rel)
                candidates.append(rel)
            candidate_stats[rel] = (int(mtime_ns), int(size))

        async def _process_path_batch(rel_batch: list[str]) -> None:
            if not rel_batch:
                return
            stat_results = await _collect_file_stats_async(
                project_root,
                rel_batch,
                batch_size=runtime.batch_size,
                max_parallel=runtime.max_parallel,
            )
            batch_stats = {item.rel: (item.mtime_ns, item.size) for item in stat_results}
            verify_paths: list[str] = []

            for rel in rel_batch:
                mtime_ns, size = batch_stats.get(rel, (0, 0))
                prev = existing_map.get(rel)
                if not prev:
                    _mark_candidate(rel, mtime_ns, size)
                    continue
                prev_mtime_ns, prev_size, prev_hash = prev
                if int(prev_size) != int(size) or int(prev_mtime_ns) != int(mtime_ns):
                    _mark_candidate(rel, mtime_ns, size)
                    continue
                if not prev_hash:
                    continue
                if hash_verify_max_bytes > 0 and int(size) > hash_verify_max_bytes:
                    oversized_hash = sha256_text(f"oversized:{size}:{mtime_ns}")
                    if oversized_hash != prev_hash:
                        _mark_candidate(rel, mtime_ns, size)
                    continue
                verify_paths.append(rel)

            for i in range(0, len(verify_paths), runtime.batch_size):
                verify_batch = verify_paths[i : i + runtime.batch_size]
                read_results = await _read_file_batch_async(
                    project_root,
                    verify_batch,
                    batch_stats,
                    hash_verify_max_bytes,
                    max_parallel=runtime.max_parallel,
                )
                for item in read_results:
                    prev = existing_map.get(item.rel)
                    prev_hash = prev[2] if prev else ""
                    if item.text is None or sha256_text(item.text) != prev_hash:
                        _mark_candidate(item.rel, item.mtime_ns, item.size)
                await asyncio.sleep(0)

        runtime = get_scan_runtime()
        queue_size = runtime.queue_size
        sentinel = object()
        path_queue: asyncio.Queue[list[str] | object] = asyncio.Queue(maxsize=queue_size)
        limiter = asyncio.Semaphore(queue_size)

        def _collect_all_paths(root: Path) -> list[str]:
            return [path.relative_to(root).as_posix() for path in iter_code_files(root)]

        async def _produce_paths_async() -> None:
            producer_started = time.monotonic()
            try:
                rel_paths = await run_fs_io_async(_collect_all_paths, project_root, operation="scan_paths")
                for i in range(0, len(rel_paths), runtime.batch_size):
                    rel_batch = rel_paths[i : i + runtime.batch_size]
                    await limiter.acquire()
                    try:
                        await path_queue.put(rel_batch)
                    except BaseException:
                        limiter.release()
                        raise
                    scan_metrics["producer"]["batches"] += 1
                    scan_metrics["producer"]["paths"] += len(rel_batch)
            finally:
                while True:
                    try:
                        await asyncio.shield(path_queue.put(sentinel))
                        break
                    except asyncio.CancelledError:
                        if path_queue.full():
                            try:
                                dropped = path_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                await asyncio.sleep(0)
                            else:
                                if dropped is not sentinel:
                                    limiter.release()
                            continue
                        raise
                scan_metrics["producer"]["duration_s"] = (
                    scan_metrics["producer"].get("duration_s", 0.0) + time.monotonic() - producer_started
                )

        async def _consume_paths_async() -> None:
            while True:
                rel_batch = await path_queue.get()
                if rel_batch is sentinel:
                    break
                assert isinstance(rel_batch, list)
                try:
                    for rel in rel_batch:
                        seen_paths.add(rel)
                    await _process_path_batch(rel_batch)
                finally:
                    limiter.release()

        producer_task = asyncio.create_task(_produce_paths_async(), name=f"scan-producer-{project_id}")
        consumer_task = asyncio.create_task(_consume_paths_async(), name=f"scan-consumer-{project_id}")
        try:
            await asyncio.gather(producer_task, consumer_task)
        finally:
            for task in (producer_task, consumer_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(producer_task, consumer_task, return_exceptions=True)

        removed = sorted(existing_keys - seen_paths)
        sorted_candidates = sorted(candidates)

        updated = await scan_files_async(
            project_id,
            org_id,
            project_root,
            sorted_candidates,
            precomputed_stats=candidate_stats,
            scan_metrics=scan_metrics,
        )

        removed_aborted = False
        if removed and not updated.get("aborted"):
            async with AsyncSessionLocal() as session:
                async with project_lock_async(session, project_id):
                    ok, reason = await _verify_scan_snapshot_async(
                        project_root,
                        {},
                        removed,
                        batch_size=runtime.batch_size,
                        max_parallel=runtime.max_parallel,
                    )
                    if not ok:
                        logger.warning(
                            "scan_project snapshot mismatch before delete",
                            extra={"project_id": project_id, "reason": reason},
                        )
                        removed_aborted = True
                    else:
                        await session.execute(
                            delete(FileEdge).where(
                                FileEdge.project_id == project_id,
                                (FileEdge.src_path.in_(removed))
                                | (FileEdge.dst_path.in_(removed)),
                            )
                        )
                        await session.execute(
                            delete(FileNode).where(
                                FileNode.project_id == project_id,
                                FileNode.path.in_(removed),
                            )
                        )
                        try:
                            await _search_index_delete_async(session, project_id, removed)
                        except OperationalError as e:
                            if not _is_missing_table_error(e, "filetext"):
                                raise
                        try:
                            await _delete_embeddings_async(session, project_id, removed)
                        except OperationalError as e:
                            if not _is_missing_table_error(e, "filechunkembedding"):
                                raise
                        await session.commit()

    except (ProjectLockTimeout, LockedError) as exc:
        raise LockedError(f"Project {project_id} is locked by another operation") from exc

    result = {
        "nodes": len(seen_paths),
        "changed": len(sorted_candidates),
        "removed": len(removed),
        "scan_metrics": scan_metrics,
        **updated,
    }
    if removed_aborted:
        result["removed_aborted"] = True
        result["reason"] = "snapshot_mismatch"
    return result



async def scan_files_async(
    project_id: int,
    org_id: int,
    project_root: Path,
    rel_paths: Iterable[str],
    precomputed_stats: dict[str, tuple[int, int]] | None = None,
    scan_metrics: dict[str, dict[str, float | int]] | None = None,
) -> dict:
    project_root = project_root.resolve()
    norm_paths: list[str] = []
    for rp in rel_paths:
        try:
            _, rel_norm = resolve_under_root(project_root, str(rp))
        except Exception:
            continue
        norm_paths.append(rel_norm)
    norm_paths = sorted(set(norm_paths))
    if not norm_paths:
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    async with AsyncSessionLocal() as session:
        prepared = await _prepare_scan_files_async(
            session,
            project_id,
            org_id,
            project_root,
            norm_paths,
            precomputed_stats=precomputed_stats,
            scan_metrics=scan_metrics,
        )
        if not prepared.present and not prepared.removed:
            return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

        attempts = 0
        while True:
            attempts += 1
            async with project_lock_async(session, project_id):
                runtime = get_scan_runtime()
                ok, reason = await _verify_scan_snapshot_async(
                    project_root,
                    prepared.snapshot,
                    prepared.removed,
                    batch_size=runtime.batch_size,
                    max_parallel=runtime.max_parallel,
                )
                if not ok:
                    logger.warning(
                        "scan_files snapshot mismatch; aborting scan",
                        extra={
                            "project_id": project_id,
                            "reason": reason,
                            "attempt": attempts,
                        },
                    )
                    if attempts < 2:
                        prepared = await _prepare_scan_files_async(
                            session,
                            project_id,
                            org_id,
                            project_root,
                            norm_paths,
                            precomputed_stats=precomputed_stats,
                            scan_metrics=scan_metrics,
                        )
                        if not prepared.present and not prepared.removed:
                            return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}
                        continue
                    return {
                        "updated_nodes": 0,
                        "updated_edges": 0,
                        "removed": 0,
                        "aborted": True,
                        "reason": "snapshot_mismatch",
                    }
                await _write_scan_files_async(session, project_id, prepared, scan_metrics=scan_metrics)
                break

    return {
        "updated_nodes": len(prepared.node_rows),
        "updated_edges": len(prepared.edge_map),
        "removed": len(prepared.removed),
        "removed_edge_neighbors": sorted(prepared.removed_edge_neighbors),
    }


async def _prepare_scan_files_async(
    session: AsyncSession,
    project_id: int,
    org_id: int,
    project_root: Path,
    norm_paths: list[str],
    precomputed_stats: dict[str, tuple[int, int]] | None = None,
    scan_metrics: dict[str, dict[str, float | int]] | None = None,
) -> PreparedScanData:
    present: list[str] = []
    removed: list[str] = []
    runtime = get_scan_runtime()
    stat_results = await _collect_file_stats_async(
        project_root,
        norm_paths,
        precomputed_stats=precomputed_stats,
        batch_size=runtime.batch_size,
        max_parallel=runtime.max_parallel,
    )
    stats_map: dict[str, tuple[int, int]] = {}
    for item in stat_results:
        if not item.exists:
            removed.append(item.rel)
            continue
        if not item.is_file or not item.is_supported:
            continue
        present.append(item.rel)
        stats_map[item.rel] = (item.mtime_ns, item.size)

    node_rows: list[dict] = []
    edge_map: dict[tuple[str, str, str], FileEdge] = {}
    search_rows: list[dict] = []
    route_rows: list[dict] = []
    call_rows: list[dict] = []
    include_rows: list[dict] = []
    route_contract_rows: list[dict] = []
    call_meta_rows: list[dict] = []
    ts_type_rows: list[dict] = []
    embedding_rows: list[dict] = []
    embedding_paths_to_delete: list[str] = []
    embedding_hashes: dict[str, set[str]] = {}
    embedding_warned_missing_key = False
    embedding_warned_limit = False
    snapshot: dict[str, FileSnapshot] = {}

    ent_embeddings_enabled = await get_entitlement_bool_async(session, org_id, "embeddings_enabled")
    embeddings_enabled = bool(settings.embeddings_enabled) and ent_embeddings_enabled is not False
    if embeddings_enabled and present:
        try:
            rows = (
                await session.execute(
                    select(FileChunkEmbedding.path, FileChunkEmbedding.file_hash).where(
                        FileChunkEmbedding.project_id == project_id,
                        FileChunkEmbedding.path.in_(present),
                    )
                )
            ).all()
            for row in rows:
                if isinstance(row, tuple) and len(row) >= 2:
                    path, file_hash = row[0], row[1]
                else:
                    path = getattr(row, "path", "")
                    file_hash = getattr(row, "file_hash", "")
                if isinstance(path, str) and path:
                    embedding_hashes.setdefault(path, set()).add(str(file_hash or ""))
        except OperationalError as e:
            if not _is_missing_table_error(e, "filechunkembedding"):
                raise

    max_file_bytes = int(settings.snapshot_max_file_bytes)
    for i in range(0, len(present), runtime.batch_size):
        batch = present[i : i + runtime.batch_size]
        read_started = time.monotonic()
        read_batch = await _read_file_batch_async(
            project_root,
            batch,
            stats_map,
            max_file_bytes,
            max_parallel=runtime.max_parallel,
        )
        if scan_metrics is not None:
            scan_metrics.setdefault("read", {"duration_s": 0.0, "batches": 0, "files": 0})
            scan_metrics["read"]["duration_s"] += time.monotonic() - read_started
            scan_metrics["read"]["batches"] += 1
            scan_metrics["read"]["files"] += len(read_batch)

        parse_started = time.monotonic()
        parsed_batch = await _parse_index_batch_async(project_id, project_root, read_batch)
        if scan_metrics is not None:
            scan_metrics.setdefault("parse", {"duration_s": 0.0, "batches": 0, "files": 0})
            scan_metrics["parse"]["duration_s"] += time.monotonic() - parse_started
            scan_metrics["parse"]["batches"] += 1
            scan_metrics["parse"]["files"] += len(parsed_batch)

        for parsed in parsed_batch:
            rel = str(parsed["rel"])
            snapshot[rel] = FileSnapshot(
                mtime_ns=int(parsed["stat_mtime_ns"]),
                size=int(parsed["stat_size"]),
                file_hash=str(parsed["file_hash"]),
                hash_kind=str(parsed["snapshot_kind"]),
            )

            node_row = parsed.get("node_row")
            if node_row:
                node_rows.append(node_row)
            search_row = parsed.get("search_row")
            if search_row:
                search_rows.append(search_row)
            route_rows.extend(parsed.get("route_rows") or [])
            call_rows.extend(parsed.get("call_rows") or [])
            include_rows.extend(parsed.get("include_rows") or [])
            route_contract_rows.extend(parsed.get("route_contract_rows") or [])
            call_meta_rows.extend(parsed.get("call_meta_rows") or [])
            ts_type_rows.extend(parsed.get("ts_type_rows") or [])

            text = parsed.get("text")
            file_hash = str(parsed.get("file_hash") or "")
            if embeddings_enabled and isinstance(text, str) and text:
                existing_hashes = embedding_hashes.get(rel, set())
                if file_hash not in existing_hashes:
                    if not settings.openai_api_key:
                        if not embedding_warned_missing_key:
                            logger.warning("Embeddings enabled but OPENAI_API_KEY is not set; skipping embeddings.")
                            embedding_warned_missing_key = True
                    else:
                        idx = pick_indexer(rel)
                        chunks = _chunk_text(
                            text,
                            int(settings.embeddings_chunk_size),
                            int(settings.embeddings_chunk_overlap),
                        )
                        if chunks:
                            symbol_meta = await asyncio.to_thread(
                                lambda: _symbol_chunks(text, idx.parse_symbols(project_root / rel, text) or [])
                            )
                            client = get_async_openai_client()
                            try:
                                chunk_limit = await get_entitlement_int_async(
                                    session,
                                    org_id,
                                    "embeddings_daily_chunk_limit",
                                )
                                await check_and_increment_async(
                                    session,
                                    org_id,
                                    EMBEDDING_CHUNKS_KIND,
                                    len(chunks),
                                    int(chunk_limit)
                                    if chunk_limit is not None
                                    else settings.embeddings_daily_chunk_limit,
                                )
                                can_generate_embeddings = True
                            except LimitExceededError:
                                if not embedding_warned_limit:
                                    logger.warning("Embeddings daily chunk limit exceeded; skipping embeddings.")
                                    embedding_warned_limit = True
                                continue
                            try:
                                async with asyncio.timeout(float(settings.openai_timeout_seconds)):
                                    response = await run_openai_io_async(
                                        lambda: client.embeddings.create(
                                            model=settings.embeddings_model,
                                            input=chunks,
                                        ),
                                        kind="long",
                                    )
                            except asyncio.CancelledError:
                                raise
                            except Exception as e:  # noqa: BLE001
                                logger.warning(
                                    "Embeddings request failed for %s; skipping embeddings: %s",
                                    rel,
                                    e,
                                    exc_info=True,
                                )
                                continue
                            if can_generate_embeddings and existing_hashes:
                                embedding_paths_to_delete.append(rel)
                            for idx_chunk, item in enumerate(getattr(response, "data", []) or []):
                                embedding = getattr(item, "embedding", None)
                                if embedding is None:
                                    continue
                                meta = symbol_meta[idx_chunk] if idx_chunk < len(symbol_meta) else {}
                                embedding_rows.append(
                                    {
                                        "project_id": project_id,
                                        "path": rel,
                                        "chunk_index": idx_chunk,
                                        "file_hash": file_hash,
                                        "embedding_json": json.dumps(embedding),
                                        "symbol_name": str(meta.get("symbol_name", "")),
                                        "symbol_start_line": int(meta.get("symbol_start_line", 0) or 0),
                                        "symbol_end_line": int(meta.get("symbol_end_line", 0) or 0),
                                    }
                                )

            for imp in parsed.get("cached_imports") or []:
                if not isinstance(imp, dict):
                    continue
                spec = str(imp.get("spec") or "").strip()
                if not spec:
                    continue
                kind = str(imp.get("kind") or "import")
                if kind == "runtime_dynamic":
                    continue
                try:
                    dst_raw = resolve_spec(project_root, rel, spec)
                except Exception:
                    dst_raw = None
                if not dst_raw:
                    continue
                try:
                    _abs_dst, dst = resolve_under_root(project_root, str(dst_raw))
                except Exception:
                    continue
                if not dst or dst == rel:
                    continue
                raw = str(imp.get("raw") or "")
                key = (rel, dst, kind)
                if key not in edge_map:
                    edge_map[key] = FileEdge(
                        project_id=project_id,
                        src_path=rel,
                        dst_path=dst,
                        kind=kind,
                        raw=raw,
                    )

        await asyncio.sleep(0)

    removed_edge_neighbors: set[str] = set()
    if present or removed:
        rows = (
            await session.execute(
                select(FileEdge.src_path, FileEdge.dst_path).where(
                    FileEdge.project_id == project_id,
                    or_(
                        FileEdge.src_path.in_(present),
                        FileEdge.src_path.in_(removed),
                        FileEdge.dst_path.in_(removed),
                    ),
                )
            )
        ).all()
        for src, dst in rows:
            if isinstance(src, str) and src:
                removed_edge_neighbors.add(src)
            if isinstance(dst, str) and dst:
                removed_edge_neighbors.add(dst)

    return PreparedScanData(
        present=present,
        removed=removed,
        node_rows=node_rows,
        edge_map=edge_map,
        search_rows=search_rows,
        route_rows=route_rows,
        call_rows=call_rows,
        include_rows=include_rows,
        route_contract_rows=route_contract_rows,
        call_meta_rows=call_meta_rows,
        ts_type_rows=ts_type_rows,
        embedding_rows=embedding_rows,
        embedding_paths_to_delete=embedding_paths_to_delete,
        removed_edge_neighbors=removed_edge_neighbors,
        snapshot=snapshot,
    )



async def _write_scan_files_async(
    session: AsyncSession,
    project_id: int,
    prepared: PreparedScanData,
    scan_metrics: dict[str, dict[str, float | int]] | None = None,
) -> None:
    db_started = time.monotonic()
    if prepared.removed:
        await session.execute(
            delete(FileEdge).where(
                FileEdge.project_id == project_id,
                (FileEdge.src_path.in_(prepared.removed))
                | (FileEdge.dst_path.in_(prepared.removed)),
            )
        )
        await session.execute(
            delete(FileNode).where(
                FileNode.project_id == project_id,
                FileNode.path.in_(prepared.removed),
            )
        )
        try:
            await _delete_embeddings_async(session, project_id, prepared.removed)
        except OperationalError as e:
            if not _is_missing_table_error(e, "filechunkembedding"):
                raise

    try:
        to_del = sorted(set((prepared.present or []) + (prepared.removed or [])))
        if to_del:
            try:
                await _search_index_delete_async(session, project_id, to_del)
            except OperationalError as e:
                if not _is_missing_table_error(e, "filetext"):
                    raise
            try:
                await _delete_api_indexes_async(session, project_id, to_del)
            except OperationalError as e:
                if not (
                    _is_missing_table_error(e, "apiroute")
                    or _is_missing_table_error(e, "apicall")
                    or _is_missing_table_error(e, "apiinclude")
                    or _is_missing_table_error(e, "apiroutecontract")
                    or _is_missing_table_error(e, "apicallmeta")
                    or _is_missing_table_error(e, "tstypedef")
                ):
                    raise
        if prepared.embedding_paths_to_delete:
            try:
                await _delete_embeddings_async(
                    session,
                    project_id,
                    sorted(set(prepared.embedding_paths_to_delete)),
                )
            except OperationalError as e:
                if not _is_missing_table_error(e, "filechunkembedding"):
                    raise

        if prepared.search_rows:
            stmt_text = pg_insert(FileText).values(prepared.search_rows)
            stmt_text = stmt_text.on_conflict_do_update(
                index_elements=["project_id", "path"],
                set_={"content": stmt_text.excluded.content},
            )
            await session.execute(stmt_text)
        if prepared.route_rows:
            stmt_r = pg_insert(ApiRoute).values(prepared.route_rows)
            stmt_r = stmt_r.on_conflict_do_nothing(
                index_elements=[
                    "project_id",
                    "method",
                    "path",
                    "source_path",
                    "handler_name",
                    "lineno",
                ]
            )
            await session.execute(stmt_r)
        if prepared.call_rows:
            stmt_c = pg_insert(ApiCall).values(prepared.call_rows)
            stmt_c = stmt_c.on_conflict_do_nothing(
                index_elements=["project_id", "method", "path", "source_path", "lineno"]
            )
            await session.execute(stmt_c)
        if prepared.include_rows:
            stmt_i = pg_insert(ApiInclude).values(prepared.include_rows)
            stmt_i = stmt_i.on_conflict_do_nothing(
                index_elements=[
                    "project_id",
                    "parent_source_path",
                    "parent_instance",
                    "child_source_path",
                    "child_instance",
                    "prefix",
                    "lineno",
                ]
            )
            await session.execute(stmt_i)
        if prepared.route_contract_rows:
            stmt_rc = pg_insert(ApiRouteContract).values(prepared.route_contract_rows)
            stmt_rc = stmt_rc.on_conflict_do_update(
                index_elements=[
                    "project_id",
                    "method",
                    "path",
                    "source_path",
                    "handler_name",
                    "lineno",
                ],
                set_={"contract_json": stmt_rc.excluded.contract_json},
            )
            await session.execute(stmt_rc)
        if prepared.call_meta_rows:
            stmt_cm = pg_insert(ApiCallMeta).values(prepared.call_meta_rows)
            stmt_cm = stmt_cm.on_conflict_do_update(
                index_elements=["project_id", "method", "path", "source_path", "lineno"],
                set_={
                    "wrapper_name": stmt_cm.excluded.wrapper_name,
                    "wrapper_response_type": stmt_cm.excluded.wrapper_response_type,
                    "wrapper_body_type": stmt_cm.excluded.wrapper_body_type,
                    "wrapper_params_json": stmt_cm.excluded.wrapper_params_json,
                    "body_keys_json": stmt_cm.excluded.body_keys_json,
                    "notes": stmt_cm.excluded.notes,
                },
            )
            await session.execute(stmt_cm)
        if prepared.ts_type_rows:
            stmt_tt = pg_insert(TsTypeDef).values(prepared.ts_type_rows)
            stmt_tt = stmt_tt.on_conflict_do_update(
                index_elements=["project_id", "name", "source_path"],
                set_={
                    "kind": stmt_tt.excluded.kind,
                    "fields_json": stmt_tt.excluded.fields_json,
                },
            )
            await session.execute(stmt_tt)
        if prepared.embedding_rows:
            stmt_emb = pg_insert(FileChunkEmbedding).values(prepared.embedding_rows)
            stmt_emb = stmt_emb.on_conflict_do_nothing(
                index_elements=["project_id", "path", "chunk_index", "file_hash"]
            )
            try:
                await session.execute(stmt_emb)
            except OperationalError as e:
                if not _is_missing_table_error(e, "filechunkembedding"):
                    raise
    except Exception as e:
        await session.rollback()
        raise RuntimeError(f"scan_files: DB write failed: {e}") from e

    if prepared.present:
        await session.execute(
            delete(FileEdge).where(
                FileEdge.project_id == project_id,
                FileEdge.src_path.in_(prepared.present),
            )
        )

    if prepared.node_rows:
        stmt = pg_insert(FileNode).values(prepared.node_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["project_id", "path"],
            set_={
                "language": stmt.excluded.language,
                "loc": stmt.excluded.loc,
                "complexity": stmt.excluded.complexity,
                "file_hash": stmt.excluded.file_hash,
                "file_mtime": stmt.excluded.file_mtime,
                "file_mtime_ns": stmt.excluded.file_mtime_ns,
                "file_size": stmt.excluded.file_size,
            },
        )
        await session.execute(stmt)

    if prepared.edge_map:
        edge_rows = [
            {
                "project_id": e.project_id,
                "src_path": e.src_path,
                "dst_path": e.dst_path,
                "kind": e.kind,
                "raw": e.raw,
            }
            for e in prepared.edge_map.values()
        ]
        stmt_e = pg_insert(FileEdge).values(edge_rows)
        stmt_e = stmt_e.on_conflict_do_nothing(
            index_elements=["project_id", "src_path", "dst_path", "kind"]
        )
        await session.execute(stmt_e)

    await session.commit()
    if scan_metrics is not None:
        scan_metrics.setdefault("db", {"duration_s": 0.0, "batches": 0})
        scan_metrics["db"]["duration_s"] += time.monotonic() - db_started
        scan_metrics["db"]["batches"] += 1
