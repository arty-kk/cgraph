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
