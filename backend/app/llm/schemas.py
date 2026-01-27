#backend/app/llm/schemas.py
from __future__ import annotations

ANALYZE_SCHEMA = {
  "name": "stubgraph_analyze",
  "schema": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "summary": {"type": "string"},
      "risks": {"type": "array", "items": {"type": "string"}},
      "evolution_points": {"type": "array", "items": {"type": "string"}},
      "notable_symbols": {"type": "array", "items": {"type": "string"}},
      "suggestions": {"type": "array", "items": {"type": "string"}},
      "sources": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
            "note": {"type": "string"},
            "used_in": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["path", "start_line", "end_line", "used_in"]
        }
      },
    },
    "required": ["summary", "risks", "evolution_points", "notable_symbols", "suggestions"]
  },
  "strict": True
}

PLAN_TZ_SCHEMA = {
  "name": "stubgraph_plan_tz",
  "schema": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "summary": {"type": "string"},
      "requirements": {"type": "array", "items": {"type": "string"}},
      "constraints": {"type": "array", "items": {"type": "string"}},
      "sdlc_plan": {"type": "array", "items": {"type": "string"}},
      "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
      "risks": {"type": "array", "items": {"type": "string"}},
      "open_questions": {"type": "array", "items": {"type": "string"}},
      "deliverables": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
      "summary",
      "requirements",
      "constraints",
      "sdlc_plan",
      "acceptance_criteria",
      "risks",
      "open_questions",
      "deliverables",
    ],
  },
  "strict": True,
}

SELF_CHECK_SCHEMA = {
  "name": "stubgraph_self_check",
  "schema": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "ok": {"type": "boolean"},
      "issues": {"type": "array", "items": {"type": "string"}},
      "missing_context": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ok", "issues", "missing_context"]
  },
  "strict": True
}

TRIAGE_SCHEMA = {
  "name": "stubgraph_triage",
  "schema": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "task_kind": {"type": "string", "enum": ["analyze", "evolve", "fix", "impact"]},
      "depth": {"type": "integer", "minimum": 0, "maximum": 6},
      "dep_mode": {"type": "string", "enum": ["contracts", "full"]},
      "needs_patch": {"type": "boolean"},
      "notes": {"type": "string"}
    },
    "required": ["task_kind", "depth", "dep_mode", "needs_patch", "notes"]
  },
  "strict": True
}

FIX_SCHEMA = {
  "name": "stubgraph_fix",
  "schema": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "diagnosis": {"type": "string"},
      "plan": {"type": "array", "items": {"type": "string"}},
      "patch_unified_diff": {"type": "string"},
      "tests": {"type": "array", "items": {"type": "string"}, "minItems": 1},
      "notes": {"type": "string"},
      "sources": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
            "note": {"type": "string"},
            "used_in": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["path", "start_line", "end_line", "used_in"]
        }
      }
    },
    "required": ["diagnosis", "plan", "patch_unified_diff", "tests", "notes"]
  },
  "strict": True
}

DOCS_SCHEMA = {
  "name": "stubgraph_docs",
  "schema": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "markdown": {"type": "string"}
    },
    "required": ["markdown"]
  },
  "strict": True
}
