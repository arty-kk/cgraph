import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic  # noqa: E402
from app.llm.agentic import tools as agentic_tools  # noqa: E402


class TestAgenticFileToolsAsync(unittest.IsolatedAsyncioTestCase):
    async def test_get_file_async_uses_fs_runtime_for_file_read(self) -> None:
        meta = agentic.AgenticMeta(fs_ops_semaphore=asyncio.Semaphore(2))
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "sample.txt"
            file_path.write_text("x" * 100, encoding="utf-8")
            args = {"path": "sample.txt", "max_chars": 50}
            calls: list[tuple[object, tuple, dict]] = []

            async def _fake_fs_runtime(fn, *a, **kw):
                calls.append((fn, a, dict(kw)))
                kw.pop("operation", None)
                return fn(*a, **kw)

            with patch("app.llm.agentic.tools.run_fs_io_async", side_effect=_fake_fs_runtime):
                result = await agentic._tool_get_file_async(1, root, meta, args, max_file_chars=80)

        self.assertTrue(result["ok"])
        self.assertIn("data", result)
        self.assertIsNone(result["error"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2].get("operation"), "agentic.fs_tool")

    async def test_get_file_lines_async_schema_and_fs_runtime(self) -> None:
        meta = agentic.AgenticMeta(fs_ops_semaphore=asyncio.Semaphore(2))
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "lines.txt"
            file_path.write_text("a\n" * 5, encoding="utf-8")
            args = {"path": "lines.txt", "start_line": 2, "end_line": 3, "max_chars": 30}
            calls: list[tuple[object, tuple, dict]] = []

            async def _fake_fs_runtime(fn, *a, **kw):
                calls.append((fn, a, dict(kw)))
                kw.pop("operation", None)
                return fn(*a, **kw)

            with patch("app.llm.agentic.tools.run_fs_io_async", side_effect=_fake_fs_runtime):
                result = await agentic._tool_get_file_lines_async(
                    1,
                    root,
                    meta,
                    args,
                    max_file_chars=100,
                )

        self.assertEqual(set(result.keys()), {"ok", "data", "error"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["start_line"], 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2].get("operation"), "agentic.fs_tool")

    async def test_get_file_async_preserves_not_found_error_shape(self) -> None:
        meta = agentic.AgenticMeta(fs_ops_semaphore=asyncio.Semaphore(2))
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = await agentic._tool_get_file_async(
                1,
                root,
                meta,
                {"path": "missing.txt", "max_chars": 50},
                max_file_chars=80,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "not_found")
        self.assertEqual(result["error"]["details"], {"path": "missing.txt"})

    async def test_get_file_lines_async_preserves_not_a_file_error_shape(self) -> None:
        meta = agentic.AgenticMeta(fs_ops_semaphore=asyncio.Semaphore(2))
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "folder").mkdir()
            result = await agentic._tool_get_file_lines_async(
                1,
                root,
                meta,
                {"path": "folder", "start_line": 1, "end_line": 2, "max_chars": 50},
                max_file_chars=80,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "not_a_file")
        self.assertEqual(result["error"]["details"], {"path": "folder"})

    async def test_get_file_async_preserves_read_failed_error_shape(self) -> None:
        meta = agentic.AgenticMeta(fs_ops_semaphore=asyncio.Semaphore(2))
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "boom.txt").write_text("hello", encoding="utf-8")

            with patch(
                "app.llm.agentic.tools._resolve_and_read_file_under_root",
                side_effect=agentic_tools._file_read_failed("boom.txt", "denied: boom.txt"),
            ):
                result = await agentic._tool_get_file_async(
                    1,
                    root,
                    meta,
                    {"path": "boom.txt", "max_chars": 50},
                    max_file_chars=80,
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "read_failed")
        self.assertEqual(
            result["error"]["details"],
            {"path": "boom.txt", "reason": "denied: boom.txt"},
        )

    async def test_suggest_frontend_client_async_uses_fs_runtime_for_file_exists_check(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            args = {"path": "/api/users", "method": "GET"}
            calls: list[tuple[object, tuple, dict]] = []

            route = SimpleNamespace(
                method="GET",
                path="/api/users",
                source_path="backend/app/api/users.py",
                handler_name="list_users",
                lineno=10,
                decorator="router.get",
            )

            class _FakeExecuteResult:
                def scalars(self):
                    return self

                def all(self):
                    return [route]

            class _FakeSession:
                async def execute(self, _q):
                    return _FakeExecuteResult()

            async def _fake_prefix_map(_project_id: int):
                return {}

            async def _fake_fs_runtime(fn, *a, **kw):
                calls.append((fn, a, dict(kw)))
                kw.pop("operation", None)
                return fn(*a, **kw)

            with (
                patch("app.llm.agentic.tools._compute_prefix_map", side_effect=_fake_prefix_map),
                patch("app.llm.agentic.tools.run_fs_io_async", side_effect=_fake_fs_runtime),
            ):
                result = await agentic._tool_suggest_frontend_client_async(
                    _FakeSession(),
                    1,
                    root,
                    args,
                )

        self.assertTrue(result["ok"])
        self.assertIn("data", result)
        self.assertIsNone(result["error"])
        self.assertIsInstance(result["data"]["frontend"]["file_exists"], bool)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0][2].get("operation"),
            "agentic.suggest_frontend_client.path_exists",
        )


if __name__ == "__main__":
    unittest.main()
