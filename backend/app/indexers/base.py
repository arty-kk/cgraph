#backend/app/indexers/base.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

@dataclass(frozen=True)
class ImportRef:
    raw: str
    spec: str
    kind: str = "import"

@dataclass(frozen=True)
class SymbolDef:
    name: str
    kind: str
    signature: str = ""
    doc: str = ""
    start_line: int = 0
    end_line: int = 0

class Indexer(Protocol):
    def language(self) -> str: ...
    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]: ...
    def parse_exports(self, file_path: Path, text: str) -> list[str]: ...
    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]: ...
    def naive_complexity(self, text: str) -> int: ...
