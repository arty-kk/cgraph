#backend/app/context_pack.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlmodel import select
from .db import get_session
from .models import FileEdge, FileNode
from .contracts import get_or_build_contract

@dataclass
class PackedContext:
    target_path: str
    files: list[dict]
    graph: dict

def _neighbors(project_id: int, start: str, depth: int, direction: str = "out") -> list[str]:
    if depth <= 0:
        return []

    visited: set[str] = {start}
    ordered: list[str] = []
    frontier: list[str] = [start]
    with get_session() as s:
        for _ in range(depth):
            if not frontier:
                break
            if direction == "in":
                rows = s.exec(
                    select(FileEdge.src_path, FileEdge.dst_path)
                    .where(FileEdge.project_id == project_id, FileEdge.dst_path.in_(frontier))
                    .order_by(FileEdge.src_path, FileEdge.dst_path)
                ).all()
            else:
                rows = s.exec(
                    select(FileEdge.src_path, FileEdge.dst_path)
                    .where(FileEdge.project_id == project_id, FileEdge.src_path.in_(frontier))
                    .order_by(FileEdge.src_path, FileEdge.dst_path)
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

def pack_context(
    project_id: int,
    project_root: Path,
    target_rel: str,
    depth: int,
    dep_mode: str = "contracts",
    max_files: int = 25,
    max_chars_per_file: int = 12000,
    mode: str = "analyze",
    max_total_chars: int = 120000,
) -> PackedContext:
    project_root = project_root.resolve()
    p = project_root / target_rel
    target_text = p.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]

    exports: list[str] = []
    try:
        _contract = get_or_build_contract(project_id, project_root, target_rel)
        exports = [str(x) for x in _contract.get("exports", []) if isinstance(x, str)]
    except Exception:
        exports = []

    out_deps = _neighbors(project_id, target_rel, depth, direction="out")
    in_depth = max(0, min(depth, 2))
    in_deps = _neighbors(project_id, target_rel, in_depth, direction="in")

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

    def _add_file(path: str, kind: str) -> None:
        nonlocal total_chars
        if len(files) >= max_files:
            return
        if total_chars >= max_total_chars:
            return
        abs_p = project_root / path
        if not abs_p.exists() or not abs_p.is_file():
            return
        try:
            content = abs_p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        content = content[:max_chars_per_file]
        if total_chars + len(content) > max_total_chars:
            return
        total_chars += len(content)
        files.append({"path": path, "kind": kind, "content": content})

    files.append({"path": target_rel, "kind": "target", "content": target_text})
    total_chars += len(target_text)

    symbol_mentions: list[str] = []
    if exports:
        with get_session() as s:
            nodes = s.exec(
                select(FileNode.path)
                .where(FileNode.project_id == project_id)
                .order_by(FileNode.fan_in.desc())
                .limit(200)
            ).all()
        candidates = [r[0] if isinstance(r, (tuple, list)) else getattr(r, "path", "") for r in nodes]
        candidates = [c for c in candidates if isinstance(c, str) and c and c not in prioritized and c != target_rel]
        for c in candidates:
            try:
                text = (project_root / c).read_text(encoding="utf-8", errors="replace")
            except Exception:
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
                _add_file(d, "dep_full")
            else:
                c = get_or_build_contract(project_id, project_root, d)
                files.append({"path": d, "kind": "dep_contract", "contract": c})
        except Exception:
            continue

    graph = {"target": target_rel, "deps": ordered_deps, "inbound": in_deps, "outbound": out_deps}
    return PackedContext(target_path=target_rel, files=files, graph=graph)
