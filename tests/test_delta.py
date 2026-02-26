"""Tests for src/aci/topology/delta.py — Topology Delta Storage.

Covers:
  - capture_delta: node/edge additions, removals, updates
  - DeltaStore: SQLite CRUD, recent queries, time-range queries, purge
  - format_recent_changes: human-readable output
  - Sanitize attrs helper
  - Edge cases: empty graphs, first build, no changes
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from src.aci.topology.delta import (
    DeltaStore,
    TopologyChange,
    _sanitize_attrs,
    capture_delta,
    format_recent_changes,
)
from src.aci.topology.engine import InfraGraph
from src.aci.topology.types import EdgeAttrs, EdgeType, NodeAttrs, NodeStatus, NodeType


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a temporary SQLite DB."""
    return str(tmp_path / "test_deltas.db")


@pytest.fixture
def store(tmp_db):
    return DeltaStore(db_path=tmp_db)


def _graph_abc() -> InfraGraph:
    """Graph with nodes A, B, C and edges A→B, B→C."""
    g = InfraGraph()
    g._add_node("A", NodeAttrs(node_type=NodeType.VPC, label="A", status=NodeStatus.HEALTHY))
    g._add_node("B", NodeAttrs(node_type=NodeType.SUBNET, label="B", status=NodeStatus.HEALTHY))
    g._add_node("C", NodeAttrs(node_type=NodeType.NAT_GATEWAY, label="C", status=NodeStatus.HEALTHY))
    g._add_edge("A", "B", EdgeAttrs(edge_type=EdgeType.CONTAINS, label="contains"))
    g._add_edge("B", "C", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label="route"))
    return g


def _graph_abd() -> InfraGraph:
    """Graph with nodes A, B, D and edges A→B, B→D. (C removed, D added)."""
    g = InfraGraph()
    g._add_node("A", NodeAttrs(node_type=NodeType.VPC, label="A", status=NodeStatus.HEALTHY))
    g._add_node("B", NodeAttrs(node_type=NodeType.SUBNET, label="B-updated", status=NodeStatus.WARNING))
    g._add_node("D", NodeAttrs(node_type=NodeType.INTERNET_GATEWAY, label="D", status=NodeStatus.HEALTHY))
    g._add_edge("A", "B", EdgeAttrs(edge_type=EdgeType.CONTAINS, label="contains"))
    g._add_edge("B", "D", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label="new-route"))
    return g


# ── capture_delta tests ──────────────────────────────────────────────


class TestCaptureDelta:
    def test_first_build_all_added(self):
        g = _graph_abc()
        changes = capture_delta(None, g)
        types = [c.change_type for c in changes]
        assert types.count("node_added") == 3
        assert types.count("edge_added") == 2

    def test_no_changes(self):
        g = _graph_abc()
        changes = capture_delta(g, g)
        assert changes == []

    def test_node_added(self):
        old = _graph_abc()
        new = _graph_abd()
        changes = capture_delta(old, new)
        added = [c for c in changes if c.change_type == "node_added"]
        assert any(c.entity_id == "D" for c in added)

    def test_node_removed(self):
        old = _graph_abc()
        new = _graph_abd()
        changes = capture_delta(old, new)
        removed = [c for c in changes if c.change_type == "node_removed"]
        assert any(c.entity_id == "C" for c in removed)

    def test_node_updated(self):
        old = _graph_abc()
        new = _graph_abd()
        changes = capture_delta(old, new)
        updated = [c for c in changes if c.change_type == "node_updated"]
        assert any(c.entity_id == "B" for c in updated)
        b_change = next(c for c in updated if c.entity_id == "B")
        assert b_change.old_value["label"] == "B"
        assert b_change.new_value["label"] == "B-updated"

    def test_edge_added(self):
        old = _graph_abc()
        new = _graph_abd()
        changes = capture_delta(old, new)
        added_edges = [c for c in changes if c.change_type == "edge_added"]
        assert any("D" in c.entity_id for c in added_edges)

    def test_edge_removed(self):
        old = _graph_abc()
        new = _graph_abd()
        changes = capture_delta(old, new)
        removed_edges = [c for c in changes if c.change_type == "edge_removed"]
        assert any("C" in c.entity_id for c in removed_edges)

    def test_source_field(self):
        g = _graph_abc()
        changes = capture_delta(None, g, source="cloudtrail", source_detail="evt-123")
        for c in changes:
            assert c.source == "cloudtrail"
            assert c.source_detail == "evt-123"

    def test_timestamps_set(self):
        g = _graph_abc()
        changes = capture_delta(None, g)
        for c in changes:
            assert c.timestamp  # non-empty ISO string


# ── DeltaStore tests ─────────────────────────────────────────────────


class TestDeltaStore:
    def test_store_and_retrieve(self, store):
        changes = capture_delta(None, _graph_abc())
        count = store.store(changes)
        assert count == 5  # 3 nodes + 2 edges

        recent = store.get_recent(window=timedelta(hours=1))
        assert len(recent) == 5

    def test_store_empty_list(self, store):
        assert store.store([]) == 0

    def test_get_recent_filter_by_entity(self, store):
        changes = capture_delta(None, _graph_abc())
        store.store(changes)
        recent = store.get_recent(entity_id="A")
        assert len(recent) == 1
        assert recent[0].entity_id == "A"

    def test_get_recent_limit(self, store):
        changes = capture_delta(None, _graph_abc())
        store.store(changes)
        recent = store.get_recent(limit=2)
        assert len(recent) == 2

    def test_get_between(self, store):
        changes = capture_delta(None, _graph_abc())
        store.store(changes)
        start = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
        end = datetime.now(tz=timezone.utc) + timedelta(minutes=1)
        between = store.get_between(start, end)
        assert len(between) == 5

    def test_get_between_empty_range(self, store):
        changes = capture_delta(None, _graph_abc())
        store.store(changes)
        old_start = datetime(2020, 1, 1)
        old_end = datetime(2020, 1, 2)
        between = store.get_between(old_start, old_end)
        assert len(between) == 0

    def test_purge_old(self, store):
        changes = capture_delta(None, _graph_abc())
        # Set old timestamps
        for c in changes:
            c.timestamp = (datetime.now(tz=timezone.utc) - timedelta(days=30)).isoformat()
        store.store(changes)
        deleted = store.purge_old(retention_days=7)
        assert deleted == 5
        assert store.get_recent(window=timedelta(days=365)) == []

    def test_purge_keeps_recent(self, store):
        changes = capture_delta(None, _graph_abc())
        store.store(changes)
        deleted = store.purge_old(retention_days=7)
        assert deleted == 0
        assert len(store.get_recent()) == 5

    def test_schema_created(self, tmp_db):
        """Schema is created on init."""
        store = DeltaStore(db_path=tmp_db)
        assert os.path.exists(tmp_db)
        # Can create again without error (IF NOT EXISTS)
        store2 = DeltaStore(db_path=tmp_db)
        assert store2 is not None


# ── TopologyChange model ─────────────────────────────────────────────


class TestTopologyChange:
    def test_to_dict(self):
        c = TopologyChange(
            change_type="node_added",
            entity_id="vpc-1",
            entity_type="vpc",
            new_value={"label": "test"},
            source="discovery",
        )
        d = c.to_dict()
        assert d["change_type"] == "node_added"
        assert d["entity_id"] == "vpc-1"
        assert d["new_value"]["label"] == "test"

    def test_defaults(self):
        c = TopologyChange(change_type="node_added", entity_id="x")
        assert c.source == "discovery"
        assert c.old_value is None
        assert c.new_value is None


# ── format_recent_changes ────────────────────────────────────────────


class TestFormatRecentChanges:
    def test_empty(self):
        assert "No topology changes" in format_recent_changes([])

    def test_node_added(self):
        changes = [TopologyChange(
            change_type="node_added", entity_id="vpc-1",
            entity_type="vpc", timestamp="2026-02-26T10:00:00",
        )]
        out = format_recent_changes(changes)
        assert "+ Node vpc-1" in out
        assert "vpc" in out

    def test_node_removed(self):
        changes = [TopologyChange(
            change_type="node_removed", entity_id="nat-1",
            entity_type="nat", timestamp="2026-02-26T10:00:00",
        )]
        out = format_recent_changes(changes)
        assert "- Node nat-1" in out

    def test_node_updated(self):
        changes = [TopologyChange(
            change_type="node_updated", entity_id="i-123",
            old_value={"status": "healthy"}, new_value={"status": "error"},
            timestamp="2026-02-26T10:00:00",
        )]
        out = format_recent_changes(changes)
        assert "~ Node i-123" in out
        assert "healthy → error" in out

    def test_edge_changes(self):
        changes = [
            TopologyChange(change_type="edge_added", entity_id="A->B",
                           entity_type="routes_to", timestamp="2026-02-26T10:00:00"),
            TopologyChange(change_type="edge_removed", entity_id="B->C",
                           entity_type="contains", timestamp="2026-02-26T10:00:00"),
        ]
        out = format_recent_changes(changes)
        assert "+ Edge A->B" in out
        assert "- Edge B->C" in out

    def test_max_items_truncation(self):
        changes = [
            TopologyChange(
                change_type="node_added", entity_id=f"n-{i}",
                timestamp="2026-02-26T10:00:00",
            )
            for i in range(20)
        ]
        out = format_recent_changes(changes, max_items=5)
        assert "15 more changes" in out


# ── _sanitize_attrs ──────────────────────────────────────────────────


class TestSanitizeAttrs:
    def test_primitives(self):
        result = _sanitize_attrs({"a": 1, "b": "x", "c": True, "d": None})
        assert result == {"a": 1, "b": "x", "c": True, "d": None}

    def test_nested_dict(self):
        result = _sanitize_attrs({"nested": {"x": 1}})
        assert result["nested"]["x"] == 1

    def test_non_serialisable_to_str(self):
        result = _sanitize_attrs({"obj": object()})
        assert isinstance(result["obj"], str)

    def test_list_preserved(self):
        result = _sanitize_attrs({"items": [1, 2, 3]})
        assert result["items"] == [1, 2, 3]

    def test_tuple_to_list(self):
        result = _sanitize_attrs({"t": (1, 2)})
        assert result["t"] == [1, 2]
