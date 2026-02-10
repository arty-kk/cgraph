import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm.agentic.call import _agentic_json_call


class _FakeResponses:
    def __init__(self, payloads):
        self._payloads = list(payloads)

    def create(self, **kwargs):
        assert kwargs.get("model") == "gpt-5-mini"
        return self._payloads.pop(0)


class _FakeClient:
    def __init__(self, payloads):
        self.responses = _FakeResponses(payloads)


def test_agentic_retry_aggregates_usage_tokens(monkeypatch):
    first_resp = SimpleNamespace(
        output=[],
        output_text='{"summary": "first", "sources": []}',
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens="2", total_tokens=12),
    )
    second_resp = SimpleNamespace(
        output=[],
        output_text=(
            '{"summary": "second", "sources": '
            '[{"path": "a.py", "line_start": 1, "line_end": 1}]}'
        ),
        usage={"prompt_tokens": "7", "completion_tokens": 3, "total_tokens": "10"},
    )

    fake_client = _FakeClient([first_resp, second_resp])
    monkeypatch.setattr("app.llm.agentic.call.get_openai_client", lambda: fake_client)
    monkeypatch.setattr("app.llm.agentic.call._tool_definitions", lambda _max_file_chars: [])

    def _fake_self_check(**kwargs):
        return {"ok": True, "issues": [], "missing_context": []}

    monkeypatch.setattr("app.llm.agentic.call._run_self_check", _fake_self_check)

    result, meta = _agentic_json_call(
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
    assert meta.prompt_tokens == 17
    assert meta.completion_tokens == 5
    assert meta.total_tokens == 22
