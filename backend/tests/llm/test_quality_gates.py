import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm.quality_gates import QualityGateError, validate_llm_result


def _settings(min_sources: int = 1) -> SimpleNamespace:
    return SimpleNamespace(llm_evidence_min_sources=min_sources)


def test_fix_quality_gate_success() -> None:
    result = {
        "sources": [{"path": "a.py", "start_line": 1, "end_line": 2}],
        "patch_unified_diff": "\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
        "tests": ["pytest backend/tests/test_a.py"],
    }

    validate_llm_result("fix", result, evidence_mode=False, settings=_settings())


def test_fix_quality_gate_failures_are_structured() -> None:
    result = {
        "sources": [
            {"path": "", "start_line": 0, "end_line": 1},
            {"path": "ok.py", "start_line": 4, "end_line": 2},
        ],
        "patch_unified_diff": "   ",
        "tests": ["", "   "],
    }

    with pytest.raises(QualityGateError) as exc:
        validate_llm_result("fix", result, evidence_mode=False, settings=_settings())

    payload = exc.value.reasons_payload()
    assert any(item["field"] == "sources[0].path" for item in payload)
    assert any(item["field"] == "sources[0].start_line" for item in payload)
    assert any(item["field"] == "sources[1]" for item in payload)
    assert any(item["field"] == "patch_unified_diff" for item in payload)
    assert any(item["field"] == "tests[0]" for item in payload)


def test_analyze_evidence_requires_minimum_sources() -> None:
    result = {
        "sources": [
            {"path": "valid.py", "start_line": 1, "end_line": 1},
            {"path": "", "start_line": 3, "end_line": 4},
        ]
    }

    with pytest.raises(QualityGateError) as exc:
        validate_llm_result("analyze", result, evidence_mode=True, settings=_settings(2))

    reasons = exc.value.reasons_payload()
    assert any(r["code"] == "insufficient_sources" for r in reasons)


def test_evolve_evidence_passes_with_enough_sources() -> None:
    result = {
        "sources": [
            {"path": "a.py", "start_line": 1, "end_line": 1},
            {"path": "b.py", "start_line": 10, "end_line": 12},
        ]
    }

    validate_llm_result("evolve", result, evidence_mode=True, settings=_settings(2))
