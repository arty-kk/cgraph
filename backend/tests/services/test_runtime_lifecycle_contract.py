import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra.runtime_lifecycle import build_cleanup_steps, build_startup_steps


def _step_names(steps):
    return [name for name, _ in steps]


def test_api_and_worker_startup_steps_match_contract() -> None:
    api_steps = _step_names(build_startup_steps(role="api"))
    worker_steps = _step_names(build_startup_steps(role="worker"))

    assert api_steps == worker_steps
    assert api_steps[:2] == ["init_redis_pool_async", "init_async_db"]
    assert "init_task_producer_runtime_async" in api_steps


def test_cleanup_order_keeps_dependency_safe_teardown() -> None:
    api_cleanup = _step_names(build_cleanup_steps(role="api"))
    worker_cleanup = _step_names(build_cleanup_steps(role="worker"))

    assert api_cleanup.index("close_redis_pool_async") < api_cleanup.index("close_async_db")
    assert worker_cleanup.index("close_redis_pool_async") < worker_cleanup.index("close_async_db")
    assert "close_task_producer_runtime_async" in api_cleanup
    assert "close_task_producer_runtime_async" in worker_cleanup
    assert "close_scan_runtime" in api_cleanup
    assert "close_scan_runtime" not in worker_cleanup
