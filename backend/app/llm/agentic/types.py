from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgenticMeta:
    full_file_paths: set[str] = field(default_factory=set)
    tool_calls: int = 0
    total_tool_output_chars: int = 0
    cache_hits: int = 0
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    retrieval_plan: dict | None = None
    self_check_ok: bool | None = None
    self_check_notes: list[str] = field(default_factory=list)
    self_check_missing_context: list[str] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    fs_ops_semaphore: asyncio.Semaphore | None = None
    cpu_ops_semaphore: asyncio.Semaphore | None = None
