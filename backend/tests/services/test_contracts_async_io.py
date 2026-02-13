import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import contracts


@pytest.mark.anyio
async def test_read_text_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return "payload"

    monkeypatch.setattr(contracts.asyncio, "to_thread", _fake_to_thread)

    path = Path("/tmp/module.py")
    result = await contracts._read_text_async(path)

    assert result == "payload"
    assert calls["func"] == path.read_text
    assert calls["args"] == ()
    assert calls["kwargs"] == {"encoding": "utf-8", "errors": "replace"}


@pytest.mark.anyio
async def test_build_contract_payload_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"path": "src/main.py"}

    monkeypatch.setattr(contracts.asyncio, "to_thread", _fake_to_thread)

    result = await contracts._build_contract_payload_async(
        Path("/repo"),
        "src/main.py",
        Path("/repo/src/main.py"),
        "print('ok')",
    )

    assert result == {"path": "src/main.py"}
    assert calls["func"] is contracts._build_contract_payload
    assert calls["args"] == (
        Path("/repo"),
        "src/main.py",
        Path("/repo/src/main.py"),
        "print('ok')",
    )
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_resolve_under_root_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo/a.py"), "a.py"

    monkeypatch.setattr(contracts.asyncio, "to_thread", _fake_to_thread)

    result = await contracts._resolve_under_root_async(Path("/repo"), "a.py")

    assert result == (Path("/repo/a.py"), "a.py")
    assert calls["func"] is contracts.resolve_under_root
    assert calls["args"] == (Path("/repo"), "a.py")
    assert calls["kwargs"] == {}


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
        lambda p: __import__('asyncio').sleep(0, result=(True, True)),
    )
    monkeypatch.setattr(
        contracts,
        "_sha256_file_async",
        lambda p: __import__('asyncio').sleep(0, result="hash"),
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
async def test_path_exists_and_is_file_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return True, True

    monkeypatch.setattr(contracts.asyncio, "to_thread", _fake_to_thread)

    result = await contracts._path_exists_and_is_file_async(Path("/repo/a.py"))

    assert result == (True, True)
    assert calls["func"] is contracts._path_exists_and_is_file
    assert calls["args"] == (Path("/repo/a.py"),)
    assert calls["kwargs"] == {}


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
        lambda p: __import__('asyncio').sleep(0, result="hash"),
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
async def test_resolve_path_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(contracts.asyncio, "to_thread", _fake_to_thread)

    path = Path("/repo")
    result = await contracts._resolve_path_async(path)

    assert result == Path("/repo")
    assert calls["func"] == path.resolve
    assert calls["args"] == ()
    assert calls["kwargs"] == {}
