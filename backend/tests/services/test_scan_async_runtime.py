import ast
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import scan


class _AsyncSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


class _NoopLock:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


@pytest.mark.anyio
async def test_collect_file_stats_async_keeps_input_order_across_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rel_paths = ["c.py", "a.py", "d.py", "b.py", "e.py"]
    for rel in rel_paths:
        (tmp_path / rel).write_text(rel, encoding="utf-8")

    seen_operations: list[str] = []

    async def _run_scan_fs_batch_out_of_order(sync_fn, batch, *, operation: str):
        seen_operations.append(operation)
        if batch and batch[0] == "d.py":
            await asyncio.sleep(0.03)
        return sync_fn(batch)

    monkeypatch.setattr(scan, "_run_scan_fs_batch", _run_scan_fs_batch_out_of_order)
    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 2)

    try:
        results = await scan._collect_file_stats_async(tmp_path, rel_paths, batch_size=2, max_parallel=2)
    except NameError as exc:
        pytest.fail(f"NameError must not be raised: {exc}")

    assert [item.rel for item in results] == rel_paths
    assert all(item.exists and item.is_file for item in results)
    assert seen_operations == ["scan.fs.collect_batch", "scan.fs.collect_batch", "scan.fs.collect_batch"]


@pytest.mark.anyio
async def test_read_file_batch_async_keeps_input_order_across_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rel_paths = ["3.py", "1.py", "4.py", "2.py", "5.py"]
    for rel in rel_paths:
        (tmp_path / rel).write_text(f"text:{rel}", encoding="utf-8")

    stats_map = {rel: (10 + idx, 20 + idx) for idx, rel in enumerate(rel_paths)}

    seen_operations: list[str] = []

    async def _run_scan_fs_batch_out_of_order(sync_fn, batch, *, operation: str):
        seen_operations.append(operation)
        if batch and batch[0] == "4.py":
            await asyncio.sleep(0.03)
        return sync_fn(batch)

    monkeypatch.setattr(scan, "_run_scan_fs_batch", _run_scan_fs_batch_out_of_order)
    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 2)

    try:
        results = await scan._read_file_batch_async(
            tmp_path,
            rel_paths,
            stats_map=stats_map,
            max_file_bytes=1024,
            max_parallel=2,
        )
    except NameError as exc:
        pytest.fail(f"NameError must not be raised: {exc}")

    assert [item.rel for item in results] == rel_paths
    assert [item.text for item in results] == [f"text:{rel}" for rel in rel_paths]
    assert seen_operations == ["scan.fs.read_batch", "scan.fs.read_batch", "scan.fs.read_batch"]


@pytest.mark.anyio
async def test_bounded_batch_helper_uses_max_parallel_as_queue_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    queue_sizes: list[int] = []
    original_queue = scan.asyncio.Queue

    class _QueueProbe(original_queue):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            queue_sizes.append(self.maxsize)

    async def _process(batch: list[int]) -> list[int]:
        await asyncio.sleep(0)
        return batch

    monkeypatch.setattr(scan.asyncio, "Queue", _QueueProbe)

    result = await scan._process_batches_bounded_async(
        [[1], [2], [3], [4]],
        max_parallel=3,
        process_batch=_process,
    )

    assert result == [[1], [2], [3], [4]]
    assert queue_sizes
    assert queue_sizes[0] == 3


@pytest.mark.anyio
async def test_bounded_batch_helper_cleans_up_on_outer_cancellation() -> None:
    blocker = asyncio.Event()

    async def _process(batch: list[str]) -> str:
        _ = batch
        await blocker.wait()
        return "ok"

    task = asyncio.create_task(
        scan._process_batches_bounded_async(
            [["a"], ["b"], ["c"]],
            max_parallel=2,
            process_batch=_process,
        )
    )

    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    other_tasks = [
        t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
    ]
    assert all(getattr(t.get_coro(), "__name__", "") != "_worker" for t in other_tasks)


@pytest.mark.anyio
async def test_bounded_batch_helper_cancels_workers_on_first_exception() -> None:
    started: list[str] = []
    cancelled: list[str] = []
    blocker = asyncio.Event()

    async def _process(batch: list[str]) -> str:
        name = batch[0]
        started.append(name)
        if name == "fail":
            raise RuntimeError("boom")
        try:
            await blocker.wait()
        except asyncio.CancelledError:
            cancelled.append(name)
            raise
        return name

    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.wait_for(
            scan._process_batches_bounded_async(
                [["fail"], ["slow-1"], ["slow-2"]],
                max_parallel=3,
                process_batch=_process,
            ),
            timeout=1,
        )

    assert "fail" in started
    assert cancelled



@pytest.mark.anyio
async def test_scan_files_async_runtime_does_not_use_sync_get_session(monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = scan.PreparedScanData(
        present=["a.py"],
        removed=[],
        node_rows=[{"path": "a.py"}],
        edge_map={},
        search_rows=[],
        route_rows=[],
        call_rows=[],
        include_rows=[],
        route_contract_rows=[],
        call_meta_rows=[],
        ts_type_rows=[],
        embedding_rows=[],
        embedding_paths_to_delete=[],
        removed_edge_neighbors=set(),
        snapshot={},
    )

    class _Session:
        pass

    async def _fake_prepare(*_args, **_kwargs):
        return prepared

    async def _fake_write(*_args, **_kwargs):
        return None

    def _fail_get_session(*_args, **_kwargs):
        raise AssertionError("sync get_session must not be called in async runtime scan path")

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "project_lock_async", lambda *_args, **_kwargs: _NoopLock())
    monkeypatch.setattr(scan, "_prepare_scan_files_async", _fake_prepare)
    monkeypatch.setattr(scan, "_write_scan_files_async", _fake_write)
    monkeypatch.setattr(scan, "get_session", _fail_get_session, raising=False)

    result = await scan.scan_files_async(1, 2, Path("/repo"), ["a.py"])

    assert result["updated_nodes"] == 1


@pytest.mark.anyio
async def test_scan_files_async_returns_aborted_on_snapshot_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = scan.PreparedScanData(
        present=["a.py"],
        removed=[],
        node_rows=[{"path": "a.py"}],
        edge_map={},
        search_rows=[],
        route_rows=[],
        call_rows=[],
        include_rows=[],
        route_contract_rows=[],
        call_meta_rows=[],
        ts_type_rows=[],
        embedding_rows=[],
        embedding_paths_to_delete=[],
        removed_edge_neighbors=set(),
        snapshot={"a.py": scan.FileSnapshot(0, 0, "", "stat_only")},
    )

    class _Session:
        pass

    calls = {"prepare": 0, "write": 0}

    async def _fake_prepare(*_args, **_kwargs):
        calls["prepare"] += 1
        return prepared

    async def _fake_write(*_args, **_kwargs):
        calls["write"] += 1

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "project_lock_async", lambda *_args, **_kwargs: _NoopLock())
    monkeypatch.setattr(scan, "_prepare_scan_files_async", _fake_prepare)
    monkeypatch.setattr(scan, "_write_scan_files_async", _fake_write)

    async def _fake_verify(*_args, **_kwargs):
        return (False, "changed")

    monkeypatch.setattr(scan, "_verify_scan_snapshot_async", _fake_verify)

    result = await scan.scan_files_async(1, 2, Path("/repo"), ["a.py"])

    assert result["aborted"] is True
    assert result["reason"] == "snapshot_mismatch"
    assert calls["prepare"] == 2
    assert calls["write"] == 0


@pytest.mark.anyio
async def test_scan_files_async_uses_async_snapshot_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = scan.PreparedScanData(
        present=["a.py"],
        removed=[],
        node_rows=[{"path": "a.py"}],
        edge_map={},
        search_rows=[],
        route_rows=[],
        call_rows=[],
        include_rows=[],
        route_contract_rows=[],
        call_meta_rows=[],
        ts_type_rows=[],
        embedding_rows=[],
        embedding_paths_to_delete=[],
        removed_edge_neighbors=set(),
        snapshot={},
    )

    class _Session:
        pass

    called = {"verify": 0}

    async def _fake_prepare(*_args, **_kwargs):
        return prepared

    async def _fake_write(*_args, **_kwargs):
        return None

    async def _fake_verify(*_args, **_kwargs):
        called["verify"] += 1
        return (True, "")

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "project_lock_async", lambda *_args, **_kwargs: _NoopLock())
    monkeypatch.setattr(scan, "_prepare_scan_files_async", _fake_prepare)
    monkeypatch.setattr(scan, "_write_scan_files_async", _fake_write)
    monkeypatch.setattr(scan, "_verify_scan_snapshot_async", _fake_verify)

    result = await scan.scan_files_async(1, 2, Path("/repo"), ["a.py"])

    assert result["updated_nodes"] == 1
    assert called["verify"] == 1


@pytest.mark.anyio
async def test_scan_project_async_uses_async_snapshot_verify_for_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        async def execute(self, *_args, **_kwargs):
            return _Result([("gone.py", 0.0, 0, 0, "")])

        async def commit(self):
            return None

    called = {"verify": 0}

    async def _fake_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = rel_paths, precomputed_stats, batch_size, max_parallel
        return []

    async def _fake_scan_files(*_args, **_kwargs):
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    async def _fake_verify(_project_root, _snapshot, removed, **_kwargs):
        called["verify"] += 1
        if removed:
            return (False, f"removed_path_exists:{removed[0]}")
        return (True, "")

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "iter_code_files", lambda _root: [])
    monkeypatch.setattr(scan, "_collect_file_stats_async", _fake_collect)
    monkeypatch.setattr(scan, "scan_files_async", _fake_scan_files)
    monkeypatch.setattr(scan, "project_lock_async", lambda *_args, **_kwargs: _NoopLock())
    monkeypatch.setattr(scan, "_verify_scan_snapshot_async", _fake_verify)

    result = await scan.scan_project_async(1, 2, Path("/repo"))

    assert called["verify"] == 1
    assert result["removed_aborted"] is True
    assert result["reason"] == "snapshot_mismatch"


@pytest.mark.anyio
async def test_scan_project_async_large_streamed_paths_keeps_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    all_paths = [f"src/file_{i:04d}.py" for i in range(600)]
    changed_by_stat = {all_paths[i] for i in range(0, 120, 3)}
    changed_by_hash = {all_paths[i] for i in range(300, 360, 2)}
    unchanged = set(all_paths) - changed_by_stat - changed_by_hash

    existing_rows = []
    for rel in sorted(unchanged | changed_by_stat | changed_by_hash):
        if rel in changed_by_stat:
            existing_rows.append((rel, 0.0, 10, 10, f"hash:{rel}"))
        else:
            existing_rows.append((rel, 0.0, 20, 20, f"hash:{rel}"))
    existing_rows.append(("gone.py", 0.0, 10, 10, "hash:gone.py"))

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        def __init__(self):
            self._calls = 0

        async def execute(self, statement, *_args, **_kwargs):
            _ = statement
            self._calls += 1
            if self._calls == 1:
                return _Result(existing_rows)
            return _Result([])

        async def commit(self):
            return None

    captured: dict[str, object] = {}
    collect_batch_sizes: list[int] = []
    queue_sizes: list[int] = []
    created_consumer_names: list[str] = []

    async def _fake_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        collect_batch_sizes.append(len(rel_paths))
        results = []
        for rel in rel_paths:
            if rel in changed_by_stat:
                results.append(scan.FileStatResult(rel, True, True, True, 21, 21))
            else:
                results.append(scan.FileStatResult(rel, True, True, True, 20, 20))
        return results

    async def _fake_read(_root, batch_paths, stats_map, _max_file_bytes, max_parallel=8):
        _ = max_parallel, stats_map
        out = []
        for rel in batch_paths:
            text = f"new:{rel}" if rel in changed_by_hash else rel
            out.append(scan.FileReadResult(rel=rel, text=text, mtime_ns=20, size=20, oversized=False))
        return out

    async def _fake_scan_files(_project_id, _org_id, _project_root, rel_paths, precomputed_stats=None, scan_metrics=None):
        captured["rel_paths"] = list(rel_paths)
        captured["precomputed_stats"] = dict(precomputed_stats or {})
        captured["queue_sizes"] = list(queue_sizes)
        _ = scan_metrics
        return {"updated_nodes": len(captured["rel_paths"]), "updated_edges": 0, "removed": 0}

    verify_calls = {"removed": []}

    async def _fake_verify(_project_root, _snapshot, removed, **_kwargs):
        verify_calls["removed"].append(list(removed))
        return (True, "")

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(
        scan,
        "iter_code_files",
        lambda _root: (Path("/repo") / rel for rel in all_paths),
    )
    monkeypatch.setattr(scan, "_collect_file_stats_async", _fake_collect)
    monkeypatch.setattr(scan, "_read_file_batch_async", _fake_read)
    monkeypatch.setattr(scan, "scan_files_async", _fake_scan_files)
    monkeypatch.setattr(scan, "project_lock_async", lambda *_args, **_kwargs: _NoopLock())
    monkeypatch.setattr(scan, "_verify_scan_snapshot_async", _fake_verify)
    monkeypatch.setattr(scan, "sha256_text", lambda text: f"hash:{text}")
    monkeypatch.setattr(scan.settings, "scan_hash_verify_max_file_bytes", 1024)
    monkeypatch.setattr(scan.settings, "snapshot_max_file_bytes", 1024)
    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 64)
    monkeypatch.setattr(scan.settings, "scan_stage_max_parallel", 4)

    orig_queue = scan.asyncio.Queue

    class _QueueProbe(orig_queue):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            queue_sizes.append(self.maxsize)

    original_create_task = scan.asyncio.create_task

    def _create_task_probe(coro, *, name=None, context=None):
        if isinstance(name, str) and name.startswith("scan-consumer-"):
            created_consumer_names.append(name)
        if context is None:
            return original_create_task(coro, name=name)
        return original_create_task(coro, name=name, context=context)

    monkeypatch.setattr(scan.asyncio, "Queue", _QueueProbe)
    monkeypatch.setattr(scan.asyncio, "create_task", _create_task_probe)

    result = await scan.scan_project_async(1, 2, Path("/repo"))

    expected_changed = sorted(changed_by_stat | changed_by_hash)
    assert result["nodes"] == len(all_paths)
    assert result["changed"] == len(expected_changed)
    assert result["removed"] == 0
    assert "scan_metrics" in result
    assert result["scan_metrics"]["producer"]["batches"] == 10
    assert result["scan_metrics"]["producer"]["paths"] == len(all_paths)
    assert verify_calls["removed"] == [["gone.py"]]
    assert captured["rel_paths"] == expected_changed
    assert set(captured["precomputed_stats"].keys()) == set(expected_changed)
    assert all(captured["precomputed_stats"][rel] == (21, 21) for rel in changed_by_stat)
    assert all(captured["precomputed_stats"][rel] == (20, 20) for rel in changed_by_hash)
    assert collect_batch_sizes[:10] == [64, 64, 64, 64, 64, 64, 64, 64, 64, 24]
    assert captured["queue_sizes"] == [4]
    assert created_consumer_names == [
        "scan-consumer-1-0",
        "scan-consumer-1-1",
        "scan-consumer-1-2",
        "scan-consumer-1-3",
    ]




@pytest.mark.anyio
async def test_scan_project_async_starts_multiple_consumers_when_parallelism_is_high(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        async def execute(self, *_args, **_kwargs):
            return _Result([])

        async def commit(self):
            return None

    created_consumer_names: list[str] = []
    original_create_task = scan.asyncio.create_task

    def _create_task_probe(coro, *, name=None, context=None):
        if isinstance(name, str) and name.startswith("scan-consumer-"):
            created_consumer_names.append(name)
        if context is None:
            return original_create_task(coro, name=name)
        return original_create_task(coro, name=name, context=context)

    async def _fake_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        await asyncio.sleep(0)
        return [scan.FileStatResult(rel, True, True, True, 1, 1) for rel in rel_paths]

    async def _fake_scan_files(_project_id, _org_id, _project_root, rel_paths, precomputed_stats=None, scan_metrics=None):
        _ = rel_paths, precomputed_stats, scan_metrics
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "iter_code_files", lambda root: (root / f"f{i}.py" for i in range(12)))
    monkeypatch.setattr(scan, "_collect_file_stats_async", _fake_collect)
    monkeypatch.setattr(scan, "scan_files_async", _fake_scan_files)
    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 2)
    monkeypatch.setattr(scan.settings, "scan_stage_max_parallel", 3)
    monkeypatch.setattr(scan.asyncio, "create_task", _create_task_probe)

    await scan.scan_project_async(7, 8, Path("/repo"))

    assert len(created_consumer_names) == 3
    assert created_consumer_names == [
        "scan-consumer-7-0",
        "scan-consumer-7-1",
        "scan-consumer-7-2",
    ]

@pytest.mark.anyio
async def test_scan_project_async_streams_batches_before_full_fs_walk_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        async def execute(self, *_args, **_kwargs):
            return _Result([])

        async def commit(self):
            return None

    walk_can_finish = asyncio.Event()
    first_batch_started = asyncio.Event()

    def _iter_stream(root: Path):
        yield root / "f0.py"
        yield root / "f1.py"
        while not first_batch_started.is_set():
            time.sleep(0.001)
        for i in range(2, 6):
            yield root / f"f{i}.py"
        while not walk_can_finish.is_set():
            time.sleep(0.001)

    async def _collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        first_batch_started.set()
        walk_can_finish.set()
        return [scan.FileStatResult(rel, True, True, True, 1, 1) for rel in rel_paths]

    async def _fake_scan_files(_project_id, _org_id, _project_root, rel_paths, precomputed_stats=None, scan_metrics=None):
        _ = rel_paths, precomputed_stats, scan_metrics
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "iter_code_files", _iter_stream)
    monkeypatch.setattr(scan, "_collect_file_stats_async", _collect)
    monkeypatch.setattr(scan, "scan_files_async", _fake_scan_files)
    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 2)
    monkeypatch.setattr(scan.settings, "scan_stage_max_parallel", 2)

    result = await asyncio.wait_for(scan.scan_project_async(1, 2, Path("/repo")), timeout=1.0)

    assert first_batch_started.is_set()
    assert result["nodes"] == 6



@pytest.mark.anyio
async def test_scan_project_async_producer_does_not_use_run_coroutine_threadsafe(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        async def execute(self, *_args, **_kwargs):
            return _Result([])

        async def commit(self):
            return None

    async def _fake_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        return [scan.FileStatResult(rel, True, True, True, 1, 1) for rel in rel_paths]

    async def _fake_scan_files(_project_id, _org_id, _project_root, rel_paths, precomputed_stats=None, scan_metrics=None):
        _ = rel_paths, precomputed_stats, scan_metrics
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    def _fail_threadsafe(*_args, **_kwargs):
        raise AssertionError("run_coroutine_threadsafe must not be used by async producer")

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "iter_code_files", lambda root: (root / f"f{i}.py" for i in range(8)))
    monkeypatch.setattr(scan, "_collect_file_stats_async", _fake_collect)
    monkeypatch.setattr(scan, "scan_files_async", _fake_scan_files)
    monkeypatch.setattr(scan.asyncio, "run_coroutine_threadsafe", _fail_threadsafe)

    result = await scan.scan_project_async(1, 2, Path("/repo"))

    assert result["nodes"] == 8


@pytest.mark.anyio
async def test_scan_project_async_applies_backpressure_with_bounded_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        
    class _Session:
        async def execute(self, *_args, **_kwargs):
            return _Result([])

        async def commit(self):
            return None

    pressure = {"queue_maxsize": None, "max_qsize": 0}

    orig_queue = scan.asyncio.Queue

    class _QueueProbe(orig_queue):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            pressure["queue_maxsize"] = self.maxsize

        async def put(self, item):
            await super().put(item)
            pressure["max_qsize"] = max(pressure["max_qsize"], self.qsize())

    async def _slow_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        await asyncio.sleep(0.02)
        return [scan.FileStatResult(rel, True, True, True, 1, 1) for rel in rel_paths]

    async def _fake_scan_files(_project_id, _org_id, _project_root, rel_paths, precomputed_stats=None, scan_metrics=None):
        _ = rel_paths, precomputed_stats, scan_metrics
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "iter_code_files", lambda root: (root / f"f{i}.py" for i in range(40)))
    monkeypatch.setattr(scan, "_collect_file_stats_async", _slow_collect)
    monkeypatch.setattr(scan, "scan_files_async", _fake_scan_files)
    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 2)
    monkeypatch.setattr(scan.settings, "scan_stage_max_parallel", 2)
    monkeypatch.setattr(scan.asyncio, "Queue", _QueueProbe)

    result = await scan.scan_project_async(1, 2, Path("/repo"))

    assert pressure["queue_maxsize"] == 2
    assert pressure["max_qsize"] <= 2
    assert result["scan_metrics"]["producer"]["duration_s"] >= 0.15


@pytest.mark.anyio
async def test_scan_project_async_high_concurrency_keeps_event_loop_responsive(monkeypatch: pytest.MonkeyPatch) -> None:
    roots = {
        Path("/repo-a").resolve(): [f"src/a_{i}.py" for i in range(24)],
        Path("/repo-b").resolve(): [f"src/b_{i}.py" for i in range(24)],
    }

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        async def execute(self, *_args, **_kwargs):
            return _Result([])

        async def commit(self):
            return None

    async def _slow_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        await asyncio.sleep(0.01)
        return [scan.FileStatResult(rel, True, True, True, 1, 1) for rel in rel_paths]

    async def _fake_scan_files(_project_id, _org_id, _project_root, rel_paths, precomputed_stats=None, scan_metrics=None):
        _ = rel_paths, precomputed_stats, scan_metrics
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    ticks = {"count": 0}

    async def _heartbeat():
        deadline = time.monotonic() + 0.35
        while time.monotonic() < deadline:
            ticks["count"] += 1
            await asyncio.sleep(0.005)

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "iter_code_files", lambda root: (root / rel for rel in roots[root.resolve()]))
    monkeypatch.setattr(scan, "_collect_file_stats_async", _slow_collect)
    monkeypatch.setattr(scan, "scan_files_async", _fake_scan_files)
    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 2)
    monkeypatch.setattr(scan.settings, "scan_stage_max_parallel", 2)

    await asyncio.gather(
        scan.scan_project_async(101, 201, Path("/repo-a")),
        scan.scan_project_async(102, 202, Path("/repo-b")),
        _heartbeat(),
    )

    assert ticks["count"] >= 20


@pytest.mark.anyio
async def test_scan_project_async_cancelled_scan_does_not_leave_pipeline_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        async def execute(self, *_args, **_kwargs):
            return _Result([])

        async def commit(self):
            return None

    async def _slow_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        await asyncio.sleep(0.05)
        return [scan.FileStatResult(rel, True, True, True, 1, 1) for rel in rel_paths]

    async def _fake_scan_files(*_args, **_kwargs):
        return {"updated_nodes": 0, "updated_edges": 0, "removed": 0}

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "iter_code_files", lambda root: (root / f"f{i}.py" for i in range(500)))
    monkeypatch.setattr(scan, "_collect_file_stats_async", _slow_collect)
    monkeypatch.setattr(scan, "scan_files_async", _fake_scan_files)
    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 2)
    monkeypatch.setattr(scan.settings, "scan_stage_max_parallel", 3)

    task = asyncio.create_task(scan.scan_project_async(999, 1, Path("/repo")))
    await asyncio.sleep(0.08)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)

    await asyncio.sleep(0)
    dangling = [
        t for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and t.get_name().startswith(("scan-producer-", "scan-consumer-"))
    ]
    assert not dangling


@pytest.mark.anyio
async def test_verify_scan_snapshot_async_keeps_read_failed_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "a.py"
    file_path.write_text("print('ok')", encoding="utf-8")
    st = file_path.stat()
    snapshot = {
        "a.py": scan.FileSnapshot(
            mtime_ns=int(st.st_mtime_ns),
            size=int(st.st_size),
            file_hash="irrelevant",
            hash_kind="content",
        )
    }

    def _boom(*_args, **_kwargs):
        raise RuntimeError("cannot read")

    monkeypatch.setattr(Path, "read_text", _boom)
    ok, reason = await scan._verify_scan_snapshot_async(tmp_path, snapshot, [])

    assert ok is False
    assert reason == "read_failed:a.py"


@pytest.mark.anyio
async def test_verify_scan_snapshot_async_keeps_hash_changed_reason(tmp_path: Path) -> None:
    file_path = tmp_path / "a.py"
    file_path.write_text("print('ok')", encoding="utf-8")
    st = file_path.stat()
    snapshot = {
        "a.py": scan.FileSnapshot(
            mtime_ns=int(st.st_mtime_ns),
            size=int(st.st_size),
            file_hash="bad-hash",
            hash_kind="content",
        )
    }

    ok, reason = await scan._verify_scan_snapshot_async(tmp_path, snapshot, [])

    assert ok is False
    assert reason == "hash_changed:a.py"


@pytest.mark.anyio
async def test_verify_scan_snapshot_async_keeps_unknown_hash_kind_reason(tmp_path: Path) -> None:
    file_path = tmp_path / "a.py"
    file_path.write_text("print('ok')", encoding="utf-8")
    st = file_path.stat()
    snapshot = {
        "a.py": scan.FileSnapshot(
            mtime_ns=int(st.st_mtime_ns),
            size=int(st.st_size),
            file_hash="",
            hash_kind="weird",
        )
    }

    ok, reason = await scan._verify_scan_snapshot_async(tmp_path, snapshot, [])

    assert ok is False
    assert reason == "unknown_hash_kind:a.py"


@pytest.mark.anyio
async def test_verify_scan_snapshot_async_uses_bounded_parallel_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {}
    for i in range(12):
        rel = f"f{i}.py"
        p = tmp_path / rel
        p.write_text(f"x={i}\n", encoding="utf-8")
        st = p.stat()
        text = p.read_text(encoding="utf-8", errors="replace")
        snapshot[rel] = scan.FileSnapshot(
            mtime_ns=int(st.st_mtime_ns),
            size=int(st.st_size),
            file_hash=scan.sha256_text(text),
            hash_kind="content",
        )

    active = {"value": 0, "peak": 0}

    async def _fake_run(sync_fn, *args, operation: str):
        if operation == "scan.fs.verify_snapshot_fs_batch":
            active["value"] += 1
            active["peak"] = max(active["peak"], active["value"])
            await asyncio.sleep(0.02)
            try:
                return sync_fn(*args)
            finally:
                active["value"] -= 1
        return sync_fn(*args)

    monkeypatch.setattr(scan, "_run_scan_fs_batch", _fake_run)

    ok, reason = await scan._verify_scan_snapshot_async(
        tmp_path,
        snapshot,
        [],
        batch_size=1,
        max_parallel=3,
    )

    assert ok is True
    assert reason == ""
    assert active["peak"] <= 3
    assert active["peak"] > 1


@pytest.mark.anyio
async def test_verify_scan_snapshot_async_stops_early_on_first_failed_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {}
    for i in range(6):
        rel = f"f{i}.py"
        p = tmp_path / rel
        p.write_text("x=1\n", encoding="utf-8")
        st = p.stat()
        snapshot[rel] = scan.FileSnapshot(
            mtime_ns=int(st.st_mtime_ns),
            size=int(st.st_size),
            file_hash="bad-hash",
            hash_kind="content",
        )

    call_counter = {"cpu": 0}

    async def _fake_cpu(sync_fn, *args, operation: str):
        call_counter["cpu"] += 1
        await asyncio.sleep(0.05)
        return sync_fn(*args)

    monkeypatch.setattr(scan, "_run_scan_cpu_batch", _fake_cpu)

    ok, reason = await scan._verify_scan_snapshot_async(
        tmp_path,
        snapshot,
        [],
        batch_size=1,
        max_parallel=3,
    )

    assert ok is False
    assert reason.startswith("hash_changed:")
    assert call_counter["cpu"] < len(snapshot)




@pytest.mark.anyio
async def test_prepare_scan_files_async_uses_chunked_async_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Session:
        async def execute(self, _stmt, _params=None):
            class _Rows:
                def all(self):
                    return []

            return _Rows()

    norm_paths = [f"f{i}.py" for i in range(6)]
    stage_calls = {"collect": 0, "read": 0, "parse": 0}

    async def _fake_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        stage_calls["collect"] += 1
        return [
            scan.FileStatResult(
                rel=rel,
                exists=True,
                is_file=True,
                is_supported=True,
                mtime_ns=1,
                size=10,
            )
            for rel in rel_paths
        ]

    async def _fake_read(_root, batch_paths, stats_map, max_file_bytes, max_parallel=8):
        _ = stats_map, max_file_bytes, max_parallel
        stage_calls["read"] += 1
        return [
            scan.FileReadResult(rel=rel, text="print('ok')", mtime_ns=1, size=10, oversized=False)
            for rel in batch_paths
        ]

    async def _fake_parse(project_id, _project_root, file_batch):
        stage_calls["parse"] += 1
        rows = []
        for item in file_batch:
            rows.append(
                {
                    "rel": item.rel,
                    "stat_mtime": 0.0,
                    "stat_mtime_ns": item.mtime_ns,
                    "stat_size": item.size,
                    "file_hash": "h",
                    "snapshot_kind": "content",
                    "node_row": {
                        "project_id": project_id,
                        "path": item.rel,
                        "language": "py",
                        "loc": 1,
                        "complexity": 1,
                        "file_hash": "h",
                        "file_mtime": 0.0,
                        "file_mtime_ns": item.mtime_ns,
                        "file_size": item.size,
                    },
                    "search_row": {"project_id": project_id, "path": item.rel, "content": item.text or ""},
                    "cached_imports": [],
                    "route_rows": [],
                    "call_rows": [],
                    "include_rows": [],
                    "route_contract_rows": [],
                    "call_meta_rows": [],
                    "ts_type_rows": [],
                    "text": item.text,
                }
            )
        return rows

    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 2)
    monkeypatch.setattr(scan, "_collect_file_stats_async", _fake_collect)
    monkeypatch.setattr(scan, "_read_file_batch_async", _fake_read)
    monkeypatch.setattr(scan, "_parse_index_batch_async", _fake_parse)
    async def _fake_entitlement(*_args, **_kwargs):
        return False

    monkeypatch.setattr(scan, "get_entitlement_bool_async", _fake_entitlement)

    prepared = await scan._prepare_scan_files_async(
        _Session(),
        1,
        1,
        Path("/repo"),
        norm_paths,
        precomputed_stats={rel: (1, 10) for rel in norm_paths},
    )

    assert len(prepared.node_rows) == len(norm_paths)
    assert stage_calls["collect"] == 1
    assert stage_calls["read"] == 3
    assert stage_calls["parse"] == 3


@pytest.mark.anyio
async def test_prepare_scan_files_async_embeddings_dispatcher_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Session:
        async def execute(self, _stmt, _params=None):
            class _Rows:
                def all(self):
                    return []

            return _Rows()

    class _EmbeddingItem:
        def __init__(self, embedding):
            self.embedding = embedding

    class _EmbeddingsResponse:
        def __init__(self):
            self.data = [_EmbeddingItem([0.1, 0.2])]

    current_concurrency = 0
    max_concurrency = 0

    class _Embeddings:
        async def create(self, **_kwargs):
            nonlocal current_concurrency, max_concurrency
            current_concurrency += 1
            max_concurrency = max(max_concurrency, current_concurrency)
            await asyncio.sleep(0.05)
            current_concurrency -= 1
            return _EmbeddingsResponse()

    class _Client:
        def __init__(self):
            self.embeddings = _Embeddings()

    norm_paths = [f"f{i}.py" for i in range(3)]

    async def _fake_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        return [
            scan.FileStatResult(
                rel=rel,
                exists=True,
                is_file=True,
                is_supported=True,
                mtime_ns=1,
                size=10,
            )
            for rel in rel_paths
        ]

    async def _fake_read(_root, batch_paths, stats_map, max_file_bytes, max_parallel=8):
        _ = stats_map, max_file_bytes, max_parallel
        return [
            scan.FileReadResult(rel=rel, text="print('ok')", mtime_ns=1, size=10, oversized=False)
            for rel in batch_paths
        ]

    async def _fake_parse(project_id, _project_root, file_batch):
        rows = []
        for item in file_batch:
            rows.append(
                {
                    "rel": item.rel,
                    "stat_mtime": 0.0,
                    "stat_mtime_ns": item.mtime_ns,
                    "stat_size": item.size,
                    "file_hash": f"h-{item.rel}",
                    "snapshot_kind": "content",
                    "node_row": {
                        "project_id": project_id,
                        "path": item.rel,
                        "language": "py",
                        "loc": 1,
                        "complexity": 1,
                        "file_hash": f"h-{item.rel}",
                        "file_mtime": 0.0,
                        "file_mtime_ns": item.mtime_ns,
                        "file_size": item.size,
                    },
                    "search_row": {"project_id": project_id, "path": item.rel, "content": item.text or ""},
                    "cached_imports": [],
                    "route_rows": [],
                    "call_rows": [],
                    "include_rows": [],
                    "route_contract_rows": [],
                    "call_meta_rows": [],
                    "ts_type_rows": [],
                    "text": item.text,
                }
            )
        return rows

    async def _fake_entitlement(*_args, **_kwargs):
        return True

    async def _fake_entitlement_int(*_args, **_kwargs):
        return 100

    async def _fake_check_increment(*_args, **_kwargs):
        return None

    async def _fake_openai_io(fn, kind="short"):
        assert kind == "long"
        return await fn()

    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 3)
    monkeypatch.setattr(scan.settings, "scan_embeddings_max_parallel", 2)
    monkeypatch.setattr(scan, "_collect_file_stats_async", _fake_collect)
    monkeypatch.setattr(scan, "_read_file_batch_async", _fake_read)
    monkeypatch.setattr(scan, "_parse_index_batch_async", _fake_parse)
    monkeypatch.setattr(scan, "_symbol_chunks", lambda _text, _symbols: [{"symbol_name": "s"}])
    monkeypatch.setattr(scan, "get_entitlement_bool_async", _fake_entitlement)
    monkeypatch.setattr(scan, "get_entitlement_int_async", _fake_entitlement_int)
    monkeypatch.setattr(scan, "check_and_increment_async", _fake_check_increment)
    monkeypatch.setattr(scan, "run_openai_io_async", _fake_openai_io)
    monkeypatch.setattr(scan, "get_async_openai_client", lambda: _Client())
    monkeypatch.setattr(scan.settings, "embeddings_enabled", True)
    monkeypatch.setattr(scan.settings, "openai_api_key", "test")

    prepared = await scan._prepare_scan_files_async(
        _Session(),
        1,
        1,
        Path("/repo"),
        norm_paths,
        precomputed_stats={rel: (1, 10) for rel in norm_paths},
    )

    assert len(prepared.embedding_rows) == len(norm_paths)
    assert max_concurrency == 2


@pytest.mark.anyio
async def test_write_scan_files_async_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def execute(self, _stmt, _params=None):
            return None

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    session = _Session()
    prepared = scan.PreparedScanData(
        present=[],
        removed=[],
        node_rows=[],
        edge_map={},
        search_rows=[],
        route_rows=[],
        call_rows=[],
        include_rows=[],
        route_contract_rows=[],
        call_meta_rows=[],
        ts_type_rows=[],
        embedding_rows=[],
        embedding_paths_to_delete=[],
        removed_edge_neighbors=set(),
        snapshot={},
    )

    await scan._write_scan_files_async(session, 1, prepared)

    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.anyio
async def test_write_scan_files_async_rolls_back_on_execute_error() -> None:
    class _Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def execute(self, _stmt, _params=None):
            raise RuntimeError("boom")

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    session = _Session()
    prepared = scan.PreparedScanData(
        present=[],
        removed=[],
        node_rows=[],
        edge_map={},
        search_rows=[{"project_id": 1, "path": "a.py", "content": "x"}],
        route_rows=[],
        call_rows=[],
        include_rows=[],
        route_contract_rows=[],
        call_meta_rows=[],
        ts_type_rows=[],
        embedding_rows=[],
        embedding_paths_to_delete=[],
        removed_edge_neighbors=set(),
        snapshot={},
    )

    with pytest.raises(RuntimeError, match="scan_files: DB write failed"):
        await scan._write_scan_files_async(session, 1, prepared)

    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.anyio
async def test_collect_file_stats_async_uses_bounded_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = []
    for i in range(24):
        rel = f"f{i}.py"
        (tmp_path / rel).write_text("print('ok')", encoding="utf-8")
        paths.append(rel)

    active = {"value": 0, "peak": 0}

    async def _fake_run(sync_fn, *args, operation: str):
        _ = operation
        active["value"] += 1
        active["peak"] = max(active["peak"], active["value"])
        await asyncio.sleep(0.01)
        try:
            return sync_fn(*args)
        finally:
            active["value"] -= 1

    monkeypatch.setattr(scan, "_run_scan_fs_batch", _fake_run)

    result = await scan._collect_file_stats_async(
        tmp_path,
        paths,
        batch_size=2,
        max_parallel=3,
    )

    assert len(result) == len(paths)
    assert [item.rel for item in result] == paths
    assert active["peak"] <= 3


@pytest.mark.anyio
async def test_read_file_batch_async_uses_bounded_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = []
    stats: dict[str, tuple[int, int]] = {}
    for i in range(20):
        rel = f"r{i}.py"
        content = f"x={i}"
        pth = tmp_path / rel
        pth.write_text(content, encoding="utf-8")
        st = pth.stat()
        stats[rel] = (int(st.st_mtime_ns), int(st.st_size))
        paths.append(rel)

    active = {"value": 0, "peak": 0}

    async def _fake_run(sync_fn, *args, operation: str):
        _ = operation
        active["value"] += 1
        active["peak"] = max(active["peak"], active["value"])
        await asyncio.sleep(0.01)
        try:
            return sync_fn(*args)
        finally:
            active["value"] -= 1

    monkeypatch.setattr(scan, "_run_scan_fs_batch", _fake_run)

    result = await scan._read_file_batch_async(
        tmp_path,
        paths,
        stats,
        max_file_bytes=1024,
        max_parallel=4,
    )

    assert [item.rel for item in result] == paths
    assert active["peak"] <= 4


def test_scan_module_does_not_use_asyncio_to_thread_in_scan_paths() -> None:
    scan_path = Path(__file__).resolve().parents[2] / "app" / "scan.py"
    tree = ast.parse(scan_path.read_text(encoding="utf-8"), filename=str(scan_path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "asyncio"
                and node.func.attr == "to_thread"
            ):
                offenders.append(f"{scan_path}:{node.lineno}")
    assert not offenders, "scan module must not use asyncio.to_thread in async scan paths"

def test_prepare_scan_files_async_does_not_call_cached_import_aggregator_directly() -> None:
    scan_path = Path(__file__).resolve().parents[2] / "app" / "scan.py"
    tree = ast.parse(scan_path.read_text(encoding="utf-8"), filename=str(scan_path))

    prepare_node = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_prepare_scan_files_async":
            prepare_node = node
            break

    assert prepare_node is not None, "_prepare_scan_files_async must exist"

    direct_calls: list[int] = []
    cpu_wrapped_calls: list[int] = []

    for node in ast.walk(prepare_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "_aggregate_cached_import_edges_sync":
            direct_calls.append(node.lineno)
        if isinstance(node.func, ast.Name) and node.func.id == "_run_scan_cpu_batch" and node.args:
            fn_arg = node.args[0]
            if isinstance(fn_arg, ast.Name) and fn_arg.id == "_aggregate_cached_import_edges_sync":
                for kw in node.keywords:
                    if kw.arg == "operation" and isinstance(kw.value, ast.Constant) and kw.value.value == "scan.cpu.cached_import_edges":
                        cpu_wrapped_calls.append(node.lineno)

    assert not direct_calls, "_prepare_scan_files_async must not call _aggregate_cached_import_edges_sync directly"
    assert cpu_wrapped_calls, "_prepare_scan_files_async must route cached import edge aggregation via CPU runtime"



@pytest.mark.anyio
async def test_scan_runtime_routes_fs_and_cpu_operations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_fs(sync_fn, *args, operation=None, **kwargs):
        _ = kwargs
        calls.append(("fs", str(operation)))
        return sync_fn(*args)

    async def _fake_cpu(sync_fn, *args, operation=None, **kwargs):
        _ = kwargs
        calls.append(("cpu", str(operation)))
        return sync_fn(*args)

    monkeypatch.setattr(scan, "run_fs_io_async", _fake_fs)
    monkeypatch.setattr(scan, "run_cpu_io_async", _fake_cpu)

    file_path = tmp_path / "a.py"
    file_path.write_text("x = 1\n", encoding="utf-8")
    stat = file_path.stat()

    await scan._collect_file_stats_async(tmp_path, ["a.py"])
    await scan._read_file_batch_async(tmp_path, ["a.py"], {"a.py": (int(stat.st_mtime_ns), int(stat.st_size))}, 1024)
    await scan._parse_index_batch_async(
        1,
        tmp_path,
        [scan.FileReadResult(rel="a.py", text="x=1", mtime_ns=int(stat.st_mtime_ns), size=int(stat.st_size), oversized=False)],
    )
    await scan._verify_scan_snapshot_async(
        tmp_path,
        {
            "a.py": scan.FileSnapshot(
                mtime_ns=int(stat.st_mtime_ns),
                size=int(stat.st_size),
                file_hash=scan.sha256_text("x = 1\n"),
                hash_kind="content",
            )
        },
        ["missing.py"],
    )

    assert ("fs", "scan.fs.collect_batch") in calls
    assert ("fs", "scan.fs.read_batch") in calls
    assert ("fs", "scan.fs.verify_removed_batch") in calls
    assert ("fs", "scan.fs.verify_snapshot_fs_batch") in calls
    assert ("cpu", "scan.cpu.parse_batch") in calls
    assert ("cpu", "scan.cpu.verify_snapshot_hash_batch") in calls


@pytest.mark.anyio
async def test_scan_cpu_heavy_batch_does_not_block_fs_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    events: dict[str, float] = {}

    async def _fake_fs(sync_fn, *args, operation=None, **kwargs):
        _ = kwargs, operation
        events["fs_started"] = time.monotonic()
        result = sync_fn(*args)
        events["fs_finished"] = time.monotonic()
        return result

    async def _fake_cpu(sync_fn, *args, operation=None, **kwargs):
        _ = kwargs, operation
        events["cpu_started"] = time.monotonic()
        await asyncio.sleep(0.15)
        result = sync_fn(*args)
        events["cpu_finished"] = time.monotonic()
        return result

    monkeypatch.setattr(scan, "run_fs_io_async", _fake_fs)
    monkeypatch.setattr(scan, "run_cpu_io_async", _fake_cpu)

    async def _cpu_task():
        return await scan._run_scan_cpu_batch(lambda: "cpu", operation="scan.cpu.test")

    async def _fs_task():
        return await scan._run_scan_fs_batch(lambda: "fs", operation="scan.fs.test")

    cpu_result, fs_result = await asyncio.gather(_cpu_task(), _fs_task())

    assert cpu_result == "cpu"
    assert fs_result == "fs"
    assert events["fs_finished"] < events["cpu_finished"]


@pytest.mark.anyio
async def test_prepare_scan_files_async_resolves_cached_imports_in_fs_stage_and_aggregates_in_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Session:
        async def execute(self, _stmt, _params=None):
            class _Rows:
                def all(self):
                    return []

            return _Rows()

    async def _fake_collect(_root, rel_paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        return [scan.FileStatResult(rel=rel, exists=True, is_file=True, is_supported=True, mtime_ns=1, size=10) for rel in rel_paths]

    async def _fake_read(_root, batch_paths, stats_map, max_file_bytes, max_parallel=8):
        _ = stats_map, max_file_bytes, max_parallel
        return [scan.FileReadResult(rel=rel, text="import x", mtime_ns=1, size=10, oversized=False) for rel in batch_paths]

    async def _fake_parse(project_id, _project_root, file_batch):
        rows = []
        for item in file_batch:
            rows.append(
                {
                    "rel": item.rel,
                    "stat_mtime": 0.0,
                    "stat_mtime_ns": item.mtime_ns,
                    "stat_size": item.size,
                    "file_hash": f"h-{item.rel}",
                    "snapshot_kind": "content",
                    "node_row": {"project_id": project_id, "path": item.rel},
                    "search_row": {"project_id": project_id, "path": item.rel, "content": item.text or ""},
                    "cached_imports": [{"spec": "pkg.mod", "kind": "import", "raw": "import pkg.mod"}],
                    "route_rows": [],
                    "call_rows": [],
                    "include_rows": [],
                    "route_contract_rows": [],
                    "call_meta_rows": [],
                    "ts_type_rows": [],
                    "text": item.text,
                }
            )
        return rows

    fs_operations: list[str] = []
    cpu_operations: list[str] = []
    active_operation: str | None = None

    async def _fake_fs(sync_fn, *args, operation: str):
        nonlocal active_operation
        fs_operations.append(operation)
        previous = active_operation
        active_operation = operation
        try:
            return sync_fn(*args)
        finally:
            active_operation = previous

    async def _fake_cpu(sync_fn, *args, operation: str):
        cpu_operations.append(operation)
        return sync_fn(*args)

    def _resolve_spec_only_from_fs(_root, rel, spec):
        assert active_operation == "scan.fs.cached_import_resolve"
        if rel == "a.py" and spec == "pkg.mod":
            return "pkg/mod.py"
        return None

    def _resolve_under_root_only_from_fs(_root, dst_raw):
        assert active_operation == "scan.fs.cached_import_resolve"
        return (Path("/repo") / dst_raw, dst_raw)

    async def _fake_entitlement(*_args, **_kwargs):
        return False

    monkeypatch.setattr(scan, "_collect_file_stats_async", _fake_collect)
    monkeypatch.setattr(scan, "_read_file_batch_async", _fake_read)
    monkeypatch.setattr(scan, "_parse_index_batch_async", _fake_parse)
    monkeypatch.setattr(scan, "_run_scan_fs_batch", _fake_fs)
    monkeypatch.setattr(scan, "_run_scan_cpu_batch", _fake_cpu)
    monkeypatch.setattr(scan, "resolve_spec", _resolve_spec_only_from_fs)
    monkeypatch.setattr(scan, "resolve_under_root", _resolve_under_root_only_from_fs)
    monkeypatch.setattr(scan, "get_entitlement_bool_async", _fake_entitlement)

    prepared = await scan._prepare_scan_files_async(
        _Session(),
        1,
        1,
        Path("/repo"),
        ["a.py"],
        precomputed_stats={"a.py": (1, 10)},
    )

    assert fs_operations.count("scan.fs.cached_import_resolve") == 1
    assert cpu_operations.count("scan.cpu.cached_import_edges") == 1
    assert ("a.py", "pkg/mod.py", "import") in prepared.edge_map


def test_resolve_cached_imports_fs_sync_and_aggregate_mixed_imports_dedup() -> None:
    project_root = Path("/tmp/stubgraph-edge-test")
    parsed_batch = [
        {
            "rel": "src/a.py",
            "cached_imports": [
                {"spec": "./b", "kind": "import", "raw": "import ./b"},
                {"spec": "pkg.mod", "kind": "import", "raw": "import pkg.mod"},
                {"spec": "dyn", "kind": "runtime_dynamic", "raw": "import('dyn')"},
                {"spec": "./b", "kind": "import", "raw": "import ./b duplicate"},
            ],
        }
    ]

    original_resolve_spec = scan.resolve_spec
    original_resolve_under_root = scan.resolve_under_root

    def _fake_resolve_spec(_root, rel, spec):
        mapping = {
            ("src/a.py", "./b"): "src/b.py",
            ("src/a.py", "pkg.mod"): "pkg/mod.py",
            ("src/a.py", "dyn"): "pkg/dyn.py",
        }
        return mapping.get((rel, spec))

    def _fake_resolve_under_root(_root, dst_raw):
        return (project_root / dst_raw, dst_raw)

    try:
        scan.resolve_spec = _fake_resolve_spec
        scan.resolve_under_root = _fake_resolve_under_root
        resolved = scan._resolve_cached_imports_fs_sync(str(project_root), parsed_batch)
    finally:
        scan.resolve_spec = original_resolve_spec
        scan.resolve_under_root = original_resolve_under_root

    assert resolved == [
        {
            "src_path": "src/a.py",
            "dst_path": "src/b.py",
            "kind": "import",
            "raw": "import ./b",
        },
        {
            "src_path": "src/a.py",
            "dst_path": "pkg/mod.py",
            "kind": "import",
            "raw": "import pkg.mod",
        },
        {
            "src_path": "src/a.py",
            "dst_path": "src/b.py",
            "kind": "import",
            "raw": "import ./b duplicate",
        },
    ]

    edges = scan._aggregate_cached_import_edges_sync(resolved)

    assert edges == [
        {
            "src_path": "src/a.py",
            "dst_path": "src/b.py",
            "kind": "import",
            "raw": "import ./b",
        },
        {
            "src_path": "src/a.py",
            "dst_path": "pkg/mod.py",
            "kind": "import",
            "raw": "import pkg.mod",
        },
    ]



@pytest.mark.anyio
async def test_scan_files_async_parallel_smoke_keeps_base_metrics(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Session:
        async def execute(self, _stmt, _params=None):
            class _Rows:
                def all(self):
                    return []

            return _Rows()

        async def commit(self):
            return None

    rel_paths = [f"f{idx}.py" for idx in range(48)]
    (tmp_path / "shared.py").write_text("VALUE = 1\n", encoding="utf-8")
    for rel in rel_paths:
        (tmp_path / rel).write_text("import shared\n", encoding="utf-8")

    async def _fake_write(*_args, **_kwargs):
        return None

    async def _fake_verify(*_args, **_kwargs):
        return (True, "")

    async def _fake_entitlement(*_args, **_kwargs):
        return False

    monkeypatch.setattr(scan, "AsyncSessionLocal", lambda: _AsyncSessionCtx(_Session()))
    monkeypatch.setattr(scan, "project_lock_async", lambda *_args, **_kwargs: _NoopLock())
    monkeypatch.setattr(scan, "_write_scan_files_async", _fake_write)
    monkeypatch.setattr(scan, "_verify_scan_snapshot_async", _fake_verify)
    monkeypatch.setattr(scan, "get_entitlement_bool_async", _fake_entitlement)

    fs_counters = {"cached_import_resolve": 0}
    cpu_counters = {"parse_batch": 0, "cached_import_edges": 0}

    async def _fs_probe(sync_fn, *args, operation: str, lane: str = "bulk"):
        _ = lane
        if operation == "scan.fs.cached_import_resolve":
            fs_counters["cached_import_resolve"] += 1
        return sync_fn(*args)

    async def _cpu_probe(sync_fn, *args, operation: str):
        if operation == "scan.cpu.parse_batch":
            cpu_counters["parse_batch"] += 1
        if operation == "scan.cpu.cached_import_edges":
            cpu_counters["cached_import_edges"] += 1
        return sync_fn(*args)

    monkeypatch.setattr(scan, "run_fs_io_async", _fs_probe)
    monkeypatch.setattr(scan, "run_cpu_io_async", _cpu_probe)

    timeout_s = 2.0

    async def _one_run(i: int):
        return await asyncio.wait_for(
            scan.scan_files_async(i + 1, 1, tmp_path, rel_paths),
            timeout=timeout_s,
        )

    started = time.monotonic()
    results = await asyncio.gather(*[_one_run(i) for i in range(6)])
    elapsed = time.monotonic() - started

    assert elapsed < timeout_s
    assert all(item.get("aborted") is not True for item in results)
    assert all(item["updated_nodes"] == len(rel_paths) for item in results)
    assert all(item["updated_edges"] > 0 for item in results)
    assert fs_counters["cached_import_resolve"] > 0
    assert cpu_counters["parse_batch"] > 0
    assert cpu_counters["cached_import_edges"] > 0



@pytest.mark.anyio
async def test_prepare_scan_files_async_cached_import_edges_cpu_stage_keeps_loop_responsive(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Session:
        async def execute(self, _stmt, _params=None):
            class _Rows:
                def all(self):
                    return []

            return _Rows()

    rel_paths = [f"f{i}.py" for i in range(120)]

    async def _fake_collect(_root, paths, precomputed_stats=None, batch_size=128, max_parallel=8):
        _ = precomputed_stats, batch_size, max_parallel
        return [scan.FileStatResult(rel=rel, exists=True, is_file=True, is_supported=True, mtime_ns=1, size=10) for rel in paths]

    async def _fake_read(_root, batch_paths, stats_map, max_file_bytes, max_parallel=8):
        _ = stats_map, max_file_bytes, max_parallel
        return [scan.FileReadResult(rel=rel, text="import pkg.mod", mtime_ns=1, size=10, oversized=False) for rel in batch_paths]

    async def _fake_parse(project_id, _project_root, file_batch):
        rows = []
        for item in file_batch:
            rows.append(
                {
                    "rel": item.rel,
                    "stat_mtime": 0.0,
                    "stat_mtime_ns": item.mtime_ns,
                    "stat_size": item.size,
                    "file_hash": f"h-{item.rel}",
                    "snapshot_kind": "content",
                    "node_row": {"project_id": project_id, "path": item.rel},
                    "search_row": {"project_id": project_id, "path": item.rel, "content": item.text or ""},
                    "cached_imports": [{"spec": "pkg.mod", "kind": "import", "raw": "import pkg.mod"}],
                    "route_rows": [],
                    "call_rows": [],
                    "include_rows": [],
                    "route_contract_rows": [],
                    "call_meta_rows": [],
                    "ts_type_rows": [],
                    "text": item.text,
                }
            )
        return rows

    fs_calls = {"cached_import_resolve": 0}
    cpu_calls = {"cached_import_edges": 0}

    async def _fake_fs(sync_fn, *args, operation: str):
        if operation == "scan.fs.cached_import_resolve":
            fs_calls["cached_import_resolve"] += 1
            await asyncio.sleep(0)
        return sync_fn(*args)

    async def _fake_cpu(sync_fn, *args, operation: str):
        if operation == "scan.cpu.cached_import_edges":
            cpu_calls["cached_import_edges"] += 1
            await asyncio.sleep(0.03)
        return sync_fn(*args)

    ticks = {"count": 0}
    stop = asyncio.Event()

    async def _ticker():
        while not stop.is_set():
            ticks["count"] += 1
            await asyncio.sleep(0.002)

    async def _fake_entitlement(*_args, **_kwargs):
        return False

    monkeypatch.setattr(scan.settings, "scan_stage_batch_size", 20)
    monkeypatch.setattr(scan, "_collect_file_stats_async", _fake_collect)
    monkeypatch.setattr(scan, "_read_file_batch_async", _fake_read)
    monkeypatch.setattr(scan, "_parse_index_batch_async", _fake_parse)
    monkeypatch.setattr(scan, "_run_scan_fs_batch", _fake_fs)
    monkeypatch.setattr(scan, "_run_scan_cpu_batch", _fake_cpu)
    monkeypatch.setattr(scan, "resolve_spec", lambda _root, _rel, _spec: "pkg/mod.py")
    monkeypatch.setattr(scan, "resolve_under_root", lambda _root, dst_raw: (Path("/repo") / dst_raw, dst_raw))
    monkeypatch.setattr(scan, "get_entitlement_bool_async", _fake_entitlement)

    ticker_task = asyncio.create_task(_ticker())
    started = time.monotonic()
    try:
        prepared = await asyncio.wait_for(
            scan._prepare_scan_files_async(
                _Session(),
                1,
                1,
                Path("/repo"),
                rel_paths,
                precomputed_stats={rel: (1, 10) for rel in rel_paths},
            ),
            timeout=2.0,
        )
    finally:
        stop.set()
        await ticker_task

    elapsed = time.monotonic() - started

    assert ticks["count"] >= 20
    assert elapsed < 2.0
    assert fs_calls["cached_import_resolve"] > 0
    assert cpu_calls["cached_import_edges"] > 0
    assert prepared.edge_map


@pytest.mark.anyio
async def test_parse_index_batch_runs_on_real_cpu_process_runtime(tmp_path: Path) -> None:
    """Parsing must dispatch a top-level, pickle-safe callable to the CPU process
    runtime. A local closure violates the process contract and raises TypeError,
    so this exercises the real runtime instead of a monkeypatched stub."""
    from app.infra import cpu_runtime

    await cpu_runtime.close_cpu_runtime()
    await cpu_runtime.init_cpu_runtime()
    try:
        text = "x = 1\n"
        batch = [
            scan.FileReadResult(rel="a.py", text=text, mtime_ns=1, size=len(text), oversized=False)
        ]
        rows = await scan._parse_index_batch_async(1, tmp_path, batch)
    finally:
        await cpu_runtime.close_cpu_runtime()

    assert len(rows) == 1
    row = rows[0]
    assert row["rel"] == "a.py"
    assert row["snapshot_kind"] == "content"
    assert row["node_row"] is not None
    assert row["text"] == text
