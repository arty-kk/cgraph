import sys
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
    monkeypatch.setattr(scan, "get_session", _fail_get_session)

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
    monkeypatch.setattr(scan, "_verify_scan_snapshot", lambda *_args, **_kwargs: (False, "changed"))

    result = await scan.scan_files_async(1, 2, Path("/repo"), ["a.py"])

    assert result["aborted"] is True
    assert result["reason"] == "snapshot_mismatch"
    assert calls["prepare"] == 2
    assert calls["write"] == 0


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
