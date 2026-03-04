import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import contracts


@pytest.mark.anyio
async def test_read_text_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return "payload"

    monkeypatch.setattr(contracts, "run_fs_io_async", _fake_fs_runtime)

    path = Path("/tmp/module.py")
    result = await contracts._read_text_async(path)

    assert result == "payload"
    assert calls["func"] == path.read_text
    assert calls["args"] == ()
    assert calls["kwargs"] == {
        "encoding": "utf-8",
        "errors": "replace",
        "operation": "contracts.read_text",
    }


@pytest.mark.anyio
async def test_build_contract_payload_cpu_async_uses_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"path": "src/main.py"}

    monkeypatch.setattr(contracts, "run_cpu_io_async", _fake_cpu_runtime)

    result = await contracts._build_contract_payload_cpu_async(
        "/repo",
        "src/main.py",
        "/repo/src/main.py",
        "print('ok')",
    )

    assert result == {"path": "src/main.py"}
    assert calls["func"] is contracts._build_contract_payload_cpu
    assert calls["args"] == (
        "/repo",
        "src/main.py",
        "/repo/src/main.py",
        "print('ok')",
    )
    assert calls["kwargs"] == {"operation": "contracts.build_payload_cpu"}


@pytest.mark.anyio
async def test_resolve_under_root_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo/a.py"), "a.py"

    monkeypatch.setattr(contracts, "run_fs_io_async", _fake_fs_runtime)

    result = await contracts._resolve_under_root_async(Path("/repo"), "a.py")

    assert result == (Path("/repo/a.py"), "a.py")
    assert calls["func"] is contracts.resolve_under_root
    assert calls["args"] == (Path("/repo"), "a.py")
    assert calls["kwargs"] == {"operation": "contracts.resolve_under_root"}


@pytest.mark.anyio
async def test_path_exists_and_is_file_async_uses_fs_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return True, True

    monkeypatch.setattr(contracts, "run_fs_io_async", _fake_fs_runtime)

    result = await contracts._path_exists_and_is_file_async(Path("/repo/a.py"))

    assert result == (True, True)
    assert calls["func"] is contracts._path_exists_and_is_file
    assert calls["args"] == (Path("/repo/a.py"),)
    assert calls["kwargs"] == {"operation": "contracts.path_is_file"}


@pytest.mark.anyio
async def test_resolve_path_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(contracts, "run_fs_io_async", _fake_fs_runtime)

    path = Path("/repo")
    result = await contracts._resolve_path_async(path)

    assert result == Path("/repo")
    assert calls["func"] == path.resolve
    assert calls["args"] == ()
    assert calls["kwargs"] == {"operation": "contracts.resolve_path"}


@pytest.mark.anyio
async def test_contract_payload_cpu_and_fs_enrichment_preserve_shape_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Import:
        def __init__(self, n: int):
            self.spec = f"./dep{n}"
            self.kind = "import"
            self.raw = f"import dep{n}"

    class _Symbol:
        def __init__(self, n: int):
            self.name = f"symbol_{n}"
            self.kind = "function"
            self.signature = f"symbol_{n}()"
            self.doc = "doc"
            self.start_line = n
            self.end_line = n + 1

    class _Indexer:
        def parse_exports(self, _path, _text):
            return ["symbol_0"]

        def parse_imports(self, _path, _text):
            return [_Import(i) for i in range(contracts.MAX_CONTRACT_IMPORTS + 25)]

        def parse_symbols(self, _path, _text):
            return [_Symbol(i) for i in range(contracts.MAX_CONTRACT_SYMBOLS + 25)]

        def parse_module_doc(self, _path, _text):
            return " module doc "

        def language(self):
            return "python"

    monkeypatch.setattr(contracts, "pick_indexer", lambda _rel: _Indexer())
    monkeypatch.setattr(contracts, "resolve_spec", lambda _root, _rel, spec: f"resolved/{spec}")

    payload = contracts._build_contract_payload_cpu(
        "/repo",
        "src/main.py",
        "/repo/src/main.py",
        "print('ok')",
    )

    assert payload["version"] == contracts.CONTRACT_VERSION
    assert payload["path"] == "src/main.py"
    assert payload["module_doc"] == "module doc"
    assert payload["imports"] and payload["imports"][0]["resolved_path"] is None
    assert len(payload["imports"]) == contracts.MAX_CONTRACT_IMPORTS
    assert len(payload["symbols"]) == contracts.MAX_CONTRACT_SYMBOLS

    enriched_imports = contracts._resolve_contract_imports(
        Path("/repo"),
        "src/main.py",
        payload["imports"],
    )

    assert len(enriched_imports) == contracts.MAX_CONTRACT_IMPORTS
    assert enriched_imports[0]["resolved_path"] == "resolved/./dep0"
    assert payload["symbols"][0]["exported"] is True


@pytest.mark.anyio
async def test_get_or_build_contract_async_uses_async_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Existing:
        file_hash = "hash"
        contract_json = '{"version": 2, "path": "a.py"}'
        path = "a.py"

    class _ExecResult:
        def scalars(self):
            return self

        def first(self):
            return _Existing()

    class _Session:
        async def execute(self, stmt):
            _ = stmt
            return _ExecResult()

        def add(self, item):
            _ = item

        async def commit(self):
            return None

    async def _fake_resolve_under_root_async(project_root, rel_path):
        _ = project_root, rel_path
        return Path("/repo/a.py"), "a.py"

    monkeypatch.setattr(contracts, "_resolve_under_root_async", _fake_resolve_under_root_async)
    monkeypatch.setattr(
        contracts,
        "resolve_under_root",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("sync resolve_under_root must not be used")
        ),
    )
    monkeypatch.setattr(
        contracts,
        "_path_exists_and_is_file_async",
        lambda p: __import__("asyncio").sleep(0, result=(True, True)),
    )
    monkeypatch.setattr(
        contracts,
        "_sha256_file_async",
        lambda p: __import__("asyncio").sleep(0, result="hash"),
    )

    result = await contracts.get_or_build_contract_async(
        _Session(),
        project_id=7,
        project_root=Path("/repo"),
        rel_path="a.py",
    )

    assert result["path"] == "a.py"
    assert result["version"] == 2


@pytest.mark.anyio
async def test_resolve_contract_imports_async_uses_fs_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return [{"spec": "./dep", "kind": "import", "raw": "import", "resolved_path": "src/dep.py"}]

    monkeypatch.setattr(contracts, "run_fs_io_async", _fake_fs_runtime)

    result = await contracts._resolve_contract_imports_async(
        Path("/repo"),
        "src/main.py",
        [{"spec": "./dep", "kind": "import", "raw": "import", "resolved_path": None}],
    )

    assert result[0]["resolved_path"] == "src/dep.py"
    assert calls["func"] is contracts._resolve_contract_imports
    assert calls["kwargs"] == {"operation": "contracts.resolve_imports"}


@pytest.mark.anyio
async def test_get_or_build_contract_async_uses_path_exists_and_is_file_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Existing:
        file_hash = "hash"
        contract_json = '{"version": 2, "path": "a.py"}'
        path = "a.py"

    class _ExecResult:
        def scalars(self):
            return self

        def first(self):
            return _Existing()

    class _Session:
        async def execute(self, stmt):
            _ = stmt
            return _ExecResult()

        def add(self, item):
            _ = item

        async def commit(self):
            return None

    async def _fake_resolve_under_root_async(project_root, rel_path):
        _ = project_root, rel_path
        return Path("/repo/a.py"), "a.py"

    calls = {"path_state": 0}

    async def _fake_path_exists_and_is_file_async(path: Path):
        _ = path
        calls["path_state"] += 1
        return True, True

    monkeypatch.setattr(contracts, "_resolve_under_root_async", _fake_resolve_under_root_async)
    monkeypatch.setattr(
        contracts,
        "_path_exists_and_is_file_async",
        _fake_path_exists_and_is_file_async,
    )
    monkeypatch.setattr(
        contracts,
        "_sha256_file_async",
        lambda p: __import__("asyncio").sleep(0, result="hash"),
    )

    result = await contracts.get_or_build_contract_async(
        _Session(),
        project_id=7,
        project_root=Path("/repo"),
        rel_path="a.py",
    )

    assert result["path"] == "a.py"
    assert calls["path_state"] == 1


@pytest.mark.anyio
async def test_get_or_build_contract_async_routes_parse_to_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExecResult:
        def scalars(self):
            return self

        def first(self):
            return None

    class _Session:
        async def execute(self, _stmt):
            return _ExecResult()

        def add(self, _item):
            return None

        async def commit(self):
            return None

    cpu_calls = []
    fs_ops = []

    async def _fake_cpu_runtime(func, *args, operation=None, **kwargs):
        cpu_calls.append(operation)
        return func(*args, **kwargs)

    async def _fake_fs_runtime(func, *args, operation=None, **kwargs):
        fs_ops.append(operation)
        return func(*args, **kwargs)

    class _Import:
        spec = "./dep"
        kind = "import"
        raw = "import dep"

    class _Indexer:
        def parse_exports(self, _path, _text):
            return ["run"]

        def parse_imports(self, _path, _text):
            return [_Import()]

        def parse_symbols(self, _path, _text):
            return []

        def language(self):
            return "python"

    monkeypatch.setattr(contracts, "run_cpu_io_async", _fake_cpu_runtime)
    monkeypatch.setattr(contracts, "run_fs_io_async", _fake_fs_runtime)
    monkeypatch.setattr(contracts, "pick_indexer", lambda _rel: _Indexer())
    monkeypatch.setattr(contracts, "resolve_spec", lambda _root, _rel, _spec: "src/dep.py")
    monkeypatch.setattr(
        contracts, "_resolve_path_async", lambda p: __import__("asyncio").sleep(0, result=p)
    )
    monkeypatch.setattr(
        contracts,
        "_resolve_under_root_async",
        lambda root, rel: __import__("asyncio").sleep(0, result=(root / rel, rel)),
    )
    monkeypatch.setattr(
        contracts,
        "_path_exists_and_is_file_async",
        lambda p: __import__("asyncio").sleep(0, result=(True, True)),
    )
    monkeypatch.setattr(
        contracts,
        "_sha256_file_async",
        lambda p: __import__("asyncio").sleep(0, result="hash"),
    )
    monkeypatch.setattr(
        contracts,
        "_read_text_async",
        lambda p: __import__("asyncio").sleep(0, result="print('ok')"),
    )

    result = await contracts.get_or_build_contract_async(
        _Session(),
        project_id=7,
        project_root=Path("/repo"),
        rel_path="a.py",
    )

    assert result["imports"][0]["resolved_path"] == "src/dep.py"
    assert "contracts.build_payload_cpu" in cpu_calls
    assert "contracts.build_payload" not in fs_ops
    assert "contracts.resolve_imports" in fs_ops


@pytest.mark.anyio
async def test_get_or_build_contract_async_concurrency_cpu_stage_does_not_block_fs_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExecResult:
        def scalars(self):
            return self

        def first(self):
            return None

    class _Session:
        async def execute(self, _stmt):
            return _ExecResult()

        def add(self, _item):
            return None

        async def commit(self):
            return None

    class _Indexer:
        def parse_exports(self, _path, _text):
            return []

        def parse_imports(self, _path, _text):
            return []

        def parse_symbols(self, _path, _text):
            return []

        def language(self):
            return "python"

    fs_enter_times: list[float] = []
    cpu_in_flight = 0
    max_cpu_in_flight = 0

    async def _fake_cpu_runtime(func, *args, operation=None, **kwargs):
        nonlocal cpu_in_flight, max_cpu_in_flight
        _ = operation
        cpu_in_flight += 1
        max_cpu_in_flight = max(max_cpu_in_flight, cpu_in_flight)
        await asyncio.sleep(0.03)
        try:
            return func(*args, **kwargs)
        finally:
            cpu_in_flight -= 1

    async def _fake_fs_runtime(func, *args, operation=None, **kwargs):
        _ = operation
        fs_enter_times.append(time.perf_counter())
        await asyncio.sleep(0)
        return func(*args, **kwargs)

    monkeypatch.setattr(contracts, "run_cpu_io_async", _fake_cpu_runtime)
    monkeypatch.setattr(contracts, "run_fs_io_async", _fake_fs_runtime)
    monkeypatch.setattr(contracts, "pick_indexer", lambda _rel: _Indexer())
    monkeypatch.setattr(
        contracts, "_resolve_path_async", lambda p: __import__("asyncio").sleep(0, result=p)
    )
    monkeypatch.setattr(
        contracts,
        "_resolve_under_root_async",
        lambda root, rel: __import__("asyncio").sleep(0, result=(root / rel, rel)),
    )
    monkeypatch.setattr(
        contracts,
        "_path_exists_and_is_file_async",
        lambda p: __import__("asyncio").sleep(0, result=(True, True)),
    )
    monkeypatch.setattr(
        contracts,
        "_sha256_file_async",
        lambda p: __import__("asyncio").sleep(0, result=f"hash-{p.name}"),
    )
    monkeypatch.setattr(
        contracts,
        "_read_text_async",
        lambda p: __import__("asyncio").sleep(0, result="print('ok')"),
    )

    await asyncio.gather(
        *[
            contracts.get_or_build_contract_async(
                _Session(),
                project_id=11,
                project_root=Path("/repo"),
                rel_path=f"src/file_{i}.py",
            )
            for i in range(20)
        ]
    )

    assert max_cpu_in_flight > 1
    assert len(fs_enter_times) >= 20


@pytest.mark.anyio
async def test_get_or_build_contract_async_normalizes_path_for_cached_record() -> None:
    class _Existing:
        file_hash = "hash"
        contract_json = (
            '{"version": 2, "path": "legacy/main.py", "exports": [], "imports": [], "symbols": []}'
        )
        path = "legacy/main.py"

    class _ExecResult:
        def scalars(self):
            return self

        def first(self):
            return _Existing()

    class _Session:
        def __init__(self):
            self.added = []
            self.commits = 0
            self.statements = []

        async def execute(self, stmt):
            self.statements.append(stmt)
            return _ExecResult()

        def add(self, item):
            self.added.append(item)

        async def commit(self):
            self.commits += 1

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        contracts,
        "_resolve_path_async",
        lambda p: __import__("asyncio").sleep(0, result=p),
    )
    monkeypatch.setattr(
        contracts,
        "_resolve_under_root_async",
        lambda root, rel: __import__("asyncio").sleep(
            0, result=(Path("/repo/src/main.py"), "src/main.py")
        ),
    )
    monkeypatch.setattr(
        contracts,
        "_path_exists_and_is_file_async",
        lambda p: __import__("asyncio").sleep(0, result=(True, True)),
    )
    monkeypatch.setattr(
        contracts,
        "_sha256_file_async",
        lambda p: __import__("asyncio").sleep(0, result="hash"),
    )

    session = _Session()
    result = await contracts.get_or_build_contract_async(
        session,
        11,
        Path("/repo"),
        "legacy/../src/main.py",
    )

    monkeypatch.undo()

    assert result["path"] == "src/main.py"
    assert session.commits == 1
    assert session.added and session.added[0].path == "src/main.py"
