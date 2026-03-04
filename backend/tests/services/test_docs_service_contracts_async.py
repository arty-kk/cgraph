import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import docs_service


@pytest.mark.anyio
async def test_collect_compact_contracts_async_skips_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_get_or_build_contract_async(session, project_id, root, path):
        _ = (session, project_id, root)
        calls.append(path)
        if path == "bad.py":
            raise RuntimeError("boom")
        return {"path": path, "exports": ["x"]}

    monkeypatch.setattr(docs_service, "get_or_build_contract_async", _fake_get_or_build_contract_async)
    monkeypatch.setattr(docs_service, "_compact_contract", lambda contract: {"exports": contract.get("exports", [])})

    result = await docs_service._collect_compact_contracts_async(
        object(),
        1,
        Path("/repo"),
        ["ok.py", "bad.py"],
        max_parallel=2,
    )

    assert calls == ["ok.py", "bad.py"]
    assert result == [{"path": "ok.py", "contract": {"exports": ["x"]}}]


@pytest.mark.anyio
async def test_collect_compact_contracts_async_empty_paths() -> None:
    result = await docs_service._collect_compact_contracts_async(object(), 1, Path("/repo"), [])
    assert result == []


def test_collect_compact_contracts_async_does_not_open_session_per_item() -> None:
    source = Path(docs_service.__file__).read_text(encoding="utf-8")
    marker = "async def _collect_compact_contracts_async"
    start = source.index(marker)
    end = source.index("\n\ndef _build_run_hints", start)
    body = source[start:end]
    assert "AsyncSessionLocal" not in body


@pytest.mark.anyio
async def test_collect_docs_enrichment_async_avoids_parallel_session_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _NoParallelExecuteSession:
        def __init__(self) -> None:
            self.in_execute = False

        async def execute(self, _query):
            if self.in_execute:
                raise RuntimeError("parallel execute is not allowed")
            self.in_execute = True
            events.append("execute:start")
            try:
                await asyncio.sleep(0)
                events.append("execute:end")
                return object()
            finally:
                self.in_execute = False

    async def _fake_collect_compact_contracts_async(session, project_id, root, contract_paths):
        _ = (project_id, root, contract_paths)
        events.append("contracts:start")
        await session.execute("contracts")
        events.append("contracts:end")
        return [{"path": "a.py"}]

    async def _fake_build_api_summary_async(session, project_id):
        _ = project_id
        events.append("api:start")
        await session.execute("api")
        events.append("api:end")
        return {"counts": {"routes": 1, "calls": 2, "includes": 0}}

    monkeypatch.setattr(docs_service, "_collect_compact_contracts_async", _fake_collect_compact_contracts_async)
    monkeypatch.setattr(docs_service, "_build_api_summary_async", _fake_build_api_summary_async)

    contracts, api_summary = await docs_service._collect_docs_enrichment_async(
        _NoParallelExecuteSession(),
        1,
        Path("/repo"),
        ["a.py"],
    )

    assert contracts == [{"path": "a.py"}]
    assert api_summary == {"counts": {"routes": 1, "calls": 2, "includes": 0}}
    assert events == [
        "contracts:start",
        "execute:start",
        "execute:end",
        "contracts:end",
        "api:start",
        "execute:start",
        "execute:end",
        "api:end",
    ]
