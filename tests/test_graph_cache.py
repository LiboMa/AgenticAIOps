"""Tests for src/aci/topology/cache.py — GraphCache singleton.

Covers:
  - get_current / is_available (initially None)
  - refresh with builder
  - refresh stores deltas
  - inject_alarm (status update + stale marking)
  - inject_alarm on missing node
  - invalidate
  - status() dict
  - start/stop refresh loop
  - error handling in builder
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.aci.topology.cache import GraphCache
from src.aci.topology.engine import InfraGraph
from src.aci.topology.types import EdgeAttrs, EdgeType, NodeAttrs, NodeStatus, NodeType


# ── Fixtures ─────────────────────────────────────────────────────────


def _build_test_graph() -> InfraGraph:
    g = InfraGraph()
    g._add_node("vpc-1", NodeAttrs(node_type=NodeType.VPC, label="vpc", status=NodeStatus.HEALTHY))
    g._add_node("i-123", NodeAttrs(node_type=NodeType.EC2_INSTANCE, label="web", status=NodeStatus.HEALTHY))
    g._add_edge("vpc-1", "i-123", EdgeAttrs(edge_type=EdgeType.CONTAINS, label=""))
    return g


# ── Basic state tests ────────────────────────────────────────────────


class TestGraphCacheBasic:
    def test_initial_state(self):
        cache = GraphCache()
        assert cache.get_current() is None
        assert cache.is_available() is False
        assert cache.last_refresh is None
        assert cache.is_stale is False

    def test_status_empty(self):
        cache = GraphCache()
        s = cache.status()
        assert s["available"] is False
        assert s["stale"] is False
        assert s["last_refresh"] is None
        assert s["node_count"] == 0

    def test_invalidate(self):
        cache = GraphCache()
        cache.invalidate()
        assert cache.is_stale is True


# ── Refresh tests ────────────────────────────────────────────────────


class TestGraphCacheRefresh:
    @pytest.mark.asyncio
    async def test_refresh_without_builder(self):
        cache = GraphCache()
        await cache.refresh()
        assert cache.get_current() is None

    @pytest.mark.asyncio
    async def test_refresh_with_builder(self):
        cache = GraphCache()
        builder = AsyncMock(return_value=_build_test_graph())
        cache.set_builder(builder)

        await cache.refresh()
        assert cache.is_available()
        assert cache.get_current().node_count == 2
        assert cache.last_refresh is not None
        builder.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_keeps_previous(self):
        cache = GraphCache()
        g1 = _build_test_graph()
        g2 = _build_test_graph()
        g2._add_node("extra", NodeAttrs(node_type=NodeType.SUBNET, label="extra"))

        call_count = 0

        async def _builder():
            nonlocal call_count
            call_count += 1
            return g1 if call_count == 1 else g2

        cache.set_builder(_builder)
        await cache.refresh()
        assert cache.get_previous() is None  # first refresh

        await cache.refresh()
        prev = cache.get_previous()
        assert prev is not None
        assert prev.node_count == 2  # g1
        assert cache.get_current().node_count == 3  # g2

    @pytest.mark.asyncio
    async def test_refresh_clears_stale(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        cache.invalidate()
        assert cache.is_stale is True
        await cache.refresh()
        assert cache.is_stale is False

    @pytest.mark.asyncio
    async def test_refresh_builder_failure_keeps_old(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        await cache.refresh()
        assert cache.is_available()

        # Now make builder fail
        cache.set_builder(AsyncMock(side_effect=RuntimeError("boom")))
        await cache.refresh()
        # Should still have the old graph
        assert cache.is_available()
        assert cache.get_current().node_count == 2

    @pytest.mark.asyncio
    @patch("src.aci.topology.cache.get_delta_store")
    async def test_refresh_stores_deltas(self, mock_get_store):
        mock_store = MagicMock()
        mock_store.store.return_value = 3
        mock_get_store.return_value = mock_store

        cache = GraphCache()
        g1 = _build_test_graph()
        g2 = _build_test_graph()
        g2._add_node("new-node", NodeAttrs(node_type=NodeType.SUBNET, label="new"))

        calls = [g1, g2]
        cache.set_builder(AsyncMock(side_effect=calls))

        await cache.refresh()  # first build — no deltas (no previous)
        mock_store.store.assert_not_called()

        await cache.refresh()  # second build — should capture deltas
        mock_store.store.assert_called_once()
        stored_changes = mock_store.store.call_args[0][0]
        assert len(stored_changes) > 0


# ── Alarm injection tests ────────────────────────────────────────────


class TestInjectAlarm:
    @pytest.mark.asyncio
    async def test_inject_alarm_updates_status(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        await cache.refresh()

        result = await cache.inject_alarm("i-123", "ALARM")
        assert result is True
        node = cache.get_current().get_node("i-123")
        assert node["status"] == NodeStatus.ERROR

    @pytest.mark.asyncio
    async def test_inject_alarm_ok(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        await cache.refresh()

        await cache.inject_alarm("i-123", "ALARM")
        await cache.inject_alarm("i-123", "OK")
        node = cache.get_current().get_node("i-123")
        assert node["status"] == NodeStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_inject_alarm_insufficient_data(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        await cache.refresh()

        await cache.inject_alarm("i-123", "INSUFFICIENT_DATA")
        node = cache.get_current().get_node("i-123")
        assert node["status"] == NodeStatus.WARNING

    @pytest.mark.asyncio
    async def test_inject_alarm_marks_stale(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        await cache.refresh()
        assert cache.is_stale is False

        await cache.inject_alarm("i-123", "ALARM")
        assert cache.is_stale is True

    @pytest.mark.asyncio
    async def test_inject_alarm_missing_node(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        await cache.refresh()

        result = await cache.inject_alarm("nonexistent", "ALARM")
        assert result is False

    @pytest.mark.asyncio
    async def test_inject_alarm_no_graph(self):
        cache = GraphCache()
        result = await cache.inject_alarm("i-123", "ALARM")
        assert result is False

    @pytest.mark.asyncio
    async def test_inject_alarm_case_insensitive(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        await cache.refresh()

        await cache.inject_alarm("i-123", "alarm")
        node = cache.get_current().get_node("i-123")
        assert node["status"] == NodeStatus.ERROR


# ── Refresh loop tests ───────────────────────────────────────────────


class TestRefreshLoop:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        cache = GraphCache(refresh_interval_s=60)
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        cache.start_refresh_loop()

        # Give it a moment to start
        await asyncio.sleep(0.1)
        assert cache._refresh_task is not None
        assert not cache._refresh_task.done()

        cache.stop_refresh_loop()
        await asyncio.sleep(0.1)
        assert cache._refresh_task is None

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        cache = GraphCache(refresh_interval_s=60)
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        cache.start_refresh_loop()
        task1 = cache._refresh_task
        cache.start_refresh_loop()
        assert cache._refresh_task is task1
        cache.stop_refresh_loop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        cache = GraphCache()
        cache.stop_refresh_loop()  # should not raise


# ── Status output ────────────────────────────────────────────────────


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_after_refresh(self):
        cache = GraphCache()
        cache.set_builder(AsyncMock(return_value=_build_test_graph()))
        await cache.refresh()

        s = cache.status()
        assert s["available"] is True
        assert s["stale"] is False
        assert s["node_count"] == 2
        assert s["edge_count"] == 1
        assert s["last_refresh"] is not None
