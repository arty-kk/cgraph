#backend/app/utils.py
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Tuple

def sha256_text(text: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    return h.hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def resolve_under_root(project_root: Path, rel_path: str) -> Tuple[Path, str]:
    root = project_root.resolve()

    rel = rel_path.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]

    abs_path = (root / rel).resolve()
    if root not in abs_path.parents and abs_path != root:
        raise ValueError("Path escapes project root")

    rel_norm = abs_path.relative_to(root).as_posix()
    return abs_path, rel_norm