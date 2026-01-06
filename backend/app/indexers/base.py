#backend/app/indexers/base.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

@dataclass(frozen=True)
class ImportRef:
    raw: str
    spec: str
    kind: str = "import"

class Indexer(Protocol):
    def language(self) -> str: ...
    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]: ...
    def parse_exports(self, file_path: Path, text: str) -> list[str]: ...
    def naive_complexity(self, text: str) -> int: ...
