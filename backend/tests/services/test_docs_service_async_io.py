import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import docs_service


@pytest.mark.anyio
async def test_collect_key_files_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"path": "README.md"}], {"makefiles": []})

    monkeypatch.setattr(docs_service.asyncio, "to_thread", _fake_to_thread)

    result = await docs_service._collect_key_files_async(Path("/repo"), ["README.md"])

    assert result == ([{"path": "README.md"}], {"makefiles": []})
    assert calls["func"] is docs_service._collect_key_files
    assert calls["args"] == (Path("/repo"), ["README.md"])
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_compute_project_summary_facts_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"counts": {"files": 1, "loc": 10}}

    monkeypatch.setattr(docs_service.asyncio, "to_thread", _fake_to_thread)

    result = await docs_service._compute_project_summary_facts_async([("a.py", "python", 10, 1, 1, 1, "ok")])

    assert result == {"counts": {"files": 1, "loc": 10}}
    assert calls["func"] is docs_service._compute_project_summary_facts
    assert calls["kwargs"] == {"hotspots_limit": 25, "hubs_limit": 25, "module_map_limit": 100}


@pytest.mark.anyio
async def test_tree_outline_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"lines": ["- src"], "truncated": False, "max_lines": 1200}

    monkeypatch.setattr(docs_service.asyncio, "to_thread", _fake_to_thread)

    result = await docs_service._tree_outline_async(["src/main.py"], 1200)

    assert result["lines"] == ["- src"]
    assert calls["func"] is docs_service._tree_outline
    assert calls["args"] == (["src/main.py"], 1200)
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_build_run_hints_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ["pytest -q"]

    monkeypatch.setattr(docs_service.asyncio, "to_thread", _fake_to_thread)

    result = await docs_service._build_run_hints_async([{"content": "make test"}], {"makefiles": []})

    assert result == ["pytest -q"]
    assert calls["func"] is docs_service._build_run_hints
    assert calls["args"] == ([{"content": "make test"}], {"makefiles": []})
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_build_docs_markdown_parts_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"module_map_table_md": "m", "hotspots_table_md": "h", "tree_md": "t", "api_md": "a", "run_md": "r", "key_files_md": "k"}

    monkeypatch.setattr(docs_service.asyncio, "to_thread", _fake_to_thread)

    result = await docs_service._build_docs_markdown_parts_async(
        module_rows=[{"module": "src", "files": 1, "loc": 10, "risk_max": 1.0, "top_hotspots": []}],
        hotspots=[{"path": "a.py", "risk": 1.0, "loc": 10, "fan_in": 1, "fan_out": 1, "complexity": 1, "status": "ok"}],
        outline={"lines": ["- src"], "truncated": False},
        run_hints=["pytest -q"],
        key_files=[{"path": "README.md", "role": "readme"}],
        api_summary={"counts": {"routes": 1, "calls": 1, "includes": 0}},
    )

    assert result["module_map_table_md"] == "m"
    assert calls["func"] is docs_service._build_docs_markdown_parts
    assert calls["kwargs"]["run_hints"] == ["pytest -q"]


@pytest.mark.anyio
async def test_select_contract_paths_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ["a.py"]

    monkeypatch.setattr(docs_service.asyncio, "to_thread", _fake_to_thread)

    result = await docs_service._select_contract_paths_async(
        risks=[{"path": "a.py", "risk": 1.0, "fan_out": 1}],
        hotspots=[{"path": "a.py"}],
        hubs=[{"path": "b.py"}],
        paths=["a.py", "b.py"],
    )

    assert result == ["a.py"]
    assert calls["func"] is docs_service._select_contract_paths
    assert calls["kwargs"]["paths"] == ["a.py", "b.py"]


@pytest.mark.anyio
async def test_build_api_summary_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class _Result:
        def __init__(self, *, scalar=None, rows=None):
            self._scalar = scalar
            self._rows = rows or []

        def scalar_one(self):
            return self._scalar

        def all(self):
            return self._rows

    class _Session:
        def __init__(self):
            self._results = [
                _Result(scalar=2),
                _Result(scalar=3),
                _Result(scalar=1),
                _Result(rows=[("GET", 2)]),
                _Result(rows=[("POST", 3)]),
                _Result(rows=[("/api/users",), ("/health",)]),
                _Result(rows=[("/api/users",)]),
            ]

        async def execute(self, _query):
            return self._results.pop(0)

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"counts": {"routes": 2, "calls": 3, "includes": 1}}

    monkeypatch.setattr(docs_service.asyncio, "to_thread", _fake_to_thread)

    result = await docs_service._build_api_summary_async(_Session(), 42)

    assert result == {"counts": {"routes": 2, "calls": 3, "includes": 1}}
    assert calls["func"] is docs_service._build_api_summary_payload
    assert calls["kwargs"]["routes_total"] == 2
    assert calls["kwargs"]["calls_total"] == 3
    assert calls["kwargs"]["includes_total"] == 1


@pytest.mark.anyio
async def test_collect_docs_enrichment_async_runs_contracts_and_api_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_collect_compact_contracts_async(
        project_id: int,
        root: Path,
        contract_paths: list[str],
    ):
        _ = (project_id, root, contract_paths)
        calls.append("contracts")
        return [{"path": "a.py"}]

    async def _fake_build_api_summary_async(session, project_id: int):
        _ = (session, project_id)
        calls.append("api")
        return {"counts": {"routes": 1, "calls": 2, "includes": 0}}

    monkeypatch.setattr(
        docs_service,
        "_collect_compact_contracts_async",
        _fake_collect_compact_contracts_async,
    )
    monkeypatch.setattr(docs_service, "_build_api_summary_async", _fake_build_api_summary_async)

    contracts, api_summary = await docs_service._collect_docs_enrichment_async(
        object(),
        42,
        Path("/repo"),
        ["a.py"],
    )

    assert contracts == [{"path": "a.py"}]
    assert api_summary == {"counts": {"routes": 1, "calls": 2, "includes": 0}}
    assert calls == ["contracts", "api"]


@pytest.mark.anyio
async def test_collect_outline_and_key_files_async_runs_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_tree_outline_async(paths: list[str], max_lines: int = 1200):
        _ = (paths, max_lines)
        calls.append("outline")
        return {"lines": ["- src"], "truncated": False}

    async def _fake_collect_key_files_async(root: Path, paths: list[str]):
        _ = (root, paths)
        calls.append("key_files")
        return ([{"path": "README.md"}], {"makefiles": []})

    monkeypatch.setattr(docs_service, "_tree_outline_async", _fake_tree_outline_async)
    monkeypatch.setattr(docs_service, "_collect_key_files_async", _fake_collect_key_files_async)

    outline, key_files_data = await docs_service._collect_outline_and_key_files_async(
        Path("/repo"),
        ["README.md"],
    )

    assert outline == {"lines": ["- src"], "truncated": False}
    assert key_files_data == ([{"path": "README.md"}], {"makefiles": []})
    assert calls == ["outline", "key_files"]
