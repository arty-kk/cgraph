#backend/app/scan.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from sqlmodel import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .db import get_session
from .models import FileNode, FileEdge
from .indexers import pick_indexer
from .resolve import resolve_spec
from .utils import resolve_under_root

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", ".turbo"
}

CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".go", ".java", ".kt", ".rs", ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp"
}

def iter_code_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in CODE_EXTS and p.is_file():
                yield p


def scan_project(project_id: int, project_root: Path) -> dict:
    project_root = project_root.resolve()
    with get_session() as s:
        # clear old graph
        s.exec(delete(FileEdge).where(FileEdge.project_id == project_id))
        s.exec(delete(FileNode).where(FileNode.project_id == project_id))
        s.commit()

    node_rows: list[dict] = []
    edge_map: dict[tuple[str, str, str], FileEdge] = {}

    rel_paths: list[str] = []
    for p in iter_code_files(project_root):
        rel = p.relative_to(project_root).as_posix()
        rel_paths.append(rel)

    for rel in rel_paths:
        p = project_root / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        idx = pick_indexer(rel)
        loc = sum(1 for line in text.splitlines() if line.strip())
        complexity = idx.naive_complexity(text)
        node_rows.append({
            "project_id": project_id,
            "path": rel,
            "language": idx.language(),
            "loc": loc,
            "complexity": complexity,
        })

        for imp in idx.parse_imports(p, text):
            dst = resolve_spec(project_root, rel, imp.spec)
            if dst:
                if dst == rel:
                    continue
                key = (rel, dst, imp.kind)
                if key not in edge_map:
                    edge_map[key] = FileEdge(
                        project_id=project_id,
                        src_path=rel,
                        dst_path=dst,
                        kind=imp.kind,
                        raw=imp.raw,
                    )

    with get_session() as s:
        if node_rows:
            stmt = sqlite_insert(FileNode).values(node_rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["project_id", "path"])
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

    return {"nodes": len(node_rows), "edges": len(edge_map)}


def scan_files(project_id: int, project_root: Path, rel_paths: Iterable[str]) -> dict:

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
        if p.suffix.lower() not in CODE_EXTS:
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

    for rel in present:
        p = project_root / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        idx = pick_indexer(rel)
        loc = sum(1 for line in text.splitlines() if line.strip())
        complexity = idx.naive_complexity(text)
        node_rows.append({
            "project_id": project_id,
            "path": rel,
            "language": idx.language(),
            "loc": loc,
            "complexity": complexity,
        })

        for imp in idx.parse_imports(p, text):
            dst = resolve_spec(project_root, rel, imp.spec)
            if not dst or dst == rel:
                continue
            key = (rel, dst, imp.kind)
            if key not in edge_map:
                edge_map[key] = FileEdge(
                    project_id=project_id,
                    src_path=rel,
                    dst_path=dst,
                    kind=imp.kind,
                    raw=imp.raw,
                )

    with get_session() as s:
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