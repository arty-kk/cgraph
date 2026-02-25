from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm.agentic import self_check as self_check_module
from app.llm.agentic.self_check import _run_self_check_async


class _FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._attempt = 0

    async def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        self._attempt += 1
        if self._attempt == 1:
            raise TypeError(
                "responses.create() got an unexpected keyword argument "
                "'parallel_tool_calls'"
            )
        return SimpleNamespace(output_text='{"ok": true, "issues": [], "missing_context": []}')


class _FakeAsyncClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


@pytest.mark.anyio
async def test_run_self_check_async_retries_without_unsupported_keys() -> None:
    client = _FakeAsyncClient()

    result = await _run_self_check_async(
        client=client,
        model="gpt-5-mini",
        reasoning_effort=None,
        user_prompt="ping",
        seed={"a": 1},
        response_payload={"summary": "ok"},
    )

    assert result == {"ok": True, "issues": [], "missing_context": []}
    assert len(client.responses.calls) == 2
    assert "parallel_tool_calls" in client.responses.calls[0]
    assert "parallel_tool_calls" not in client.responses.calls[1]
    assert not hasattr(self_check_module, "_run_self_check")
    assert "openai.Client" not in inspect.getsource(self_check_module)
