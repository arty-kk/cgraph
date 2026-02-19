import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

BACKEND_ROOT = Path(__file__).resolve().parents[2]

MODULE_EXPECTATIONS = {
    "app/llm/client.py": {
        "forbidden_defs": {"get_openai_client"},
        "forbidden_import_names": {"OpenAI"},
        "forbidden_assignments": {"_client"},
    },
    "app/llm/orchestrator.py": {
        "forbidden_defs": {
            "_json_call",
            "_json_call_with_usage",
            "triage",
            "triage_with_usage",
            "analyze",
            "analyze_with_usage",
            "evolve",
            "evolve_with_usage",
            "fix",
            "fix_with_usage",
            "generate_docs",
            "generate_docs_with_usage",
        },
        "forbidden_import_names": {"get_openai_client"},
        "forbidden_assignments": set(),
    },
    "app/llm/routing_thresholds.py": {
        "forbidden_defs": {"resolve_routing_thresholds"},
        "forbidden_import_names": {"cache_get_json"},
        "forbidden_assignments": set(),
    },
    "app/llm/routing_weights.py": {
        "forbidden_defs": {"resolve_routing_weights"},
        "forbidden_import_names": {"cache_get_json"},
        "forbidden_assignments": set(),
    },
    "app/llm/routing_selector.py": {
        "forbidden_defs": {"select_runtime_route"},
        "forbidden_import_names": {"resolve_routing_thresholds", "resolve_routing_weights"},
        "forbidden_assignments": set(),
    },
}


def _collect_imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _collect_assigned_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def test_runtime_llm_modules_are_async_only_contract() -> None:
    violations: list[str] = []
    for rel_path, rules in MODULE_EXPECTATIONS.items():
        path = BACKEND_ROOT / rel_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        def_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        import_names = _collect_imported_names(tree)
        assigned_names = _collect_assigned_names(tree)

        for forbidden in sorted(rules["forbidden_defs"]):
            if forbidden in def_names:
                violations.append(f"{rel_path}:def:{forbidden}")
        for forbidden in sorted(rules["forbidden_import_names"]):
            if forbidden in import_names:
                violations.append(f"{rel_path}:import:{forbidden}")
        for forbidden in sorted(rules["forbidden_assignments"]):
            if forbidden in assigned_names:
                violations.append(f"{rel_path}:assign:{forbidden}")

    assert not violations, "Sync LLM runtime symbols must be removed: " + ", ".join(violations)
