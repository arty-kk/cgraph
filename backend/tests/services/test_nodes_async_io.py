import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.api import nodes


@pytest.mark.anyio
async def test_resolve_under_root_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo/a.py"), "a.py"

    monkeypatch.setattr(nodes, "run_fs_io_async", _fake_fs_runtime)

    result = await nodes._resolve_under_root_async(
        Path("/repo"),
        "a.py",
        max_length=120,
    )

    assert result == (Path("/repo/a.py"), "a.py")
    assert calls["func"] is nodes.resolve_under_root
    assert calls["args"] == (Path("/repo"), "a.py")
    assert calls["kwargs"] == {"max_length": 120, "operation": "nodes.resolve_under_root", "lane": "interactive"}


@pytest.mark.anyio
async def test_resolve_rename_paths_async_resolves_both(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_resolve_under_root_async(root, path, *, max_length):
        _ = root, max_length
        calls.append(path)
        return Path(f"/repo/{path}"), path

    monkeypatch.setattr(nodes, "_resolve_under_root_async", _fake_resolve_under_root_async)

    current, target = await nodes._resolve_rename_paths_async(
        Path("/repo"),
        "a.py",
        "b.py",
        max_length=120,
    )

    assert current == (Path("/repo/a.py"), "a.py")
    assert target == (Path("/repo/b.py"), "b.py")
    assert sorted(calls) == ["a.py", "b.py"]


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

    monkeypatch.setattr(nodes, "run_fs_io_async", _fake_fs_runtime)

    result = await nodes._path_exists_and_is_file_async(Path("/repo/a.py"))

    assert result == (True, True)
    assert calls["func"] is nodes._path_exists_and_is_file
    assert calls["args"] == (Path("/repo/a.py"),)
    assert calls["kwargs"] == {"operation": "nodes.path_is_file", "lane": "interactive"}


@pytest.mark.anyio
async def test_ensure_existing_file_async_raises_for_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_path_exists_and_is_file_async(path: Path):
        _ = path
        return False, False

    monkeypatch.setattr(
        nodes,
        "_path_exists_and_is_file_async",
        _fake_path_exists_and_is_file_async,
    )

    with pytest.raises(nodes.NotFoundError):
        await nodes._ensure_existing_file_async(Path("/repo/missing.py"), "missing.py")


@pytest.mark.anyio
async def test_ensure_existing_file_async_raises_for_not_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_path_exists_and_is_file_async(path: Path):
        _ = path
        return True, False

    monkeypatch.setattr(
        nodes,
        "_path_exists_and_is_file_async",
        _fake_path_exists_and_is_file_async,
    )

    with pytest.raises(nodes.BadRequestError):
        await nodes._ensure_existing_file_async(Path("/repo/dir"), "dir")


@pytest.mark.anyio
async def test_path_exists_and_is_dir_async_uses_fs_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return True, True

    monkeypatch.setattr(nodes, "run_fs_io_async", _fake_fs_runtime)

    result = await nodes._path_exists_and_is_dir_async(Path("/repo/dir"))

    assert result == (True, True)
    assert calls["func"] is nodes._path_exists_and_is_dir
    assert calls["args"] == (Path("/repo/dir"),)
    assert calls["kwargs"] == {"operation": "nodes.path_is_dir", "lane": "interactive"}


@pytest.mark.anyio
async def test_collect_create_path_state_async_runs_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_path_exists_async(path: Path):
        return path.name == "file.py"

    async def _fake_path_exists_and_is_dir_async(path: Path):
        assert path.name == "repo"
        return True, True

    monkeypatch.setattr(nodes, "_path_exists_async", _fake_path_exists_async)
    monkeypatch.setattr(nodes, "_path_exists_and_is_dir_async", _fake_path_exists_and_is_dir_async)

    state = await nodes._collect_create_path_state_async(Path("/tmp/file.py"), Path("/tmp/repo"))

    assert state == (True, True, True)


@pytest.mark.anyio
async def test_collect_rename_path_state_async_runs_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_path_exists_and_is_file_async(path: Path):
        assert path.name == "old.py"
        return True, True

    async def _fake_path_exists_async(path: Path):
        assert path.name == "new.py"
        return False

    async def _fake_path_exists_and_is_dir_async(path: Path):
        assert path.name == "repo"
        return True, True

    monkeypatch.setattr(
        nodes,
        "_path_exists_and_is_file_async",
        _fake_path_exists_and_is_file_async,
    )
    monkeypatch.setattr(nodes, "_path_exists_async", _fake_path_exists_async)
    monkeypatch.setattr(nodes, "_path_exists_and_is_dir_async", _fake_path_exists_and_is_dir_async)

    state = await nodes._collect_rename_path_state_async(
        Path("/tmp/old.py"),
        Path("/tmp/new.py"),
        Path("/tmp/repo"),
    )

    assert state == (True, True, False, True, True)


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(nodes, "run_fs_io_async", _fake_fs_runtime)

    result = await nodes._normalize_project_root_async("/repo")

    assert result == Path("/repo")
    assert calls["func"] is nodes.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {"max_length": nodes.settings.max_root_path_chars, "operation": "nodes.normalize_root", "lane": "interactive"}


@pytest.mark.anyio
async def test_scan_files_async_uses_async_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scan_files_async(project_id: int, org_id: int, root: Path, rel_paths: list[str]):
        assert project_id == 1
        assert org_id == 2
        assert root == Path('/repo')
        assert rel_paths == ['a.py']
        return {'ok': True}

    async def _fail_to_thread(*_args, **_kwargs):
        raise AssertionError('scan path must not use fs runtime for async scan path')

    monkeypatch.setattr(nodes, 'scan_files_async', _fake_scan_files_async)
    monkeypatch.setattr(nodes, 'run_fs_io_async', _fail_to_thread)

    result = await nodes._scan_files_async(1, 2, Path('/repo'), ['a.py'])

    assert result == {'ok': True}
