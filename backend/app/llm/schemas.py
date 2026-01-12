#backend/app/llm/schemas.py
from __future__ import annotations

ANALYZE_SCHEMA = {
  "name": "cgraph_analyze",
  "schema": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "summary": {"type": "string"},
      "risks": {"type": "array", "items": {"type": "string"}},
      "evolution_points": {"type": "array", "items": {"type": "string"}},
      "notable_symbols": {"type": "array", "items": {"type": "string"}},
      "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "risks", "evolution_points", "notable_symbols", "suggestions"]
  },
  "strict": True
}

TRIAGE_SCHEMA = {
  "name": "cgraph_triage",
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
  "name": "cgraph_fix",
  "schema": {
    "type": "object",
    "additionalProperties": False,
    "properties": {
      "diagnosis": {"type": "string"},
      "plan": {"type": "array", "items": {"type": "string"}},
      "patch_unified_diff": {"type": "string"},
      "tests": {"type": "array", "items": {"type": "string"}},
      "notes": {"type": "string"}
    },
    "required": ["diagnosis", "plan", "patch_unified_diff", "tests", "notes"]
  },
  "strict": True
}

DOCS_SCHEMA = {
  "name": "cgraph_docs",
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