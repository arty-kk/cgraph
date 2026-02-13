import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import docs_service


class _DummySession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.anyio
async def test_collect_compact_contracts_async_skips_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _fake_session_local():
        return _DummySession()

    async def _fake_get_or_build_contract_async(session, project_id, root, path):
        calls.append(path)
        if path == "bad.py":
            raise RuntimeError("boom")
        return {"path": path, "exports": ["x"]}

    monkeypatch.setattr(docs_service, "AsyncSessionLocal", _fake_session_local)
    monkeypatch.setattr(docs_service, "get_or_build_contract_async", _fake_get_or_build_contract_async)
    monkeypatch.setattr(docs_service, "_compact_contract", lambda contract: {"exports": contract.get("exports", [])})

    result = await docs_service._collect_compact_contracts_async(
        1,
        Path("/repo"),
        ["ok.py", "bad.py"],
        max_parallel=2,
    )

    assert calls == ["ok.py", "bad.py"]
    assert result == [{"path": "ok.py", "contract": {"exports": ["x"]}}]


@pytest.mark.anyio
async def test_collect_compact_contracts_async_empty_paths() -> None:
    result = await docs_service._collect_compact_contracts_async(1, Path("/repo"), [])
    assert result == []
