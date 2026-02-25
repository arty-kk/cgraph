from pathlib import Path


def test_async_submit_enqueue_run_path_has_no_sync_bridges() -> None:
    task_queue = Path("app/services/task_queue.py").read_text()
    celery_tasks = Path("app/celery_tasks.py").read_text()

    forbidden = ["run_coroutine_sync", "run_celery_producer_io_async", "dispatch_task"]
    for token in forbidden:
        assert token not in task_queue
        assert token not in celery_tasks


def test_removed_sync_bridge_modules_do_not_exist() -> None:
    assert not Path("app/infra/celery_producer_runtime.py").exists()
    assert not Path("app/celery_async_runner.py").exists()
