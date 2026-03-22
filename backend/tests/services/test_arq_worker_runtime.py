import importlib
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.task_queues import (
    QUEUE_HEAVY,
    QUEUE_LIGHT,
    QUEUE_MEDIUM,
    TASK_QUEUE_BY_KIND,
    TASK_QUEUES,
)


@pytest.mark.anyio
async def test_worker_settings_registers_stubgraph_tasks() -> None:
    from app import arq_worker

    names = {f.name for f in arq_worker.WorkerSettings.functions}

    assert "stubgraph.scan" in names
    assert "stubgraph.docs" in names
    assert "stubgraph.snapshot_import" in names
    assert "stubgraph.run_task" in names
    assert "stubgraph.mutation_indexing" in names


def test_worker_settings_queue_name_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUBGRAPH_ARQ_QUEUE", QUEUE_HEAVY)
    import app.arq_worker as arq_worker

    reloaded = importlib.reload(arq_worker)

    assert reloaded.WorkerSettings.queue_name == QUEUE_HEAVY
    assert reloaded.WorkerSettings.queue_names == (QUEUE_HEAVY,)


def test_worker_settings_queue_names_default_to_all_supported_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STUBGRAPH_ARQ_QUEUE", raising=False)
    monkeypatch.delenv("STUBGRAPH_ARQ_QUEUES", raising=False)
    import app.arq_worker as arq_worker

    reloaded = importlib.reload(arq_worker)

    assert reloaded.WorkerSettings.queue_names == TASK_QUEUES


def test_worker_settings_queue_names_come_from_env_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STUBGRAPH_ARQ_QUEUE", raising=False)
    monkeypatch.setenv("STUBGRAPH_ARQ_QUEUES", ",".join(TASK_QUEUES))
    import app.arq_worker as arq_worker

    reloaded = importlib.reload(arq_worker)

    assert reloaded.WorkerSettings.queue_names == TASK_QUEUES


def test_worker_settings_single_queue_env_has_priority_over_multi_queue_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUBGRAPH_ARQ_QUEUE", QUEUE_LIGHT)
    monkeypatch.setenv("STUBGRAPH_ARQ_QUEUES", ",".join(TASK_QUEUES))
    import app.arq_worker as arq_worker

    reloaded = importlib.reload(arq_worker)

    assert reloaded.WorkerSettings.queue_names == (QUEUE_LIGHT,)


def test_worker_settings_ignores_unknown_queues_from_multi_queue_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STUBGRAPH_ARQ_QUEUE", raising=False)
    monkeypatch.setenv("STUBGRAPH_ARQ_QUEUES", "light,unknown,medium")
    import app.arq_worker as arq_worker

    reloaded = importlib.reload(arq_worker)

    assert reloaded.WorkerSettings.queue_names == (QUEUE_LIGHT, QUEUE_MEDIUM)


def test_worker_settings_cron_jobs_disabled_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUBGRAPH_ARQ_ENABLE_CRON", "false")
    import app.arq_worker as arq_worker

    reloaded = importlib.reload(arq_worker)

    assert reloaded.WorkerSettings.cron_jobs == []


def test_worker_settings_use_arq_runtime_knobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUBGRAPH_ARQ_MAX_TRIES", "7")
    monkeypatch.setenv("STUBGRAPH_ARQ_JOB_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("STUBGRAPH_ARQ_KEEP_RESULT_SECONDS", "30")
    monkeypatch.setenv("STUBGRAPH_ARQ_POLL_DELAY_SECONDS", "0.2")
    import app.config as app_config
    import app.arq_worker as arq_worker

    importlib.reload(app_config)
    reloaded = importlib.reload(arq_worker)

    assert reloaded.WorkerSettings.max_tries == 7
    assert reloaded.WorkerSettings.job_timeout == 120
    assert reloaded.WorkerSettings.keep_result == 30
    assert reloaded.WorkerSettings.poll_delay == 0.2


def test_task_queue_mapping_contract_for_user_facing_tasks() -> None:
    assert TASK_QUEUE_BY_KIND["run_task"] == QUEUE_HEAVY
    assert TASK_QUEUE_BY_KIND["scan"] == QUEUE_MEDIUM
    assert TASK_QUEUE_BY_KIND["docs"] == QUEUE_LIGHT


def test_worker_queue_configuration_covers_mapped_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STUBGRAPH_ARQ_QUEUE", raising=False)
    monkeypatch.delenv("STUBGRAPH_ARQ_QUEUES", raising=False)
    import app.arq_worker as arq_worker

    reloaded = importlib.reload(arq_worker)
    mapped_queues = set(TASK_QUEUE_BY_KIND.values())
    covered = set(reloaded.WorkerSettings.queue_names)

    if reloaded.WorkerSettings.queue_name:
        covered.add(reloaded.WorkerSettings.queue_name)
    assert mapped_queues.issubset(covered)
