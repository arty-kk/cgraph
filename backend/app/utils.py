#backend/app/utils.py
from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Tuple

from .errors import PathValidationError

_PROJECT_LOCKS: dict[int, threading.Lock] = {}
_LOCK_GUARD = threading.Lock()


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


@contextmanager
def project_lock(project_id: int) -> Iterator[None]:

    with _LOCK_GUARD:
        lock = _PROJECT_LOCKS.setdefault(project_id, threading.Lock())

    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _normalize_rel_path(rel_path: str, max_length: int | None = None) -> str:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise PathValidationError("Относительный путь не должен быть пустым")

    rel = rel_path.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]

    if max_length is not None and len(rel) > max_length:
        raise PathValidationError("Слишком длинный относительный путь")
    return rel


def resolve_under_root(project_root: Path, rel_path: str, *, max_length: int | None = None) -> Tuple[Path, str]:
    root = project_root.resolve()

    rel = _normalize_rel_path(rel_path, max_length=max_length)

    abs_path = (root / rel).resolve()
    if root not in abs_path.parents and abs_path != root:
        raise PathValidationError(
            "Путь выходит за пределы корня проекта",
            context={"root": str(root), "path": rel},
        )

    rel_norm = abs_path.relative_to(root).as_posix()
    return abs_path, rel_norm


def normalize_project_root(root_path: str, *, max_length: int | None = None) -> Path:
    root = Path(root_path).expanduser().resolve()
    if max_length is not None and len(str(root)) > max_length:
        raise PathValidationError("Слишком длинный путь до корня проекта")
    if not root.exists():
        raise PathValidationError("Корневая директория проекта не существует")
    if not root.is_dir():
        raise PathValidationError("Корневой путь должен указывать на директорию")
    return root
