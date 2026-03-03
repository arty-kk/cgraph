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
