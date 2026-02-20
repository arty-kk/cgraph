import sys
import ast
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import graph

GRAPH_PATH = Path(__file__).resolve().parents[2] / "app" / "graph.py"
TASK_SERVICE_PATH = Path(__file__).resolve().parents[2] / "app" / "services" / "task_service.py"
RUNTIME_ASYNC_FUNCS = {
    "compute_graph_metrics_async",
    "update_graph_metrics_incremental_async",
    "search_semantic_async",
}


def _find_task_service_async_fn(symbol: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(TASK_SERVICE_PATH.read_text(encoding="utf-8"), filename=str(TASK_SERVICE_PATH))
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == symbol:
            return node
    raise AssertionError(f"Async function `{symbol}` not found in {TASK_SERVICE_PATH}")


def _find_async_functions() -> dict[str, ast.AsyncFunctionDef]:
    tree = ast.parse(GRAPH_PATH.read_text(encoding="utf-8"), filename=str(GRAPH_PATH))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in RUNTIME_ASYNC_FUNCS
    }


def test_graph_runtime_async_functions_do_not_import_or_use_get_session() -> None:
    tree = ast.parse(GRAPH_PATH.read_text(encoding="utf-8"), filename=str(GRAPH_PATH))

    async_funcs = _find_async_functions()
    forbidden_calls: list[str] = []
    for func in async_funcs.values():
        for node in ast.walk(func):
            if isinstance(node, ast.Name) and node.id == "get_session":
                forbidden_calls.append(f"{GRAPH_PATH}:{node.lineno}")

    assert not forbidden_calls, "Forbidden get_session usage in graph runtime async functions"


@pytest.mark.anyio
async def test_update_graph_metrics_incremental_async_uses_async_session_execute(monkeypatch):
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return list(self._rows)

    class _Session:
        def __init__(self):
            self.calls = 0
            self.commits = 0

        async def execute(self, stmt, *_args, **_kwargs):
            self.calls += 1
            stmt_s = str(stmt)
            if "FROM fileedge" in stmt_s and "src_path, fileedge.dst_path" in stmt_s:
                return _Result([("a.py", "b.py")])
            if "FROM fileedge" in stmt_s and "dst_path, count" in stmt_s:
                return _Result([("a.py", 1)])
            if "FROM fileedge" in stmt_s and "src_path, count" in stmt_s:
                return _Result([("a.py", 1)])
            if "SELECT filenode.path, filenode.fan_in, filenode.fan_out" in stmt_s:
                return _Result([("a.py", 1, 1)])
            if "SELECT filenode.id, filenode.path" in stmt_s:
                return _Result([(1, "a.py"), (2, "b.py")])
            return _Result([])

        async def commit(self):
            self.commits += 1

    async def _fail_to_thread(*_args, **_kwargs):
        raise AssertionError("asyncio.to_thread must not be used in incremental async DB path")

    monkeypatch.setattr(graph.asyncio, "to_thread", _fail_to_thread)

    session = _Session()
    result = await graph.update_graph_metrics_incremental_async(
        session,
        1,
        ["a.py"],
        removed_edge_neighbors=None,
    )

    assert result is False
    assert session.calls >= 7
    assert session.commits == 1


@pytest.mark.anyio
async def test_search_semantic_async_uses_async_execute_cpu_to_thread_and_fs_runtime(
    monkeypatch,
    tmp_path: Path,
):
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
        def __init__(self):
            self.calls = 0

        async def execute(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return _ScalarResult(1)
            return _RowsResult(
                [
                    (
                        "a.py",
                        0,
                        "[1.0, 0.0]",
                        "func",
                        0,
                        0,
                    )
                ]
            )

    class _Embeddings:
        @staticmethod
        async def create(**_kwargs):
            return type("Resp", (), {"data": [type("D", (), {"embedding": [1.0, 0.0]})()]})()

    class _Client:
        embeddings = _Embeddings()

    to_thread_calls: list[str] = []
    fs_calls: list[str] = []

    target_file = tmp_path / "a.py"
    target_file.write_text("def func():\n    return 1\n", encoding="utf-8")

    async def _fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func.__name__)
        return func(*args, **kwargs)

    async def _fake_run_fs_io_async(fn, *args, **kwargs):
        fs_calls.append(kwargs.get("operation", ""))
        kwargs.pop("operation", None)
        return fn(*args, **kwargs)

    monkeypatch.setattr(graph, "get_async_openai_client", lambda: _Client())
    monkeypatch.setattr(graph.settings, "embeddings_enabled", True)
    monkeypatch.setattr(graph.settings, "openai_api_key", "test")
    monkeypatch.setattr(graph, "run_fs_io_async", _fake_run_fs_io_async)
    monkeypatch.setattr(graph.asyncio, "to_thread", _fake_to_thread)

    session = _Session()
    result = await graph.search_semantic_async(
        session,
        1,
        tmp_path,
        "find symbol",
        max_results=5,
    )

    assert "results" in result
    assert session.calls == 2
    assert to_thread_calls == ["_score_semantic_candidates_cpu"]
    assert "graph.semantic.read_candidate" in fs_calls


def test_task_service_ensure_node_exists_async_uses_async_graph_metrics() -> None:
    fn = _find_task_service_async_fn("_ensure_node_exists_async")
    has_to_thread_compute_sync = False
    has_async_compute_call = False

    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "asyncio"
                and node.func.attr == "to_thread"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "compute_graph_metrics"
            ):
                has_to_thread_compute_sync = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "compute_graph_metrics_async":
                has_async_compute_call = True

    assert not has_to_thread_compute_sync, (
        "_ensure_node_exists_async must not call asyncio.to_thread(compute_graph_metrics, ...)"
    )
    assert has_async_compute_call, "_ensure_node_exists_async must call compute_graph_metrics_async(...)"
