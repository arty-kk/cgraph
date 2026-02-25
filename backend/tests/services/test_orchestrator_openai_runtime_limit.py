import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import external_io_runtime
from app.llm import orchestrator


class _FakeResponses:
    def __init__(self) -> None:
        self.current = 0
        self.max_seen = 0
        self.lock = asyncio.Lock()

    async def create(self, **kwargs):
        _ = kwargs
        async with self.lock:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
        await asyncio.sleep(0.04)
        async with self.lock:
            self.current -= 1
        return type("Resp", (), {"output_text": "{}", "output": []})()


class _FakeClient:
    def __init__(self, responses: _FakeResponses) -> None:
        self.responses = responses


@pytest.mark.anyio
async def test_orchestrator_respects_openai_long_runtime_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = _FakeResponses()
    monkeypatch.setattr(orchestrator, "get_async_openai_client", lambda: _FakeClient(responses))
    monkeypatch.setattr(orchestrator.settings, "openai_io_long_concurrency", 2)
    monkeypatch.setattr(orchestrator.settings, "openai_timeout_seconds", 3.0)

    await external_io_runtime.close_external_io_runtime()
    await external_io_runtime.init_external_io_runtime()

    schema = {"name": "payload", "schema": {"type": "object"}, "strict": True}
    inputs = [{"role": "user", "content": "ping"}]

    results = await asyncio.gather(
        *[
            orchestrator._json_call_with_usage_async("gpt-5-nano", schema, inputs)
            for _ in range(10)
        ]
    )

    assert len(results) == 10
    assert responses.max_seen <= 2

    await external_io_runtime.close_external_io_runtime()
