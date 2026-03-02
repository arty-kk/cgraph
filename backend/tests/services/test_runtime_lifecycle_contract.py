import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra.runtime_lifecycle import build_cleanup_steps, build_startup_steps


def _step_names(steps):
    return [name for name, _ in steps]


def test_api_and_worker_startup_steps_match_contract() -> None:
    api_steps = _step_names(build_startup_steps(role="api"))
    assert api_steps
    assert api_steps[:2] == ["init_redis_pool_async", "init_async_db"]
    with pytest.raises(RuntimeError, match="ARQ migration"):
        build_startup_steps(role="worker")


def test_cleanup_order_keeps_dependency_safe_teardown() -> None:
    api_cleanup = _step_names(build_cleanup_steps(role="api"))

    assert api_cleanup.index("close_redis_pool_async") < api_cleanup.index("close_async_db")
    with pytest.raises(RuntimeError, match="ARQ migration"):
        build_cleanup_steps(role="worker")
    assert "close_scan_runtime" in api_cleanup
