import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.api import nodes


@pytest.mark.anyio
async def test_read_text_limited_async_uses_to_thread(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return "content", False

    monkeypatch.setattr(nodes.asyncio, "to_thread", _fake_to_thread)

    result = await nodes._read_text_limited_async("/tmp/file.txt", 100)

    assert result == ("content", False)
    assert calls["func"] is nodes._read_text_limited
    assert calls["args"] == ("/tmp/file.txt", 100)
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_scan_files_async_uses_to_thread(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(nodes.asyncio, "to_thread", _fake_to_thread)

    result = await nodes._scan_files_async(1, 2, Path("/repo"), ["a.py"])

    assert result == {"ok": True}
    assert calls["func"] is nodes.scan_files
    assert calls["args"] == (1, 2, Path("/repo"), ["a.py"])
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_path_exists_async_uses_to_thread(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return True

    monkeypatch.setattr(nodes.asyncio, "to_thread", _fake_to_thread)

    path = Path("/tmp/a.txt")
    result = await nodes._path_exists_async(path)

    assert result is True
    assert calls["func"] == path.exists
    assert calls["args"] == ()
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_invalidate_pack_cache_async_uses_async_cache(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_cache_invalidate_prefix_async(parts):
        calls["parts"] = parts

    monkeypatch.setattr(nodes, "cache_invalidate_prefix_async", _fake_cache_invalidate_prefix_async)

    await nodes._invalidate_pack_cache_async(42)

    assert calls["parts"] == ["project:42", "pack"]


@pytest.mark.anyio
async def test_update_graph_metrics_incremental_async_uses_to_thread(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return None

    monkeypatch.setattr(nodes.asyncio, "to_thread", _fake_to_thread)

    await nodes._update_graph_metrics_incremental_async(
        7, ["repo/main.py"], removed_edge_neighbors=["repo/dep.py"]
    )

    assert calls["func"] is nodes.update_graph_metrics_incremental
    assert calls["args"] == (7, ["repo/main.py"])
    assert calls["kwargs"] == {"removed_edge_neighbors": ["repo/dep.py"]}
