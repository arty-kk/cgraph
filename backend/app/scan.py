# backend/app/scan.py
from __future__ import annotations

import json
import os
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
from .db import get_session
from .errors import LimitExceededError, LockedError
from .indexers import pick_indexer
from .indexers.infra_indexer import is_infra_file
from .llm.client import get_openai_client
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
    project_lock,
    project_lock_async,
    resolve_under_root,
    sha256_text,
)

PARSE_CACHE_LIMIT = 256
_parse_cache: OrderedDict[Tuple[str, str, str], tuple[int, list[dict]]] = OrderedDict()
_parse_cache_lock = Lock()
logger = get_logger("stubgraph.scan")

EMBEDDING_CHUNKS_KIND = "embedding_chunks"


def get_entitlement_bool(org_id: int, key: str) -> bool | None:
    with get_session() as session:
        row = session.exec(
            select(OrgEntitlement.value_bool).where(
                OrgEntitlement.org_id == org_id,
                OrgEntitlement.key == key,
            )
        ).first()
    return row[0] if isinstance(row, (tuple, list)) else row


def get_entitlement_int(org_id: int, key: str) -> int | None:
    with get_session() as session:
        row = session.exec(
            select(OrgEntitlement.value_int).where(
                OrgEntitlement.org_id == org_id,
                OrgEntitlement.key == key,
            )
        ).first()
    val = row[0] if isinstance(row, (tuple, list)) else row
    return int(val) if val is not None else None


def check_and_increment(org_id: int, kind: str, amount: int, limit: int | None) -> None:
    if amount <= 0:
        return
    if limit is not None and limit <= 0:
        raise LimitExceededError("Лимит использования исчерпан")
    day = _today_utc()
    with get_session() as session:
        with session.begin():
            insert_stmt = pg_insert(OrgUsage).values(org_id=org_id, day=day, kind=kind, count=0)
            insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["org_id", "day", "kind"])
            session.exec(insert_stmt)
            row = session.exec(
                select(OrgUsage)
                .where(OrgUsage.org_id == org_id, OrgUsage.day == day, OrgUsage.kind == kind)
                .with_for_update()
            ).one()
            current = int(row.count)
            if limit is not None and current + amount > limit:
                raise LimitExceededError(
                    "Превышен дневной лимит использования",
                    context={"kind": kind, "limit": limit},
                )
            row.count = current + amount
            session.add(row)


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


def _is_missing_table_error(e: Exception, table: str) -> bool:
    msg = str(e).lower()
    return (("no such table" in msg) or ("does not exist" in msg) or ("relation" in msg)) and (
        table.lower() in msg
    )


def _search_index_delete(session, project_id: int, paths: list[str]) -> None:
    if not paths:
        return
    stmt = delete(FileText).where(
        FileText.project_id == project_id,
        FileText.path.in_(bindparam("paths", expanding=True)),
    )
    for chunk in _chunks(paths, 400):
        session.exec(stmt, {"paths": chunk})


def _delete_embeddings(session, project_id: int, paths: list[str]) -> None:
    if not paths:
        return
    for chunk in _chunks(paths, 400):
        session.exec(
            delete(FileChunkEmbedding).where(
                FileChunkEmbedding.project_id == project_id,
                FileChunkEmbedding.path.in_(chunk),
            )
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


def _delete_api_indexes(session, project_id: int, paths: list[str]) -> None:
    if not paths:
        return
    for chunk in _chunks(paths, 400):
        session.exec(
            delete(ApiRoute).where(
                ApiRoute.project_id == project_id,
                ApiRoute.source_path.in_(chunk),
            )
        )
        session.exec(
            delete(ApiCall).where(
                ApiCall.project_id == project_id,
                ApiCall.source_path.in_(chunk),
            )
        )
        session.exec(
            delete(ApiRouteContract).where(
                ApiRouteContract.project_id == project_id,
                ApiRouteContract.source_path.in_(chunk),
            )
        )
        session.exec(
            delete(ApiCallMeta).where(
                ApiCallMeta.project_id == project_id,
                ApiCallMeta.source_path.in_(chunk),
            )
        )
        session.exec(
            delete(TsTypeDef).where(
                TsTypeDef.project_id == project_id,
                TsTypeDef.source_path.in_(chunk),
            )
        )
        session.exec(
            delete(ApiInclude).where(
                ApiInclude.project_id == project_id,
                (ApiInclude.parent_source_path.in_(chunk))
                | (ApiInclude.child_source_path.in_(chunk)),
            )
        )


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


def scan_project(project_id: int, org_id: int, project_root: Path) -> dict:
    project_root = project_root.resolve()
    try:
        with get_session() as s:
            existing = s.exec(
                select(
                    FileNode.path,
                    FileNode.file_mtime,
                    FileNode.file_mtime_ns,
                    FileNode.file_size,
                    FileNode.file_hash,
                ).where(FileNode.project_id == project_id)
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

        current_paths: list[str] = []
        stats_map: dict[str, tuple[int, int]] = {}
        for p in iter_code_files(project_root):
            rel = p.relative_to(project_root).as_posix()
            try:
                st = p.stat()
                stats_map[rel] = (int(st.st_mtime_ns), st.st_size)
            except Exception:
                stats_map[rel] = (0, 0)
            current_paths.append(rel)

        removed = sorted(set(existing_map.keys()) - set(current_paths))
        candidates: list[str] = []
        hash_verify_max_bytes = int(
            settings.scan_hash_verify_max_file_bytes or settings.snapshot_max_file_bytes
        )
        for rel in current_paths:
            mtime_ns, size = stats_map.get(rel, (0, 0))
            prev = existing_map.get(rel)
            if not prev:
                candidates.append(rel)
                continue
            prev_mtime_ns, prev_size, _prev_hash = prev
            if int(prev_size) != int(size) or int(prev_mtime_ns) != int(mtime_ns):
                candidates.append(rel)
                continue
            # Change detection: stat diff first, then optional hash verification
            # for unchanged stats (content hash for small files, oversized hash for large files).
            if not _prev_hash:
                continue
            if hash_verify_max_bytes > 0 and int(size) > hash_verify_max_bytes:
                oversized_hash = sha256_text(f"oversized:{size}:{mtime_ns}")
                if oversized_hash != _prev_hash:
                    candidates.append(rel)
                continue
            try:
                text = (project_root / rel).read_text(encoding="utf-8", errors="replace")
            except Exception:
                candidates.append(rel)
                continue
            if sha256_text(text) != _prev_hash:
                candidates.append(rel)

        updated = scan_files(
            project_id,
            org_id,
            project_root,
            candidates,
            precomputed_stats=stats_map,
        )

        removed_aborted = False
        if removed and not updated.get("aborted"):
            with project_lock(project_id):
                ok, reason = _verify_scan_snapshot(project_root, {}, removed)
                if not ok:
                    logger.warning(
                        "scan_project snapshot mismatch before delete",
                        extra={"project_id": project_id, "reason": reason},
                    )
                    removed_aborted = True
                else:
                    with get_session() as s:
                        s.exec(
                            delete(FileEdge).where(
                                FileEdge.project_id == project_id,
                                (FileEdge.src_path.in_(removed))
                                | (FileEdge.dst_path.in_(removed)),
                            )
                        )
                        s.exec(
                            delete(FileNode).where(
                                FileNode.project_id == project_id,
                                FileNode.path.in_(removed),
                            )
                        )
                        try:
                            _search_index_delete(s, project_id, removed)
                        except OperationalError as e:
                            if not _is_missing_table_error(e, "filetext"):
                                raise
                        try:
                            _delete_embeddings(s, project_id, removed)
                        except OperationalError as e:
                            if not _is_missing_table_error(e, "filechunkembedding"):
                                raise
                        try:
                            _delete_api_indexes(s, project_id, removed)
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
                        s.commit()
    except ProjectLockTimeout as exc:
        logger.warning("Project lock timeout during scan", extra={"project_id": project_id})
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc

    result = {
        "nodes": len(current_paths),
        "changed": len(candidates),
        "removed": len(removed),
        **updated,
    }
    if removed_aborted:
        result["removed_aborted"] = True
        result["reason"] = "snapshot_mismatch"
    return result


def scan_files(
    project_id: int,
    org_id: int,
    project_root: Path,
    rel_paths: Iterable[str],
    precomputed_stats: dict[str, tuple[int, int]] | None = None,
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

    prepared = _prepare_scan_files(
        project_id,
        org_id,
        project_root,
        norm_paths,
        precomputed_stats=precomputed_stats,
    )
    if not prepared.present and not prepared.removed:
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    attempts = 0
    while True:
        attempts += 1
        with project_lock(project_id):
            ok, reason = _verify_scan_snapshot(
                project_root,
                prepared.snapshot,
                prepared.removed,
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
                    prepared = _prepare_scan_files(
                        project_id,
                        org_id,
                        project_root,
                        norm_paths,
                        precomputed_stats=precomputed_stats,
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
            _write_scan_files(project_id, prepared)
            break

    return {
        "updated_nodes": len(prepared.node_rows),
        "updated_edges": len(prepared.edge_map),
        "removed": len(prepared.removed),
        "removed_edge_neighbors": sorted(prepared.removed_edge_neighbors),
    }




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

        current_paths: list[str] = []
        stats_map: dict[str, tuple[int, int]] = {}
        for p in iter_code_files(project_root):
            rel = p.relative_to(project_root).as_posix()
            try:
                st = p.stat()
                stats_map[rel] = (int(st.st_mtime_ns), st.st_size)
            except Exception:
                stats_map[rel] = (0, 0)
            current_paths.append(rel)

        removed = sorted(set(existing_map.keys()) - set(current_paths))
        candidates: list[str] = []
        hash_verify_max_bytes = int(
            settings.scan_hash_verify_max_file_bytes or settings.snapshot_max_file_bytes
        )
        for rel in current_paths:
            mtime_ns, size = stats_map.get(rel, (0, 0))
            prev = existing_map.get(rel)
            if not prev:
                candidates.append(rel)
                continue
            prev_mtime_ns, prev_size, _prev_hash = prev
            if int(prev_size) != int(size) or int(prev_mtime_ns) != int(mtime_ns):
                candidates.append(rel)
                continue
            if not _prev_hash:
                continue
            if hash_verify_max_bytes > 0 and int(size) > hash_verify_max_bytes:
                oversized_hash = sha256_text(f"oversized:{size}:{mtime_ns}")
                if oversized_hash != _prev_hash:
                    candidates.append(rel)
                continue
            try:
                text = (project_root / rel).read_text(encoding="utf-8", errors="replace")
            except Exception:
                candidates.append(rel)
                continue
            if sha256_text(text) != _prev_hash:
                candidates.append(rel)

        updated = await scan_files_async(
            project_id,
            org_id,
            project_root,
            candidates,
            precomputed_stats=stats_map,
        )

        removed_aborted = False
        if removed and not updated.get("aborted"):
            async with AsyncSessionLocal() as session:
                async with project_lock_async(session, project_id):
                    ok, reason = _verify_scan_snapshot(project_root, {}, removed)
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
                        try:
                            await _delete_api_indexes_async(session, project_id, removed)
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
                        await session.commit()
    except ProjectLockTimeout as exc:
        logger.warning("Project lock timeout during scan", extra={"project_id": project_id})
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc

    result = {
        "nodes": len(current_paths),
        "changed": len(candidates),
        "removed": len(removed),
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
        )
        if not prepared.present and not prepared.removed:
            return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

        attempts = 0
        while True:
            attempts += 1
            async with project_lock_async(session, project_id):
                ok, reason = _verify_scan_snapshot(
                    project_root,
                    prepared.snapshot,
                    prepared.removed,
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
                await _write_scan_files_async(session, project_id, prepared)
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
) -> PreparedScanData:
    present: list[str] = []
    removed: list[str] = []
    for rel in norm_paths:
        p = project_root / rel
        if not p.exists():
            removed.append(rel)
            continue
        if not p.is_file():
            continue
        if not _is_supported_file(p):
            continue
        present.append(rel)

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

    JS_TS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
    max_file_bytes = int(settings.snapshot_max_file_bytes)

    for rel in present:
        p = project_root / rel
        if precomputed_stats and rel in precomputed_stats:
            stat_mtime_ns, stat_size = precomputed_stats[rel]
        else:
            try:
                st = p.stat()
                stat_mtime_ns, stat_size = int(st.st_mtime_ns), st.st_size
            except OSError:
                stat_mtime_ns, stat_size = 0, 0
        stat_mtime = float(stat_mtime_ns) / 1_000_000_000 if stat_mtime_ns else 0.0
        oversized = max_file_bytes > 0 and int(stat_size) > max_file_bytes
        if oversized:
            idx = pick_indexer(rel)
            lang = idx.language()
            file_hash = sha256_text(f"oversized:{stat_size}:{stat_mtime_ns}")
            node_rows.append(
                {
                    "project_id": project_id,
                    "path": rel,
                    "language": lang,
                    "loc": 0,
                    "complexity": 0,
                    "file_hash": file_hash,
                    "file_mtime": float(stat_mtime),
                    "file_mtime_ns": int(stat_mtime_ns),
                    "file_size": int(stat_size),
                }
            )
            snapshot[rel] = FileSnapshot(
                mtime_ns=int(stat_mtime_ns),
                size=int(stat_size),
                file_hash=file_hash,
                hash_kind="oversized",
            )
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            snapshot[rel] = FileSnapshot(
                mtime_ns=int(stat_mtime_ns),
                size=int(stat_size),
                file_hash="",
                hash_kind="stat_only",
            )
            continue

        rel_l = rel.lower()
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
        elif rel_l.endswith(JS_TS_EXTS):
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
                call_meta_rows.extend(
                    extract_frontend_call_meta_rows(project_id, rel, text, calls_here) or []
                )
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
        file_suffix = p.suffix.lower()
        loc = sum(1 for line in text.splitlines() if line.strip())
        embed_text_len = len(text)

        search_rows.append({"project_id": int(project_id), "path": rel, "content": text[:SEARCH_INDEX_MAX_CHARS]})
        cached = _get_cached_parse(lang, file_hash, file_suffix)
        if cached:
            complexity, cached_imports = cached
        else:
            complexity = idx.naive_complexity(text)
            cached_imports = []
            try:
                for imp in idx.parse_imports(p, text) or []:
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

        node_rows.append(
            {
                "project_id": project_id,
                "path": rel,
                "language": lang,
                "loc": int(loc),
                "complexity": int(complexity),
                "file_hash": file_hash,
                "file_mtime": float(stat_mtime),
                "file_mtime_ns": int(stat_mtime_ns),
                "file_size": int(stat_size),
            }
        )
        snapshot[rel] = FileSnapshot(
            mtime_ns=int(stat_mtime_ns),
            size=int(stat_size),
            file_hash=file_hash,
            hash_kind="content",
        )

        if embeddings_enabled and embed_text_len > 0:
            existing_hashes = embedding_hashes.get(rel, set())
            if file_hash not in existing_hashes:
                if not settings.openai_api_key:
                    if not embedding_warned_missing_key:
                        logger.warning("Embeddings enabled but OPENAI_API_KEY is not set; skipping embeddings.")
                        embedding_warned_missing_key = True
                else:
                    chunks = _chunk_text(
                        text,
                        int(settings.embeddings_chunk_size),
                        int(settings.embeddings_chunk_overlap),
                    )
                    if chunks:
                        symbol_meta = _symbol_chunks(text, idx.parse_symbols(p, text) or [])
                        client = get_openai_client()
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
                            response = client.embeddings.create(
                                model=settings.embeddings_model,
                                input=chunks,
                            )
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

        for imp in cached_imports:
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
) -> None:
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


def _prepare_scan_files(
    project_id: int,
    org_id: int,
    project_root: Path,
    norm_paths: list[str],
    precomputed_stats: dict[str, tuple[int, int]] | None = None,
) -> PreparedScanData:
    present: list[str] = []
    removed: list[str] = []
    for rel in norm_paths:
        p = project_root / rel
        if not p.exists():
            removed.append(rel)
            continue
        if not p.is_file():
            continue
        # Allow infra files here; they are handled by InfraIndexer.
        if not _is_supported_file(p):
            continue
        present.append(rel)

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

    ent_embeddings_enabled = get_entitlement_bool(org_id, "embeddings_enabled")
    embeddings_enabled = bool(settings.embeddings_enabled) and ent_embeddings_enabled is not False
    if embeddings_enabled and present:
        with get_session() as s:
            try:
                rows = s.exec(
                    select(FileChunkEmbedding.path, FileChunkEmbedding.file_hash).where(
                        FileChunkEmbedding.project_id == project_id,
                        FileChunkEmbedding.path.in_(present),
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

    JS_TS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
    max_file_bytes = int(settings.snapshot_max_file_bytes)

    for rel in present:
        p = project_root / rel
        if precomputed_stats and rel in precomputed_stats:
            stat_mtime_ns, stat_size = precomputed_stats[rel]
        else:
            try:
                st = p.stat()
                stat_mtime_ns, stat_size = int(st.st_mtime_ns), st.st_size
            except OSError:
                stat_mtime_ns, stat_size = 0, 0
        stat_mtime = float(stat_mtime_ns) / 1_000_000_000 if stat_mtime_ns else 0.0
        oversized = max_file_bytes > 0 and int(stat_size) > max_file_bytes
        if oversized:
            idx = pick_indexer(rel)
            lang = idx.language()
            file_hash = sha256_text(f"oversized:{stat_size}:{stat_mtime_ns}")
            node_rows.append(
                {
                    "project_id": project_id,
                    "path": rel,
                    "language": lang,
                    "loc": 0,
                    "complexity": 0,
                    "file_hash": file_hash,
                    "file_mtime": float(stat_mtime),
                    "file_mtime_ns": int(stat_mtime_ns),
                    "file_size": int(stat_size),
                }
            )
            snapshot[rel] = FileSnapshot(
                mtime_ns=int(stat_mtime_ns),
                size=int(stat_size),
                file_hash=file_hash,
                hash_kind="oversized",
            )
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            snapshot[rel] = FileSnapshot(
                mtime_ns=int(stat_mtime_ns),
                size=int(stat_size),
                file_hash="",
                hash_kind="stat_only",
            )
            continue

        rel_l = rel.lower()
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

        elif rel_l.endswith(JS_TS_EXTS):
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
                call_meta_rows.extend(
                    extract_frontend_call_meta_rows(project_id, rel, text, calls_here) or []
                )
            except Exception:
                pass

            # TS typedefs are used for API contract comparison/fixes.
            # Do not rely on naming conventions.
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
        file_suffix = p.suffix.lower()
        loc = sum(1 for line in text.splitlines() if line.strip())
        embed_text_len = len(text)

        search_rows.append(
            {"project_id": int(project_id), "path": rel, "content": text[:SEARCH_INDEX_MAX_CHARS]}
        )
        cached = _get_cached_parse(lang, file_hash, file_suffix)
        if cached:
            complexity, cached_imports = cached
        else:
            complexity = idx.naive_complexity(text)
            cached_imports = []
            try:
                for imp in idx.parse_imports(p, text) or []:
                    spec = str(getattr(imp, "spec", "") or "").strip()
                    if not spec:
                        continue
                    cached_imports.append(
                        {
                            "spec": spec,
                            "kind": str(getattr(imp, "kind", "") or "import"),
                            "raw": str(getattr(imp, "raw", "") or ""),
                        }
                    )
            except Exception:
                cached_imports = []
            _store_cached_parse(lang, file_hash, file_suffix, complexity, cached_imports)
        node_rows.append(
            {
                "project_id": project_id,
                "path": rel,
                "language": lang,
                "loc": loc,
                "complexity": complexity,
                "file_hash": file_hash,
                "file_mtime": float(stat_mtime),
                "file_mtime_ns": int(stat_mtime_ns),
                "file_size": int(stat_size),
            }
        )
        snapshot[rel] = FileSnapshot(
            mtime_ns=int(stat_mtime_ns),
            size=int(stat_size),
            file_hash=file_hash,
            hash_kind="content",
        )

        if embeddings_enabled:
            existing_hashes = embedding_hashes.get(rel, set())
            should_embed = (
                embed_text_len > 0
                and embed_text_len <= settings.embeddings_max_file_chars
                and file_hash not in existing_hashes
            )
            can_generate_embeddings = False
            if should_embed:
                symbols: list[object] = []
                if p.suffix.lower() in CODE_EXTS:
                    try:
                        symbols = idx.parse_symbols(p, text) or []
                    except Exception:
                        symbols = []

                if symbols:
                    symbol_chunks = _symbol_chunks(text, symbols)
                    chunks = [chunk["text"] for chunk in symbol_chunks]
                    symbol_meta = [
                        {
                            "symbol_name": chunk["symbol_name"],
                            "symbol_start_line": chunk["symbol_start_line"],
                            "symbol_end_line": chunk["symbol_end_line"],
                        }
                        for chunk in symbol_chunks
                    ]
                else:
                    chunks = _chunk_text(
                        text,
                        settings.embeddings_chunk_size,
                        settings.embeddings_chunk_overlap,
                    )
                    symbol_meta = [
                        {
                            "symbol_name": "",
                            "symbol_start_line": 0,
                            "symbol_end_line": 0,
                        }
                        for _ in range(len(chunks))
                    ]

                if chunks:
                    if not settings.openai_api_key:
                        if not embedding_warned_missing_key:
                            logger.warning(
                                "Embeddings enabled but OPENAI_API_KEY is not set; "
                                "skipping embeddings."
                            )
                            embedding_warned_missing_key = True
                    else:
                        client = get_openai_client()
                        try:
                            chunk_limit = get_entitlement_int(
                                org_id, "embeddings_daily_chunk_limit"
                            )
                            check_and_increment(
                                org_id,
                                EMBEDDING_CHUNKS_KIND,
                                len(chunks),
                                chunk_limit
                                if chunk_limit is not None
                                else settings.embeddings_daily_chunk_limit,
                            )
                            can_generate_embeddings = True
                        except LimitExceededError:
                            if not embedding_warned_limit:
                                logger.warning(
                                    "Embeddings daily chunk limit exceeded; skipping embeddings."
                                )
                                embedding_warned_limit = True
                            continue
                        # Embeddings are best-effort and should not block core indexing.
                        try:
                            response = client.embeddings.create(
                                model=settings.embeddings_model,
                                input=chunks,
                            )
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

        for imp in cached_imports:
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

    removed_edge_neighbors: set[str] = set()

    with get_session() as s:
        if present or removed:
            rows = s.exec(
                select(FileEdge.src_path, FileEdge.dst_path).where(
                    FileEdge.project_id == project_id,
                    or_(
                        FileEdge.src_path.in_(present),
                        FileEdge.src_path.in_(removed),
                        FileEdge.dst_path.in_(removed),
                    ),
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


def _write_scan_files(project_id: int, prepared: PreparedScanData) -> None:
    with get_session() as s:
        if prepared.removed:
            s.exec(
                delete(FileEdge).where(
                    FileEdge.project_id == project_id,
                    (FileEdge.src_path.in_(prepared.removed))
                    | (FileEdge.dst_path.in_(prepared.removed)),
                )
            )
            s.exec(
                delete(FileNode).where(
                    FileNode.project_id == project_id,
                    FileNode.path.in_(prepared.removed),
                )
            )
            try:
                _delete_embeddings(s, project_id, prepared.removed)
            except OperationalError as e:
                if not _is_missing_table_error(e, "filechunkembedding"):
                    raise

        try:
            to_del = sorted(set((prepared.present or []) + (prepared.removed or [])))
            if to_del:
                try:
                    _search_index_delete(s, project_id, to_del)
                except OperationalError as e:
                    if not _is_missing_table_error(e, "filetext"):
                        raise
                try:
                    _delete_api_indexes(s, project_id, to_del)
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
                    _delete_embeddings(
                        s,
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
                s.exec(stmt_text)
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
                s.exec(stmt_r)
            if prepared.call_rows:
                stmt_c = pg_insert(ApiCall).values(prepared.call_rows)
                stmt_c = stmt_c.on_conflict_do_nothing(
                    index_elements=["project_id", "method", "path", "source_path", "lineno"]
                )
                s.exec(stmt_c)
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
                s.exec(stmt_i)
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
                s.exec(stmt_rc)
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
                s.exec(stmt_cm)
            if prepared.ts_type_rows:
                stmt_tt = pg_insert(TsTypeDef).values(prepared.ts_type_rows)
                stmt_tt = stmt_tt.on_conflict_do_update(
                    index_elements=["project_id", "name", "source_path"],
                    set_={
                        "kind": stmt_tt.excluded.kind,
                        "fields_json": stmt_tt.excluded.fields_json,
                    },
                )
                s.exec(stmt_tt)
            if prepared.embedding_rows:
                stmt_emb = pg_insert(FileChunkEmbedding).values(prepared.embedding_rows)
                stmt_emb = stmt_emb.on_conflict_do_nothing(
                    index_elements=["project_id", "path", "chunk_index", "file_hash"]
                )
                try:
                    s.exec(stmt_emb)
                except OperationalError as e:
                    if not _is_missing_table_error(e, "filechunkembedding"):
                        raise
        except Exception as e:
            s.rollback()
            raise RuntimeError(f"scan_files: DB write failed: {e}") from e

        if prepared.present:
            s.exec(
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
            s.exec(stmt)

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
            s.exec(stmt_e)

        s.commit()
