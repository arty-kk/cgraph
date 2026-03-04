import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TASK_HANDLERS_PATH = BACKEND_ROOT / "app" / "task_handlers.py"


def _find_function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in tree.body:  # type: ignore[attr-defined]
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function not found: {name}")


def test_consume_queued_task_payload_does_not_call_sync_decode_directly() -> None:
    tree = ast.parse(
        TASK_HANDLERS_PATH.read_text(encoding="utf-8"),
        filename=str(TASK_HANDLERS_PATH),
    )
    consume_fn = _find_function(tree, "consume_queued_task_payload_async")

    direct_calls = [
        node
        for node in ast.walk(consume_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_decode_task_payload"
    ]

    assert not direct_calls, (
        "consume_queued_task_payload_async must not call _decode_task_payload directly"
    )


def test_decode_task_payload_async_uses_cpu_runtime_wrapper() -> None:
    tree = ast.parse(
        TASK_HANDLERS_PATH.read_text(encoding="utf-8"),
        filename=str(TASK_HANDLERS_PATH),
    )
    decode_async_fn = _find_function(tree, "_decode_task_payload_async")

    runtime_calls = [
        node
        for node in ast.walk(decode_async_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_cpu_io_async"
    ]

    assert runtime_calls, "_decode_task_payload_async must call run_cpu_io_async"
    assert any(
        call.args
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "_decode_task_payload"
        and any(
            keyword.arg == "operation"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "task_handlers.decode_task_payload"
            for keyword in call.keywords
        )
        for call in runtime_calls
    ), (
        "run_cpu_io_async must receive _decode_task_payload and "
        "operation='task_handlers.decode_task_payload'"
    )
