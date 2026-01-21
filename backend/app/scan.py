#backend/app/scan.py
from __future__ import annotations

import os
import time

from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Iterable, Tuple
from sqlmodel import delete, select
from sqlalchemy import text as sa_text, bindparam
from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .db import get_session
from .models import FileNode, FileEdge, ApiRoute, ApiCall, ApiInclude, ApiRouteContract, ApiCallMeta, TsTypeDef
from .indexers import pick_indexer
from .indexers.infra_indexer import is_infra_file
from .resolve import resolve_spec
from .utils import resolve_under_root, sha256_text, project_lock
from .api_map import extract_fastapi_routes, extract_frontend_api_calls, extract_fastapi_includes
from .api_contracts import extract_backend_route_contract_rows, extract_frontend_call_meta_rows, extract_ts_type_defs


PARSE_CACHE_LIMIT = 256
_parse_cache: OrderedDict[Tuple[str, str], tuple[int, list[dict]]] = OrderedDict()
_parse_cache_lock = Lock()


def _get_cached_parse(lang: str, file_hash: str) -> tuple[int, list[dict]] | None:
    key = (lang, file_hash)
    with _parse_cache_lock:
        cached = _parse_cache.get(key)
        if cached:
            _parse_cache.move_to_end(key)
        return cached

def _store_cached_parse(lang: str, file_hash: str, complexity: int, imports: list[dict]) -> None:
    key = (lang, file_hash)
    with _parse_cache_lock:
        _parse_cache[key] = (complexity, imports)
        _parse_cache.move_to_end(key)
        if len(_parse_cache) > PARSE_CACHE_LIMIT:
            _parse_cache.popitem(last=False)

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", ".turbo", ".nuxt", ".output"
}

CODE_EXTS = {
    ".py", ".pyi",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue",
    ".go", ".java", ".kt", ".rs", ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp"
}

TS_TYPEDEF_EXTS = (".ts", ".tsx", ".mts", ".cts")

SEARCH_INDEX_MAX_CHARS = 200_000

def _is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in CODE_EXTS or is_infra_file(path)

def iter_code_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")
        )
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if _is_supported_file(p) and p.is_file():
                yield p

def _chunks(seq: list[str], size: int = 400) -> list[list[str]]:
    return [seq[i:i+size] for i in range(0, len(seq), size)]

def _is_missing_table_error(e: Exception, table: str) -> bool:
    msg = str(e).lower()
    return ("no such table" in msg) and (table.lower() in msg)

def _fts_delete(session, project_id: int, paths: list[str]) -> None:
    if not paths:
        return
    stmt = sa_text("DELETE FROM filetext_fts WHERE project_id=:pid AND path IN :paths").bindparams(
        bindparam("paths", expanding=True)
    )
    for chunk in _chunks(paths, 400):
        session.execute(stmt, {"pid": int(project_id), "paths": chunk})

def _delete_api_indexes(session, project_id: int, paths: list[str]) -> None:
    if not paths:
        return
    for chunk in _chunks(paths, 400):
        session.exec(
            delete(ApiRoute).where(ApiRoute.project_id == project_id, ApiRoute.source_path.in_(chunk))
        )
        session.exec(
            delete(ApiCall).where(ApiCall.project_id == project_id, ApiCall.source_path.in_(chunk))
        )
        session.exec(
            delete(ApiRouteContract).where(ApiRouteContract.project_id == project_id, ApiRouteContract.source_path.in_(chunk))
        )
        session.exec(
            delete(ApiCallMeta).where(ApiCallMeta.project_id == project_id, ApiCallMeta.source_path.in_(chunk))
        )
        session.exec(
            delete(TsTypeDef).where(TsTypeDef.project_id == project_id, TsTypeDef.source_path.in_(chunk))
        )
        session.exec(
            delete(ApiInclude).where(
                ApiInclude.project_id == project_id,
                (ApiInclude.parent_source_path.in_(chunk)) | (ApiInclude.child_source_path.in_(chunk)),
            )
        )

def scan_project(project_id: int, project_root: Path) -> dict:
    project_root = project_root.resolve()
    with project_lock(project_id):
        with get_session() as s:
            existing = s.exec(
                select(FileNode.path, FileNode.file_mtime, FileNode.file_size, FileNode.file_hash)
                .where(FileNode.project_id == project_id)
            ).all()

        existing_map: dict[str, tuple[float, int, str]] = {}
        for row in existing:
            if isinstance(row, tuple) and len(row) >= 4:
                path, mtime, size, h = row[0], row[1], row[2], row[3]
            else:
                path = getattr(row, "path", "")
                mtime = getattr(row, "file_mtime", 0)
                size = getattr(row, "file_size", 0)
                h = getattr(row, "file_hash", "")
            if isinstance(path, str) and path:
                existing_map[path] = (float(mtime or 0), int(size or 0), str(h or ""))

        current_paths: list[str] = []
        stats_map: dict[str, tuple[float, int]] = {}
        for p in iter_code_files(project_root):
            rel = p.relative_to(project_root).as_posix()
            try:
                st = p.stat()
                stats_map[rel] = (st.st_mtime, st.st_size)
            except Exception:
                stats_map[rel] = (time.time(), 0)
            current_paths.append(rel)

        removed = sorted(set(existing_map.keys()) - set(current_paths))
        candidates: list[str] = []
        for rel in current_paths:
            mtime, size = stats_map.get(rel, (0.0, 0))
            prev = existing_map.get(rel)
            if not prev:
                candidates.append(rel)
                continue
            prev_mtime, prev_size, _prev_hash = prev
            if int(prev_size) != int(size) or float(prev_mtime) != float(mtime):
                candidates.append(rel)

        updated = scan_files(project_id, project_root, candidates, precomputed_stats=stats_map)

        if removed:
            with get_session() as s:
                s.exec(
                    delete(FileEdge).where(
                        FileEdge.project_id == project_id,
                        (FileEdge.src_path.in_(removed)) | (FileEdge.dst_path.in_(removed)),
                    )
                )
                s.exec(delete(FileNode).where(FileNode.project_id == project_id, FileNode.path.in_(removed)))
                try:
                    _fts_delete(s, project_id, removed)
                except OperationalError as e:
                    if not _is_missing_table_error(e, "filetext_fts"):
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

        return {"nodes": len(current_paths), "changed": len(candidates), "removed": len(removed), **updated}


def scan_files(
    project_id: int,
    project_root: Path,
    rel_paths: Iterable[str],
    precomputed_stats: dict[str, tuple[float, int]] | None = None,
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

    present: list[str] = []
    removed: list[str] = []
    for rel in norm_paths:
        p = (project_root / rel)
        if not p.exists():
            removed.append(rel)
            continue
        if not p.is_file():
            continue
        # Allow infra files here; they are handled by InfraIndexer.
        if not _is_supported_file(p):
            continue
        present.append(rel)

    if removed:
        with get_session() as s:
            s.exec(
                delete(FileEdge).where(
                    FileEdge.project_id == project_id,
                    (FileEdge.src_path.in_(removed)) | (FileEdge.dst_path.in_(removed)),
                )
            )
            s.exec(delete(FileNode).where(FileNode.project_id == project_id, FileNode.path.in_(removed)))
            s.commit()

    node_rows: list[dict] = []
    edge_map: dict[tuple[str, str, str], FileEdge] = {}
    fts_rows: list[dict] = []
    route_rows: list[dict] = []
    call_rows: list[dict] = []
    include_rows: list[dict] = []
    route_contract_rows: list[dict] = []
    call_meta_rows: list[dict] = []
    ts_type_rows: list[dict] = []

    JS_TS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")

    for rel in present:
        p = project_root / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
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

            # TS typedefs are used for API contract comparison/fixes; do not rely on naming conventions.
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
        loc = sum(1 for line in text.splitlines() if line.strip())

        try:
            fts_rows.append({"project_id": int(project_id), "path": rel, "content": text[:SEARCH_INDEX_MAX_CHARS]})
        except Exception:
            pass

        cached = _get_cached_parse(lang, file_hash)
        if cached:
            complexity, cached_imports = cached
        else:
            complexity = idx.naive_complexity(text)
            cached_imports = []
            try:
                for imp in (idx.parse_imports(p, text) or []):
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
            _store_cached_parse(lang, file_hash, complexity, cached_imports)
        if precomputed_stats and rel in precomputed_stats:
            stat_mtime, stat_size = precomputed_stats[rel]
        else:
            try:
                st = p.stat()
                stat_mtime, stat_size = st.st_mtime, st.st_size
            except OSError:
                stat_mtime, stat_size = 0.0, 0
        node_rows.append({
            "project_id": project_id,
            "path": rel,
            "language": lang,
            "loc": loc,
            "complexity": complexity,
            "file_hash": file_hash,
            "file_mtime": float(stat_mtime),
            "file_size": int(stat_size),
        })

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

    with get_session() as s:
        try:
            to_del = sorted(set((present or []) + (removed or [])))
            if to_del:
                try:
                    _fts_delete(s, project_id, to_del)
                except OperationalError as e:
                    if not _is_missing_table_error(e, "filetext_fts"):
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
            if fts_rows:
                s.execute(
                    sa_text("INSERT INTO filetext_fts (project_id, path, content) VALUES (:project_id, :path, :content)"),
                    fts_rows,
                )
            if route_rows:
                stmt_r = sqlite_insert(ApiRoute).values(route_rows)
                stmt_r = stmt_r.on_conflict_do_nothing(
                    index_elements=["project_id", "method", "path", "source_path", "handler_name", "lineno"]
                )
                s.exec(stmt_r)
            if call_rows:
                stmt_c = sqlite_insert(ApiCall).values(call_rows)
                stmt_c = stmt_c.on_conflict_do_nothing(
                    index_elements=["project_id", "method", "path", "source_path", "lineno"]
                )
                s.exec(stmt_c)
            if include_rows:
                stmt_i = sqlite_insert(ApiInclude).values(include_rows)
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
            if route_contract_rows:
                stmt_rc = sqlite_insert(ApiRouteContract).values(route_contract_rows)
                stmt_rc = stmt_rc.on_conflict_do_update(
                    index_elements=["project_id", "method", "path", "source_path", "handler_name", "lineno"],
                    set_={"contract_json": stmt_rc.excluded.contract_json},
                )
                s.exec(stmt_rc)
            if call_meta_rows:
                stmt_cm = sqlite_insert(ApiCallMeta).values(call_meta_rows)
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
            if ts_type_rows:
                stmt_tt = sqlite_insert(TsTypeDef).values(ts_type_rows)
                stmt_tt = stmt_tt.on_conflict_do_update(
                    index_elements=["project_id", "name", "source_path"],
                    set_={
                        "kind": stmt_tt.excluded.kind,
                        "fields_json": stmt_tt.excluded.fields_json,
                    },
                )
                s.exec(stmt_tt)
        except Exception as e:
            s.rollback()
            raise RuntimeError(f"scan_files: DB write failed: {e}") from e

        if present:
            s.exec(
                delete(FileEdge).where(
                    FileEdge.project_id == project_id,
                    FileEdge.src_path.in_(present),
                )
            )

        if node_rows:
            stmt = sqlite_insert(FileNode).values(node_rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["project_id", "path"],
                set_={
                    "language": stmt.excluded.language,
                    "loc": stmt.excluded.loc,
                    "complexity": stmt.excluded.complexity,
                    "file_hash": stmt.excluded.file_hash,
                    "file_mtime": stmt.excluded.file_mtime,
                    "file_size": stmt.excluded.file_size,
                },
            )
            s.exec(stmt)

        if edge_map:
            edge_rows = [
                {
                    "project_id": e.project_id,
                    "src_path": e.src_path,
                    "dst_path": e.dst_path,
                    "kind": e.kind,
                    "raw": e.raw,
                }
                for e in edge_map.values()
            ]
            stmt_e = sqlite_insert(FileEdge).values(edge_rows)
            stmt_e = stmt_e.on_conflict_do_nothing(index_elements=["project_id", "src_path", "dst_path", "kind"])
            s.exec(stmt_e)

        s.commit()

    return {"updated_nodes": len(node_rows), "updated_edges": len(edge_map), "removed": len(removed)}
