"""LLM quality gates.

Использование: вызовите validate_llm_result(...) сразу после ответа LLM,
чтобы отфильтровать частично-валидные payload до записи/возврата в API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class QualityGateReason:
    code: str
    field: str
    message: str
    meta: dict[str, Any] | None = None


class QualityGateError(Exception):
    def __init__(
        self,
        *,
        mode: str,
        evidence_mode: bool,
        min_sources: int,
        reasons: list[QualityGateReason],
    ) -> None:
        super().__init__("LLM quality gate failed")
        self.mode = mode
        self.evidence_mode = evidence_mode
        self.min_sources = min_sources
        self.reasons = reasons

    def reasons_payload(self) -> list[dict[str, Any]]:
        return [asdict(reason) for reason in self.reasons]


def _reason(
    reasons: list[QualityGateReason],
    *,
    code: str,
    field: str,
    message: str,
    meta: dict[str, Any] | None = None,
) -> None:
    reasons.append(QualityGateReason(code=code, field=field, message=message, meta=meta))


def _validate_sources(
    result: dict[str, Any], reasons: list[QualityGateReason]
) -> list[dict[str, Any]]:
    raw_sources = result.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) == 0:
        _reason(
            reasons,
            code="required",
            field="sources",
            message="sources должен быть непустым списком",
        )
        return []

    valid_sources: list[dict[str, Any]] = []
    for index, source in enumerate(raw_sources):
        source_field = f"sources[{index}]"
        if not isinstance(source, dict):
            _reason(
                reasons,
                code="invalid_type",
                field=source_field,
                message="source должен быть объектом",
            )
            continue
        path = source.get("path")
        start_line = source.get("start_line")
        end_line = source.get("end_line")

        source_valid = True
        if not isinstance(path, str) or not path.strip():
            _reason(
                reasons,
                code="invalid_path",
                field=f"{source_field}.path",
                message="path должен быть непустой строкой",
            )
            source_valid = False
        if not isinstance(start_line, int) or start_line < 1:
            _reason(
                reasons,
                code="invalid_line_range",
                field=f"{source_field}.start_line",
                message="start_line должен быть целым числом >= 1",
            )
            source_valid = False
        if not isinstance(end_line, int):
            _reason(
                reasons,
                code="invalid_line_range",
                field=f"{source_field}.end_line",
                message="end_line должен быть целым числом",
            )
            source_valid = False
        if isinstance(start_line, int) and isinstance(end_line, int) and end_line < start_line:
            _reason(
                reasons,
                code="invalid_line_range",
                field=source_field,
                message="end_line должен быть >= start_line",
                meta={"start_line": start_line, "end_line": end_line},
            )
            source_valid = False
        if source_valid:
            valid_sources.append(source)

    return valid_sources


def validate_llm_result(
    mode: str, result: dict[str, Any], evidence_mode: bool, settings: Any
) -> None:
    reasons: list[QualityGateReason] = []

    if not isinstance(result, dict):
        _reason(
            reasons,
            code="invalid_type",
            field="result",
            message="result должен быть JSON-объектом",
        )
    else:
        if mode == "fix":
            valid_sources = _validate_sources(result, reasons)

            patch_unified_diff = result.get("patch_unified_diff")
            if not isinstance(patch_unified_diff, str) or not patch_unified_diff.strip():
                _reason(
                    reasons,
                    code="required",
                    field="patch_unified_diff",
                    message="patch_unified_diff должен быть непустой строкой",
                )

            tests = result.get("tests")
            if not isinstance(tests, list) or len(tests) == 0:
                _reason(
                    reasons,
                    code="required",
                    field="tests",
                    message="tests должен быть непустым списком строк",
                )
            else:
                for index, test in enumerate(tests):
                    if not isinstance(test, str) or not test.strip():
                        _reason(
                            reasons,
                            code="invalid_test_item",
                            field=f"tests[{index}]",
                            message="каждый элемент tests должен быть непустой строкой",
                        )

            if not valid_sources:
                # already reported; kept for explicitness in fix mode
                pass

        if mode in {"analyze", "evolve"} and evidence_mode:
            valid_sources = _validate_sources(result, reasons)
            min_sources = int(getattr(settings, "llm_evidence_min_sources", 1))
            if len(valid_sources) < min_sources:
                _reason(
                    reasons,
                    code="insufficient_sources",
                    field="sources",
                    message="Недостаточно валидных источников для evidence_mode",
                    meta={"valid_sources": len(valid_sources), "min_sources": min_sources},
                )

    if reasons:
        raise QualityGateError(
            mode=mode,
            evidence_mode=bool(evidence_mode),
            min_sources=int(getattr(settings, "llm_evidence_min_sources", 1)),
            reasons=reasons,
        )
