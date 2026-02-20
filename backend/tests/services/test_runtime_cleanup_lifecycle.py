import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import async_db
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


def test_openai_singleton_recreated_only_after_close(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[object] = []

    class _Client:
        def __init__(self) -> None:
            created.append(self)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(llm_client.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(llm_client, "AsyncOpenAI", lambda **_kwargs: _Client())
    monkeypatch.setattr(llm_client, "_async_client", None)

    first = llm_client.get_async_openai_client()
    second = llm_client.get_async_openai_client()

    assert first is second
    assert len(created) == 1

    import asyncio

    asyncio.run(llm_client.close_async_openai_client())
    third = llm_client.get_async_openai_client()

    assert third is not first
    assert len(created) == 2


@pytest.mark.anyio
async def test_close_fs_runtime_is_idempotent() -> None:
    await fs_runtime.init_fs_runtime()
    await fs_runtime.close_fs_runtime()
    await fs_runtime.close_fs_runtime()
