import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import async_db, snapshots
from app.config import settings
from app.infra import fs_runtime
from app.llm import client as llm_client


@pytest.mark.anyio
async def test_close_async_db_is_idempotent() -> None:
    await async_db.close_async_db()
    await async_db.close_async_db()


@pytest.mark.anyio
async def test_close_async_db_is_stable_for_repeated_cycles() -> None:
    for _ in range(5):
        await async_db.close_async_db()


@pytest.mark.anyio
async def test_close_async_openai_client_resets_singleton_with_aclose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Client:
        async def aclose(self) -> None:
            calls.append("aclose")

    monkeypatch.setattr(llm_client, "_async_client", _Client())

    await llm_client.close_async_openai_client()

    assert calls == ["aclose"]
    assert llm_client._async_client is None


@pytest.mark.anyio
async def test_close_async_openai_client_fallbacks_to_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Client:
        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(llm_client, "_async_client", _Client())

    await llm_client.close_async_openai_client()

    assert calls == ["close"]
    assert llm_client._async_client is None


@pytest.mark.anyio
async def test_close_async_openai_client_is_noop_when_singleton_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_client, "_async_client", None)

    await llm_client.close_async_openai_client()

    assert llm_client._async_client is None


@pytest.mark.anyio
async def test_close_async_openai_client_is_idempotent_across_many_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Client:
        async def aclose(self) -> None:
            calls.append("aclose")

    monkeypatch.setattr(llm_client, "_async_client", _Client())

    await llm_client.close_async_openai_client()
    await llm_client.close_async_openai_client()
    await llm_client.close_async_openai_client()

    assert calls == ["aclose"]
    assert llm_client._async_client is None


@pytest.mark.anyio
async def test_init_async_openai_client_creates_singleton_once_for_concurrent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []

    class _Client:
        def __init__(self) -> None:
            created.append(self)

    monkeypatch.setattr(llm_client.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(llm_client, "AsyncOpenAI", lambda **_kwargs: _Client())
    monkeypatch.setattr(llm_client, "_async_client", None)
    monkeypatch.setattr(llm_client, "_client_lock", None)
    monkeypatch.setattr(llm_client, "_client_lock_loop", None)

    first, second, third = await asyncio.gather(
        llm_client.init_async_openai_client(),
        llm_client.init_async_openai_client(),
        llm_client.init_async_openai_client(),
    )

    assert first is second is third
    assert len(created) == 1


@pytest.mark.anyio
async def test_get_async_openai_client_requires_explicit_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_client, "_async_client", None)

    with pytest.raises(RuntimeError, match=r"Вызови await init_async_openai_client\(\)"):
        llm_client.get_async_openai_client()


@pytest.mark.anyio
async def test_init_and_close_async_openai_client_support_repeated_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Client:
        async def aclose(self) -> None:
            calls.append("aclose")

    monkeypatch.setattr(llm_client.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(llm_client, "AsyncOpenAI", lambda **_kwargs: _Client())
    monkeypatch.setattr(llm_client, "_async_client", None)
    monkeypatch.setattr(llm_client, "_client_lock", None)
    monkeypatch.setattr(llm_client, "_client_lock_loop", None)

    first = await llm_client.init_async_openai_client()
    assert llm_client.get_async_openai_client() is first

    await llm_client.close_async_openai_client()
    await llm_client.close_async_openai_client()

    assert calls == ["aclose"]
    assert llm_client._async_client is None


@pytest.mark.anyio
async def test_close_fs_runtime_is_idempotent() -> None:
    await fs_runtime.init_fs_runtime()
    await fs_runtime.close_fs_runtime()
    await fs_runtime.close_fs_runtime()


@pytest.mark.anyio
async def test_fs_runtime_lifecycle_with_snapshot_workload() -> None:
    import io
    import zipfile
    from tempfile import TemporaryDirectory

    class _Upload:
        def __init__(self, data: bytes):
            self._data = data
            self._offset = 0

        async def seek(self, offset: int):
            self._offset = offset

        async def read(self, size: int = -1):
            if size <= 0:
                size = len(self._data) - self._offset
            chunk = self._data[self._offset : self._offset + size]
            self._offset += len(chunk)
            return chunk

    def _zip_payload(content: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("repo/README.md", content)
        return buffer.getvalue()

    original_dir = settings.db_dir
    original_backend = settings.storage_backend

    await fs_runtime.close_fs_runtime()

    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            for idx in range(4):
                meta = await snapshots.store_snapshot_upload(
                    _Upload(_zip_payload(f"cycle-{idx}")),
                    f"repo-{idx}.zip",
                )
                root = await snapshots.prepare_snapshot_root_async(meta)
                assert (root / "repo" / "README.md").read_text(encoding="utf-8") == f"cycle-{idx}"
                await snapshots.delete_snapshot_async(meta)

            runtime = fs_runtime._fs_runtime
            assert runtime is not None
            assert runtime.interactive.queue_depth == 0
            assert runtime.bulk.queue_depth == 0
            assert runtime.interactive.in_flight == 0
            assert runtime.bulk.in_flight == 0

            await fs_runtime.close_fs_runtime()
            assert fs_runtime._fs_runtime is None

            await fs_runtime.init_fs_runtime()
            assert fs_runtime._fs_runtime is not None

            await fs_runtime.close_fs_runtime()
            assert fs_runtime._fs_runtime is None
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
