# ruff: noqa: I001
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm.agentic.call import _agentic_json_call_async



class _FakeResponses:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = 0

    async def create(self, **kwargs):
        assert kwargs.get("model") == "gpt-5-mini"
        self.calls += 1
        return self._payloads.pop(0)


class _FakeClient:
    def __init__(self, payloads):
        self.responses = _FakeResponses(payloads)


@pytest.mark.anyio
async def test_agentic_retry_aggregates_usage_tokens(monkeypatch):
    first_resp = SimpleNamespace(
        output=[],
        output_text=(
            '{"summary": "first", "sources": '
            '[{"path": "a.py", "line_start": 1, "line_end": 1}]}'
        ),
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens="2", total_tokens=12),
    )
    second_resp = SimpleNamespace(
        output=[],
        output_text=(
            '{"summary": "second", "sources": '
            '[{"path": "a.py", "start_line": 1, "end_line": 1}]}'
        ),
        usage={"prompt_tokens": "7", "completion_tokens": 3, "total_tokens": "10"},
    )

    fake_client = _FakeClient([first_resp, second_resp])
    monkeypatch.setattr("app.llm.agentic.call.get_async_openai_client", lambda: fake_client)
    monkeypatch.setattr("app.llm.agentic.call._tool_definitions", lambda _max_file_chars: [])

    async def _fake_self_check_async(**kwargs):
        return {"ok": True, "issues": [], "missing_context": []}

    monkeypatch.setattr("app.llm.agentic.call._run_self_check_async", _fake_self_check_async)

    result, meta = await _agentic_json_call_async(
        session=object(),
        model="gpt-5-mini",
        self_check_model=None,
        self_check_reasoning_effort=None,
        schema={"name": "result", "schema": {"type": "object"}, "strict": True},
        project_id=1,
        root=Path("."),
        seed={"target_path": "a.py"},
        user_prompt="do work",
        reasoning_effort=None,
        evidence_mode=True,
        allow_self_check_retry=False,
        allow_evidence_retry=True,
    )

    assert result["summary"] == "second"
    assert isinstance(result.get("sources"), list)
    assert fake_client.responses.calls == 2
    assert meta.prompt_tokens == 17
    assert meta.completion_tokens == 5
    assert meta.total_tokens == 22


@pytest.mark.anyio
async def test_agentic_usage_retry_uses_async_tool_dispatch(monkeypatch):
    first_resp = SimpleNamespace(
        output=[],
        output_text='{"summary":"ok","sources":[]}',
        usage=None,
    )
    fake_client = _FakeClient([first_resp])
    monkeypatch.setattr("app.llm.agentic.call.get_async_openai_client", lambda: fake_client)

    tool_defs = [
        {
            "type": "function",
            "name": "search_tests",
            "description": "x",
            "parameters": {"type": "object", "properties": {}, "required": []},
            "strict": True,
        }
    ]
    monkeypatch.setattr(
        "app.llm.agentic.call._tool_definitions",
        lambda _max_file_chars: tool_defs,
    )

    async def _fake_dispatch(*_args, **_kwargs):
        return {"ok": True, "data": {"results": []}, "error": None}

    monkeypatch.setattr("app.llm.agentic.call._dispatch_tool_async", _fake_dispatch)

    result, _meta = await _agentic_json_call_async(
        session=object(),
        model="gpt-5-mini",
        self_check_model=None,
        self_check_reasoning_effort=None,
        schema={"name": "result", "schema": {"type": "object"}, "strict": True},
        project_id=1,
        root=Path("."),
        seed={"target_path": "a.py"},
        user_prompt="do work",
        reasoning_effort=None,
        evidence_mode=False,
        allow_self_check_retry=False,
        allow_evidence_retry=False,
    )

    assert result["summary"] == "ok"


@pytest.mark.anyio
async def test_agentic_tool_cache_keeps_canonical_output_for_next_call(monkeypatch):
    long_text = "L" * 240
    tool_payload = {"ok": True, "data": {"results": [{"text": long_text}]}, "error": None}
    dispatch_calls = 0
    shared_tool_cache = {}

    class _InspectableResponses(_FakeResponses):
        def __init__(self, payloads):
            super().__init__(payloads)
            self.requests = []

        async def create(self, **kwargs):
            self.requests.append(json.loads(json.dumps(kwargs, ensure_ascii=False)))
            return await super().create(**kwargs)

    first_call_resp = SimpleNamespace(
        output=[
            {
                "type": "function_call",
                "name": "search_text",
                "call_id": "call_1",
                "arguments": '{"query":"cache-me"}',
            }
        ],
        output_text="",
        usage=None,
    )
    first_final_resp = SimpleNamespace(
        output=[],
        output_text='{"summary":"done","sources":[]}',
        usage=None,
    )

    second_call_resp = SimpleNamespace(
        output=[
            {
                "type": "function_call",
                "name": "search_text",
                "call_id": "call_2",
                "arguments": '{"query":"cache-me"}',
            }
        ],
        output_text="",
        usage=None,
    )
    second_final_resp = SimpleNamespace(
        output=[],
        output_text='{"summary":"done","sources":[]}',
        usage=None,
    )

    first_client = _FakeClient([])
    first_client.responses = _InspectableResponses([first_call_resp, first_final_resp])
    second_client = _FakeClient([])
    second_client.responses = _InspectableResponses([second_call_resp, second_final_resp])
    clients = [first_client, second_client]
    monkeypatch.setattr("app.llm.agentic.call.get_async_openai_client", lambda: clients.pop(0))
    monkeypatch.setattr(
        "app.llm.agentic.call._tool_definitions",
        lambda _max_file_chars: [
            {
                "type": "function",
                "name": "search_text",
                "description": "x",
                "parameters": {"type": "object", "properties": {}, "required": []},
                "strict": True,
            }
        ],
    )

    async def _fake_dispatch(*_args, **_kwargs):
        nonlocal dispatch_calls
        dispatch_calls += 1
        return tool_payload

    async def _fake_self_check_async(**kwargs):
        return {"ok": True, "issues": [], "missing_context": []}

    monkeypatch.setattr("app.llm.agentic.call._dispatch_tool_async", _fake_dispatch)
    monkeypatch.setattr("app.llm.agentic.call._run_self_check_async", _fake_self_check_async)

    _, first_meta = await _agentic_json_call_async(
        session=object(),
        model="gpt-5-mini",
        self_check_model=None,
        self_check_reasoning_effort=None,
        schema={"name": "result", "schema": {"type": "object"}, "strict": True},
        project_id=1,
        root=Path("."),
        seed={"target_path": "a.py"},
        user_prompt="do work",
        reasoning_effort=None,
        evidence_mode=False,
        max_total_tool_output_chars=120,
        allow_self_check_retry=False,
        allow_evidence_retry=False,
        _tool_cache=shared_tool_cache,
    )
    _, second_meta = await _agentic_json_call_async(
        session=object(),
        model="gpt-5-mini",
        self_check_model=None,
        self_check_reasoning_effort=None,
        schema={"name": "result", "schema": {"type": "object"}, "strict": True},
        project_id=1,
        root=Path("."),
        seed={"target_path": "a.py"},
        user_prompt="do work",
        reasoning_effort=None,
        evidence_mode=False,
        max_total_tool_output_chars=5_000,
        allow_self_check_retry=False,
        allow_evidence_retry=False,
        _tool_cache=shared_tool_cache,
    )

    first_request_inputs = [req["input"] for req in first_client.responses.requests]
    second_request_inputs = [req["input"] for req in second_client.responses.requests]
    first_outputs = [
        item["output"]
        for item in first_request_inputs[1]
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    second_outputs = [
        item["output"]
        for item in second_request_inputs[1]
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    first_output = first_outputs[-1]
    second_output = second_outputs[-1]

    assert dispatch_calls == 1
    assert first_meta.cache_hits == 0
    assert second_meta.cache_hits == 1
    assert "truncated_due_to_budget" in first_output
    assert long_text in second_output
    assert "truncated_due_to_budget" not in second_output
    assert first_meta.tool_trace[0]["truncated_due_to_budget"] is True
    assert second_meta.tool_trace[0]["truncated_due_to_budget"] is False
    assert first_meta.tool_trace[0]["response_chars"] == len(first_output)
    assert second_meta.tool_trace[0]["response_chars"] == len(second_output)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_output"),
    [
        "not-a-dict",
        {"ok": True, "data": {"bad": object()}},
    ],
)
async def test_agentic_non_object_tool_output_converted_to_error_payload(monkeypatch, tool_output):
    class _InspectableResponses(_FakeResponses):
        def __init__(self, payloads):
            super().__init__(payloads)
            self.requests = []

        async def create(self, **kwargs):
            self.requests.append(json.loads(json.dumps(kwargs, ensure_ascii=False)))
            return await super().create(**kwargs)

    first_resp = SimpleNamespace(
        output=[
            {
                "type": "function_call",
                "name": "search_text",
                "call_id": "call_1",
                "arguments": '{"query":"bad-output"}',
            }
        ],
        output_text="",
        usage=None,
    )
    final_resp = SimpleNamespace(
        output=[],
        output_text='{"summary":"done","sources":[]}',
        usage=None,
    )

    fake_client = _FakeClient([])
    fake_client.responses = _InspectableResponses([first_resp, final_resp])
    monkeypatch.setattr("app.llm.agentic.call.get_async_openai_client", lambda: fake_client)
    monkeypatch.setattr(
        "app.llm.agentic.call._tool_definitions",
        lambda _max_file_chars: [
            {
                "type": "function",
                "name": "search_text",
                "description": "x",
                "parameters": {"type": "object", "properties": {}, "required": []},
                "strict": True,
            }
        ],
    )

    async def _fake_dispatch(*_args, **_kwargs):
        return tool_output

    async def _fake_self_check_async(**kwargs):
        return {"ok": True, "issues": [], "missing_context": []}

    monkeypatch.setattr("app.llm.agentic.call._dispatch_tool_async", _fake_dispatch)
    monkeypatch.setattr("app.llm.agentic.call._run_self_check_async", _fake_self_check_async)

    _result, meta = await _agentic_json_call_async(
        session=object(),
        model="gpt-5-mini",
        self_check_model=None,
        self_check_reasoning_effort=None,
        schema={"name": "result", "schema": {"type": "object"}, "strict": True},
        project_id=1,
        root=Path("."),
        seed={"target_path": "a.py"},
        user_prompt="do work",
        reasoning_effort=None,
        evidence_mode=False,
        allow_self_check_retry=False,
        allow_evidence_retry=False,
    )

    request_inputs = [req["input"] for req in fake_client.responses.requests]
    tool_outputs = [
        item["output"]
        for item in request_inputs[1]
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    assert tool_outputs
    payload = json.loads(tool_outputs[-1])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_tool_output"
    assert meta.tool_trace[0]["status"] == "error"
