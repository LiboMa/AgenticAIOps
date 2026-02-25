"""
Tests for routers/chat_intents/__init__.py — Intent dispatcher

Coverage target: 100% for dispatcher logic.
Tests the registry-dict pattern, priority ordering, error handling, and fallback.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestIntentHandlerRegistry:
    """Test the INTENT_HANDLERS registry is properly configured."""

    def test_registry_has_all_expected_handlers(self):
        from routers.chat_intents import INTENT_HANDLERS

        expected = {
            "health", "metrics", "rca", "sop",
            "knowledge", "operations", "resources", "ui_actions",
        }
        assert set(INTENT_HANDLERS.keys()) == expected

    def test_registry_has_8_handlers(self):
        from routers.chat_intents import INTENT_HANDLERS

        assert len(INTENT_HANDLERS) == 8

    def test_all_handlers_are_callable(self):
        from routers.chat_intents import INTENT_HANDLERS

        for name, handler in INTENT_HANDLERS.items():
            assert callable(handler), f"{name} handler is not callable"

    def test_priority_order_rca_before_operations(self):
        """RCA should be checked before operations to avoid mismatches."""
        from routers.chat_intents import INTENT_HANDLERS

        keys = list(INTENT_HANDLERS.keys())
        assert keys.index("rca") < keys.index("operations")

    def test_priority_order_sop_before_resources(self):
        """SOP should be checked before resources so 'sop list' isn't mismatched."""
        from routers.chat_intents import INTENT_HANDLERS

        keys = list(INTENT_HANDLERS.keys())
        assert keys.index("sop") < keys.index("resources")


class TestDispatch:
    """Test the dispatch() async function."""

    @pytest.mark.asyncio
    async def test_dispatch_returns_first_match(self):
        """When a handler returns a non-None result, dispatch returns it."""
        from routers.chat_intents import dispatch

        with patch("routers.chat_intents.INTENT_HANDLERS", {
            "mock_a": AsyncMock(return_value=None),
            "mock_b": AsyncMock(return_value="matched by B"),
            "mock_c": AsyncMock(return_value="matched by C"),
        }):
            result = await dispatch("test message", "test message")
            assert result == "matched by B"

    @pytest.mark.asyncio
    async def test_dispatch_returns_none_when_no_match(self):
        """When all handlers return None, dispatch returns None."""
        from routers.chat_intents import dispatch

        with patch("routers.chat_intents.INTENT_HANDLERS", {
            "mock_a": AsyncMock(return_value=None),
            "mock_b": AsyncMock(return_value=None),
        }):
            result = await dispatch("unknown query", "unknown query")
            assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_skips_none_results(self):
        """Handlers returning None are skipped, next handler is tried."""
        from routers.chat_intents import dispatch

        handler_a = AsyncMock(return_value=None)
        handler_b = AsyncMock(return_value="B result")

        with patch("routers.chat_intents.INTENT_HANDLERS", {
            "mock_a": handler_a,
            "mock_b": handler_b,
        }):
            result = await dispatch("msg", "msg")
            assert result == "B result"
            handler_a.assert_called_once_with("msg", "msg")
            handler_b.assert_called_once_with("msg", "msg")

    @pytest.mark.asyncio
    async def test_dispatch_stops_after_first_match(self):
        """Once a handler matches, subsequent handlers are NOT called."""
        from routers.chat_intents import dispatch

        handler_a = AsyncMock(return_value="A matched")
        handler_b = AsyncMock(return_value="B matched")

        with patch("routers.chat_intents.INTENT_HANDLERS", {
            "mock_a": handler_a,
            "mock_b": handler_b,
        }):
            result = await dispatch("msg", "msg")
            assert result == "A matched"
            handler_a.assert_called_once()
            handler_b.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_handles_handler_exception(self):
        """When a handler raises, dispatch logs and returns error message."""
        from routers.chat_intents import dispatch

        handler_a = AsyncMock(side_effect=ValueError("boom"))

        with patch("routers.chat_intents.INTENT_HANDLERS", {
            "mock_a": handler_a,
        }):
            result = await dispatch("msg", "msg")
            assert "Internal error" in result
            assert "mock_a" in result
            assert "boom" in result

    @pytest.mark.asyncio
    async def test_dispatch_exception_does_not_try_next_handler(self):
        """On exception, dispatch returns error immediately (does not continue)."""
        from routers.chat_intents import dispatch

        handler_a = AsyncMock(side_effect=RuntimeError("fail"))
        handler_b = AsyncMock(return_value="B result")

        with patch("routers.chat_intents.INTENT_HANDLERS", {
            "mock_a": handler_a,
            "mock_b": handler_b,
        }):
            result = await dispatch("msg", "msg")
            assert "Internal error" in result
            handler_b.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_passes_both_args_to_handler(self):
        """Handlers receive (message, message_lower) correctly."""
        from routers.chat_intents import dispatch

        handler = AsyncMock(return_value="ok")

        with patch("routers.chat_intents.INTENT_HANDLERS", {
            "mock": handler,
        }):
            await dispatch("Check EC2 Status", "check ec2 status")
            handler.assert_called_once_with("Check EC2 Status", "check ec2 status")

    @pytest.mark.asyncio
    async def test_dispatch_empty_registry(self):
        """With no handlers registered, dispatch returns None."""
        from routers.chat_intents import dispatch

        with patch("routers.chat_intents.INTENT_HANDLERS", {}):
            result = await dispatch("msg", "msg")
            assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_handler_returns_empty_string(self):
        """Empty string is falsy but not None — should still be returned."""
        from routers.chat_intents import dispatch

        # Empty string is a valid response (truthy check vs None check)
        handler = AsyncMock(return_value="")

        with patch("routers.chat_intents.INTENT_HANDLERS", {
            "mock": handler,
        }):
            result = await dispatch("msg", "msg")
            # Empty string is not None, so behavior depends on implementation
            # Current impl: `if result is not None` → returns ""
            assert result == ""
