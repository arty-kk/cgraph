import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic  # noqa: E402


class TestAgenticSearchSemantic(unittest.IsolatedAsyncioTestCase):
    async def test_search_semantic_returns_error_for_invalid_response(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            args = {"query": "find auth flow"}
            session = object()
            search_mock = AsyncMock(return_value=None)

            with patch("app.llm.agentic.tools.search_semantic_async", search_mock):
                result = await agentic._tool_search_semantic_async(
                    session,
                    1,
                    root,
                    args,
                    max_file_chars=1000,
                )

        search_mock.assert_awaited_once_with(
            session,
            1,
            root,
            "find auth flow",
            max_results=None,
            prefix=None,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "semantic_failed")

    async def test_async_dispatch_semantic_uses_async_handler(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            meta = agentic.AgenticMeta()
            meta.tool_trace.append({"name": "plan_retrieval", "status": "ok"})

            async def _fake(*_a, **_kw):
                return agentic._tool_ok({"results": [], "meta": {"fallback_used": False}})

            with patch.object(agentic, "_tool_search_semantic_async", side_effect=_fake):
                result = await agentic._dispatch_tool_async(
                    object(),
                    1,
                    root,
                    meta,
                    "search_semantic",
                    {"query": "auth", "max_results": 5, "prefix": None},
                    max_file_chars=1000,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(set(result.keys()), {"ok", "data", "error"})

    async def test_search_semantic_fallback_uses_passed_async_session(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            args = {"query": "find auth flow"}
            session = object()
            semantic_mock = AsyncMock(return_value={"results": [], "meta": {"reason": "no_hits"}})
            text_async_mock = AsyncMock(return_value=agentic._tool_ok({"matches": [], "meta": {}}))
            with (
                patch("app.llm.agentic.tools.search_semantic_async", semantic_mock),
                patch("app.llm.agentic.tools._tool_search_text_async", text_async_mock),
            ):
                result = await agentic._tool_search_semantic_async(
                    session,
                    1,
                    root,
                    args,
                    max_file_chars=1000,
                )

        text_async_mock.assert_awaited_once()
        call_args = text_async_mock.await_args.args
        self.assertIs(call_args[0], session)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
