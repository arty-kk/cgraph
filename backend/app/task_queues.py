"""Centralized task queue definitions and routing mapping."""

from __future__ import annotations

QUEUE_LIGHT = "light"
QUEUE_MEDIUM = "medium"
QUEUE_HEAVY = "heavy"

TASK_QUEUES: tuple[str, ...] = (QUEUE_LIGHT, QUEUE_MEDIUM, QUEUE_HEAVY)

TASK_QUEUE_BY_KIND: dict[str, str] = {
    "run_task": QUEUE_HEAVY,
    "scan": QUEUE_MEDIUM,
    "docs": QUEUE_LIGHT,
    "snapshot_import": QUEUE_MEDIUM,
    "mutation_indexing": QUEUE_MEDIUM,
}
