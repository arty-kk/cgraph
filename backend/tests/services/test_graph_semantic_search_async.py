import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import graph


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, total_candidates: int, rows):
        self._total_candidates = total_candidates
        self._rows = rows
        self.calls = 0

    async def execute(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return _ScalarResult(self._total_candidates)
        return _RowsResult(self._rows)


class _Embeddings:
    @staticmethod
    async def create(**_kwargs):
        return type("Resp", (), {"data": [type("D", (), {"embedding": [1.0, 0.0]})()]})()


class _Client:
    embeddings = _Embeddings()


@pytest.mark.anyio
async def test_search_semantic_async_keeps_event_loop_responsive_during_file_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rows = []
    for i in range(40):
        rel = f"f{i}.py"
        (tmp_path / rel).write_text(f"line-{i}\n" * 20, encoding="utf-8")
        rows.append((rel, 0, "[1.0, 0.0]", "", 0, 0))

    session = _Session(total_candidates=len(rows), rows=rows)

    heartbeat_ticks = 0
    stop_heartbeat = asyncio.Event()

    async def _heartbeat() -> None:
        nonlocal heartbeat_ticks
        while not stop_heartbeat.is_set():
            heartbeat_ticks += 1
            await asyncio.sleep(0.001)

    async def _fake_run_fs_io_async(fn, *args, **kwargs):
        await asyncio.sleep(0.002)
        kwargs.pop("operation", None)
        return fn(*args, **kwargs)

    monkeypatch.setattr(graph, "get_async_openai_client", lambda: _Client())
    monkeypatch.setattr(graph, "run_fs_io_async", _fake_run_fs_io_async)
    monkeypatch.setattr(graph.settings, "embeddings_enabled", True)
    monkeypatch.setattr(graph.settings, "openai_api_key", "test")

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        result = await graph.search_semantic_async(session, 1, tmp_path, "q")
    finally:
        stop_heartbeat.set()
        await heartbeat_task

    assert "results" in result
    assert heartbeat_ticks > 1


@pytest.mark.anyio
async def test_search_semantic_async_keeps_sorting_and_meta_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "a.py").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("gamma\n", encoding="utf-8")
    (tmp_path / "d.py").write_text("delta\n", encoding="utf-8")

    rows = [
        ("a.py", 0, "[1.0, 0.0]", "", 0, 0),
        ("b.py", 0, "[0.7, 0.0]", "", 0, 0),
        ("c.py", 0, "[0.2, 0.0]", "", 0, 0),
        ("d.py", 0, "bad-json", "", 0, 0),
    ]
    session = _Session(total_candidates=5, rows=rows)

    monkeypatch.setattr(graph, "get_async_openai_client", lambda: _Client())
    monkeypatch.setattr(graph.settings, "embeddings_enabled", True)
    monkeypatch.setattr(graph.settings, "openai_api_key", "test")
    monkeypatch.setattr(graph.settings, "embeddings_search_max_candidates", 4)
    monkeypatch.setattr(graph.settings, "embeddings_search_max_results", 2)

    result = await graph.search_semantic_async(session, 1, tmp_path, "q")

    assert [item["path"] for item in result["results"]] == ["a.py", "b.py"]
    assert result["meta"]["compared"] == 3
    assert result["meta"]["returned"] == 2
    assert result["meta"]["truncated"] is True


@pytest.mark.anyio
async def test_read_semantic_candidate_files_async_has_bounded_concurrency_and_backpressure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    max_parallel = 3
    rel_paths = [f"f{i}.py" for i in range(80)]

    in_flight = 0
    peak_in_flight = 0
    lock = asyncio.Lock()
    started_reads = asyncio.Event()
    release_reads = asyncio.Event()
    producer_finished = asyncio.Event()
    heartbeat_ticks = 0
    stop_heartbeat = asyncio.Event()

    async def _fake_run_fs_io_async(fn, *args, **kwargs):
        nonlocal in_flight, peak_in_flight
        async with lock:
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)
            if in_flight >= max_parallel:
                started_reads.set()
        await release_reads.wait()
        kwargs.pop("operation", None)
        result = fn(*args, **kwargs)
        async with lock:
            in_flight -= 1
        return result

    async def _heartbeat() -> None:
        nonlocal heartbeat_ticks
        while not stop_heartbeat.is_set():
            heartbeat_ticks += 1
            await asyncio.sleep(0)

    monkeypatch.setattr(graph, "run_fs_io_async", _fake_run_fs_io_async)

    async def _run_read() -> dict[str, str]:
        result = await graph.read_semantic_candidate_files_async(
            tmp_path,
            rel_paths,
            max_parallel=max_parallel,
            max_rel_path_length=512,
            max_chars=64,
        )
        producer_finished.set()
        return result

    heartbeat_task = asyncio.create_task(_heartbeat())
    read_task = asyncio.create_task(_run_read())

    await started_reads.wait()

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert not producer_finished.is_set()
    assert heartbeat_ticks > 0

    release_reads.set()
    result = await read_task

    stop_heartbeat.set()
    await heartbeat_task

    assert peak_in_flight <= max_parallel
    assert set(result.keys()) == set(rel_paths)
    assert all(payload == "" for payload in result.values())


@pytest.mark.anyio
async def test_read_semantic_candidate_files_async_cancels_workers_on_producer_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _BoomQueue(asyncio.Queue):
        async def put(self, item):
            if item == "boom.py":
                raise RuntimeError("producer failed")
            await super().put(item)

    monkeypatch.setattr(graph.asyncio, "Queue", _BoomQueue)

    with pytest.raises(RuntimeError, match="producer failed"):
        await graph.read_semantic_candidate_files_async(
            tmp_path,
            ["ok.py", "boom.py", "after.py"],
            max_parallel=2,
            max_rel_path_length=512,
            max_chars=64,
        )

@pytest.mark.anyio
async def test_read_semantic_candidate_files_async_keeps_dedup_and_dict_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    rel_paths = ["a.py", "b.py", "a.py", "", "b.py", "c.py"]

    async def _fake_run_fs_io_async(_fn, _root, path, **_kwargs):
        calls.append(path)
        return (path, f"payload:{path}")

    monkeypatch.setattr(graph, "run_fs_io_async", _fake_run_fs_io_async)

    result = await graph.read_semantic_candidate_files_async(
        tmp_path,
        rel_paths,
        max_parallel=4,
        max_rel_path_length=512,
        max_chars=64,
    )

    assert sorted(calls) == ["a.py", "b.py", "c.py"]
    assert result == {
        "a.py": "payload:a.py",
        "b.py": "payload:b.py",
        "c.py": "payload:c.py",
    }


@pytest.mark.anyio
async def test_read_semantic_candidate_files_async_handles_per_item_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def _fake_run_fs_io_async(_fn, _root, path, **_kwargs):
        if path in {"bad-1.py", "bad-2.py"}:
            raise RuntimeError("boom")
        return (path, f"payload:{path}")

    monkeypatch.setattr(graph, "run_fs_io_async", _fake_run_fs_io_async)

    result = await graph.read_semantic_candidate_files_async(
        tmp_path,
        ["ok.py", "bad-1.py", "bad-2.py", "ok2.py"],
        max_parallel=2,
        max_rel_path_length=512,
        max_chars=64,
    )

    assert result == {
        "ok.py": "payload:ok.py",
        "bad-1.py": "",
        "bad-2.py": "",
        "ok2.py": "payload:ok2.py",
    }
