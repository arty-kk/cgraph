#backend/app/context_pack.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlmodel import select
from .db import get_session
from .models import FileEdge
from .contracts import get_or_build_contract

@dataclass
class PackedContext:
    target_path: str
    files: list[dict]
    graph: dict

def _neighbors(project_id: int, start: str, depth: int) -> list[str]:
    if depth <= 0:
        return []

    visited: set[str] = {start}
    ordered: list[str] = []
    frontier: list[str] = [start]
    with get_session() as s:
        for _ in range(depth):
            if not frontier:
                break
            rows = s.exec(
                select(FileEdge.src_path, FileEdge.dst_path)
                .where(FileEdge.project_id == project_id, FileEdge.src_path.in_(frontier))
                .order_by(FileEdge.src_path, FileEdge.dst_path)
            ).all()
            nxt: list[str] = []
            for _src, dst in rows:
                if not isinstance(dst, str) or not dst:
                    continue
                if dst in visited:
                    continue
                visited.add(dst)
                ordered.append(dst)
                nxt.append(dst)
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
) -> PackedContext:
    project_root = project_root.resolve()
    p = project_root / target_rel
    target_text = p.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]

    deps = _neighbors(project_id, target_rel, depth)
    deps = deps[:max_files]

    files = [{"path": target_rel, "kind": "target", "content": target_text}]

    included_deps: list[str] = []
    for d in deps:
        try:
            if dep_mode == "full":
                dp = (project_root / d)
                if not dp.exists() or not dp.is_file():
                    continue
                t = dp.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]
                files.append({"path": d, "kind": "dep_full", "content": t})
            else:
                c = get_or_build_contract(project_id, project_root, d)
                files.append({"path": d, "kind": "dep_contract", "contract": c})
            included_deps.append(d)
        except Exception:
            continue

    graph = {"target": target_rel, "deps": included_deps}
    return PackedContext(target_path=target_rel, files=files, graph=graph)
