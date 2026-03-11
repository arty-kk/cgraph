import importlib
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))


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
    monkeypatch.setenv("STUBGRAPH_ARQ_QUEUE", "heavy")
    import app.arq_worker as arq_worker

    reloaded = importlib.reload(arq_worker)

    assert reloaded.WorkerSettings.queue_name == "heavy"


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
