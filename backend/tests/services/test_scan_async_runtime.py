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
    monkeypatch.setattr(scan, "SCAN_STAGE_BATCH_SIZE", 64)
    monkeypatch.setattr(scan, "SCAN_STAGE_MAX_PARALLEL", 4)

    orig_queue = scan.asyncio.Queue

    class _QueueProbe(orig_queue):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            queue_sizes.append(self.maxsize)

    monkeypatch.setattr(scan.asyncio, "Queue", _QueueProbe)

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
    assert collect_batch_sizes[:10] == [64, 64, 64, 64, 64, 64, 64, 64, 64, 24]
    assert captured["queue_sizes"] == [4]


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
    monkeypatch.setattr(scan, "SCAN_STAGE_BATCH_SIZE", 2)
    monkeypatch.setattr(scan, "SCAN_STAGE_MAX_PARALLEL", 2)
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
    monkeypatch.setattr(scan, "SCAN_STAGE_BATCH_SIZE", 2)
    monkeypatch.setattr(scan, "SCAN_STAGE_MAX_PARALLEL", 2)

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
    monkeypatch.setattr(scan, "SCAN_STAGE_BATCH_SIZE", 2)
    monkeypatch.setattr(scan, "SCAN_STAGE_MAX_PARALLEL", 2)

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

    monkeypatch.setattr(scan, "SCAN_STAGE_BATCH_SIZE", 2)
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
