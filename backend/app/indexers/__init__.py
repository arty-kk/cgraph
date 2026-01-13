#backend/app/indexers/__init__.py
from __future__ import annotations

from .base import Indexer, ImportRef
from .python_indexer import PythonIndexer
from .js_ts_indexer import JsTsIndexer
from .go_indexer import GoIndexer
from .java_indexer import JavaIndexer
from .php_indexer import PhpIndexer
from .generic_indexer import GenericIndexer
from .infra_indexer import InfraIndexer, is_infra_file

__all__ = ["Indexer", "ImportRef", "pick_indexer"]

def pick_indexer(path: str) -> Indexer:
    p = (path or "").lower()

    if p.endswith((".py", ".pyi")):
        return PythonIndexer()
    if p.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue")):
        return JsTsIndexer()
    if p.endswith(".go"):
        return GoIndexer()
    if p.endswith(".java"):
        return JavaIndexer()
    if p.endswith(".php"):
        return PhpIndexer()
    if is_infra_file(p):
        return InfraIndexer()
    return GenericIndexer()
