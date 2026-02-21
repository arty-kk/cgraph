import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import docs_service


def test_read_text_with_limit_truncates(tmp_path: Path) -> None:
    path = tmp_path / "big.txt"
    path.write_text("abcdef", encoding="utf-8")

    content, truncated = docs_service._read_text_with_limit(path, max_chars=3)

    assert content == "abc"
    assert truncated is True


def test_read_text_with_limit_returns_full_when_short(tmp_path: Path) -> None:
    path = tmp_path / "small.txt"
    path.write_text("abc", encoding="utf-8")

    content, truncated = docs_service._read_text_with_limit(path, max_chars=10)

    assert content == "abc"
    assert truncated is False


@pytest.mark.anyio
async def test_collect_key_files_async_uses_run_fs_io_async(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_run_fs_io_async(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"path": "README.md"}], {"makefiles": []})

    monkeypatch.setattr(docs_service, "run_fs_io_async", _fake_run_fs_io_async)

    result = await docs_service._collect_key_files_async(Path("/repo"), ["README.md"])

    assert result == ([{"path": "README.md"}], {"makefiles": []})
    assert calls["func"] is docs_service._collect_key_files
    assert calls["args"] == (Path("/repo"), ["README.md"])
    assert calls["kwargs"] == {"operation": "docs_service.collect_key_files"}


@pytest.mark.anyio
async def test_compute_project_summary_facts_async_uses_run_cpu_io_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_run_cpu_io_async(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"counts": {"files": 1, "loc": 10}}

    monkeypatch.setattr(docs_service, "run_cpu_io_async", _fake_run_cpu_io_async)

    result = await docs_service._compute_project_summary_facts_async([("a.py", "python", 10, 1, 1, 1, "ok")])

    assert result == {"counts": {"files": 1, "loc": 10}}
    assert calls["func"] is docs_service._compute_project_summary_facts
    assert calls["kwargs"] == {
        "hotspots_limit": 25,
        "hubs_limit": 25,
        "module_map_limit": 100,
        "operation": "docs_service.compute_project_summary_facts",
    }


@pytest.mark.anyio
async def test_tree_outline_async_runs_inline() -> None:
    result = await docs_service._tree_outline_async(["src/main.py"], 1200)

    assert result["lines"] == ["- src", "  - main.py"]


@pytest.mark.anyio
async def test_build_run_hints_async_runs_inline() -> None:
    result = await docs_service._build_run_hints_async([{"content": "make test"}], {"makefiles": []})

    assert isinstance(result, list)


@pytest.mark.anyio
async def test_build_docs_markdown_parts_async_uses_run_cpu_io_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_run_cpu_io_async(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"module_map_table_md": "m", "hotspots_table_md": "h", "tree_md": "t", "api_md": "a", "run_md": "r", "key_files_md": "k"}

    monkeypatch.setattr(docs_service, "run_cpu_io_async", _fake_run_cpu_io_async)

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
    assert calls["kwargs"]["operation"] == "docs_service.build_docs_markdown_parts"


@pytest.mark.anyio
async def test_select_contract_paths_async_runs_inline() -> None:
    result = await docs_service._select_contract_paths_async(
        risks=[{"path": "a.py", "risk": 1.0, "fan_out": 1}],
        hotspots=[{"path": "a.py"}],
        hubs=[{"path": "b.py"}],
        paths=["a.py", "b.py"],
    )

    assert result == ["a.py", "b.py"]


@pytest.mark.anyio
async def test_collect_compact_contracts_async_uses_single_session_and_keeps_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory_calls = 0

    class _SessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _fake_session_local():
        nonlocal session_factory_calls
        session_factory_calls += 1
        return _SessionCtx()

    async def _fake_get_or_build_contract_async(session, project_id, root, path):
        _ = (session, project_id, root)
        if path == "bad.py":
            raise RuntimeError("boom")
        return {"exports": [path]}

    monkeypatch.setattr(docs_service, "AsyncSessionLocal", _fake_session_local)
    monkeypatch.setattr(docs_service, "get_or_build_contract_async", _fake_get_or_build_contract_async)
    monkeypatch.setattr(docs_service, "_compact_contract", lambda contract: {"exports": contract["exports"]})

    result = await docs_service._collect_compact_contracts_async(
        1,
        Path("/repo"),
        ["ok.py", "bad.py", "ok2.py"],
    )

    assert session_factory_calls == 1
    assert result == [
        {"path": "ok.py", "contract": {"exports": ["ok.py"]}},
        {"path": "ok2.py", "contract": {"exports": ["ok2.py"]}},
    ]


@pytest.mark.anyio
async def test_build_api_summary_async_uses_run_cpu_io_async(
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

    async def _fake_run_cpu_io_async(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"counts": {"routes": 2, "calls": 3, "includes": 1}}

    monkeypatch.setattr(docs_service, "run_cpu_io_async", _fake_run_cpu_io_async)

    result = await docs_service._build_api_summary_async(_Session(), 42)

    assert result == {"counts": {"routes": 2, "calls": 3, "includes": 1}}
    assert calls["func"] is docs_service._build_api_summary_payload
    assert calls["kwargs"]["routes_total"] == 2
    assert calls["kwargs"]["calls_total"] == 3
    assert calls["kwargs"]["includes_total"] == 1
    assert calls["kwargs"]["operation"] == "docs_service.build_api_summary"


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


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_run_fs_io_async(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_run_fs_io_async(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(docs_service, "run_fs_io_async", _fake_run_fs_io_async)

    result = await docs_service._normalize_project_root_async("/repo", max_length=321)

    assert result == Path("/repo")
    assert calls["func"] is docs_service.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {
        "max_length": 321,
        "operation": "docs_service.normalize_project_root",
    }


@pytest.mark.anyio
async def test_build_project_docs_async_uses_async_root_normalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExecResult:
        def __init__(self, *, rows=None, scalar=None):
            self._rows = rows or []
            self._scalar = scalar

        def all(self):
            return self._rows

        def scalar_one(self):
            return self._scalar

    class _Session:
        def __init__(self):
            self._exec_results = [
                _ExecResult(rows=[("a.py", "python", 10, 1, 1, 1, "ok")]),
                _ExecResult(scalar=0),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        async def get(self, model, project_id):
            _ = model, project_id
            return type("Project", (), {"org_id": 5, "root_path": "/repo", "name": "Demo"})()

        async def execute(self, stmt):
            _ = stmt
            return self._exec_results.pop(0)

        def add(self, item):
            item.created_at = type("CreatedAt", (), {"isoformat": lambda self: "2026-01-01T00:00:00"})()

        async def commit(self):
            return None

        async def refresh(self, item):
            _ = item
            return None

    async def _fake_normalize_project_root_async(root_path: str, *, max_length: int):
        _ = max_length
        assert root_path == "/repo"
        return Path("/normalized")

    async def _fake_compute_project_summary_facts_async(nodes):
        _ = nodes
        return {
            "risks": [],
            "paths": ["a.py"],
            "languages": {"python": 1},
            "counts": {"loc": 10},
            "hotspots": [],
            "hubs_by_fan_in": [],
            "module_rows": [],
            "module_map": [],
        }

    async def _fake_select_contract_paths_async(**kwargs):
        _ = kwargs
        return ["a.py"]

    async def _fake_collect_docs_enrichment_async(session, project_id, root, contract_paths):
        _ = session, project_id, contract_paths
        assert root == Path("/normalized")
        return [], {"counts": {"routes": 0, "calls": 0, "includes": 0}}

    async def _fake_collect_outline_and_key_files_async(root, paths):
        _ = paths
        assert root == Path("/normalized")
        return {"lines": [], "truncated": False}, ([], {"makefiles": []})

    async def _fake_build_run_hints_async(key_files, parsed):
        _ = key_files, parsed
        return []

    async def _fake_build_docs_markdown_parts_async(**kwargs):
        _ = kwargs
        return {
            "hotspots_table_md": "",
            "module_map_table_md": "",
            "tree_md": "",
            "api_md": "",
            "run_md": "",
            "key_files_md": "",
        }

    generate_docs_async_call: dict[str, object] = {"called": False, "facts": None}

    async def _fake_generate_docs_async(facts):
        generate_docs_async_call["called"] = True
        generate_docs_async_call["facts"] = facts
        return {"markdown": "ok"}

    session_factory_calls = {"count": 0}

    def _fake_async_session_local():
        session_factory_calls["count"] += 1
        return _Session()

    monkeypatch.setattr(docs_service, "AsyncSessionLocal", _fake_async_session_local)
    monkeypatch.setattr(docs_service, "_normalize_project_root_async", _fake_normalize_project_root_async)
    monkeypatch.setattr(
        docs_service,
        "normalize_project_root",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("sync normalize_project_root must not be used")
        ),
    )
    monkeypatch.setattr(
        docs_service,
        "_compute_project_summary_facts_async",
        _fake_compute_project_summary_facts_async,
    )
    monkeypatch.setattr(docs_service, "_select_contract_paths_async", _fake_select_contract_paths_async)
    monkeypatch.setattr(
        docs_service,
        "_collect_docs_enrichment_async",
        _fake_collect_docs_enrichment_async,
    )
    monkeypatch.setattr(
        docs_service,
        "_collect_outline_and_key_files_async",
        _fake_collect_outline_and_key_files_async,
    )
    monkeypatch.setattr(docs_service, "_build_run_hints_async", _fake_build_run_hints_async)
    monkeypatch.setattr(
        docs_service,
        "_build_docs_markdown_parts_async",
        _fake_build_docs_markdown_parts_async,
    )
    monkeypatch.setattr(docs_service, "generate_docs_async", _fake_generate_docs_async)
    monkeypatch.setattr(
        docs_service,
        "generate_docs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("sync generate_docs must not be used in async runtime")
        ),
        raising=False,
    )

    result = await docs_service.build_project_docs_async(project_id=1, org_id=5)

    assert result["project_id"] == 1
    assert session_factory_calls["count"] == 2
    assert generate_docs_async_call["called"] is True
    assert isinstance(generate_docs_async_call["facts"], dict)
    assert generate_docs_async_call["facts"]["project"]["id"] == 1
