#backend/app/indexers/__init__.py
from __future__ import annotations

from .base import Indexer, ImportRef
from .python_indexer import PythonIndexer
from .js_ts_indexer import JsTsIndexer
from .generic_indexer import GenericIndexer

__all__ = ["Indexer", "ImportRef", "pick_indexer"]

def pick_indexer(path: str) -> Indexer:
    p = (path or "").lower()

    if p.endswith(".py"):
        return PythonIndexer()
    if p.endswith((".js", ".jsx", ".ts", ".tsx")):
        return JsTsIndexer()
    return GenericIndexer()
