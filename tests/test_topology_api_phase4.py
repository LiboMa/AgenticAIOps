"""Tests for Phase 4 Topology API endpoints — propagation, changes, overlay.

Tests cover:
- GET /api/topology/vpc/{vpc_id}/propagation — parameter validation, 404, schema
- GET /api/topology/vpc/{vpc_id}/changes — since/source/limit filters, scoping
- GET /api/topology/vpc/{vpc_id}?annotate_propagation=... — overlay data
- annotate_propagation_overlay() serializer function
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.aci.topology.delta import DeltaStore, TopologyChange
from src.aci.topology.engine import InfraGraph
from src.aci.topology.propagation import (
    PropagationMode,
    PropagationResult,
    PropagationWave,
    WaveEntry,
    ImpactLevel,
    fault_propagation,
)
from src.aci.topology.serializers import annotate_propagation_overlay, to_reactflow
from src.aci.topology.types import GraphMetadata, GraphNode, GraphEdge, SerializedGraph


# ── Fixtures ─────────────────────────────────────────────────────────


def _build_test_graph() -> InfraGraph:
    """Build a small test topology graph."""
    graph = InfraGraph()
    g = graph.graph

    g.add_node("igw-1", node_type="igw", label="IGW", status="healthy")
    g.add_node("nat-1", node_type="nat", label="NAT-1", status="healthy")
    g.add_node("subnet-pub", node_type="subnet", label="Public Subnet", status="healthy")
    g.add_node("subnet-priv", node_type="subnet", label="Private Subnet", status="healthy")
    g.add_node("rtb-main", node_type="rtb", label="Main RTB", status="healthy")

    g.add_edge("igw-1", "subnet-pub", edge_type="ROUTES_THROUGH")
    g.add_edge("subnet-pub", "nat-1", edge_type="ROUTES_THROUGH")
    g.add_edge("nat-1", "subnet-priv", edge_type="ROUTES_THROUGH")
    g.add_edge("subnet-priv", "rtb-main", edge_type="ASSOCIATED_WITH")

    return graph


def _make_test_app():
    """Create a test FastAPI app with topology router."""
    from fastapi import FastAPI
    from src.aci.topology.api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── GET /vpc/{vpc_id}/propagation ────────────────────────────────────


class TestPropagationEndpoint:
    @patch("src.aci.topology.api._build_vpc_graph")
    def test_basic_propagation(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test/propagation",
            params={"node_id": "nat-1", "mode": "realistic"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["root_failure"]["id"] == "nat-1"
        assert data["mode"] == "realistic"
        assert "waves" in data
        assert "summary" in data
        assert "critical_path" in data

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_propagation_pessimistic(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test/propagation",
            params={"node_id": "nat-1", "mode": "pessimistic"},
        )

        assert resp.status_code == 200
        assert resp.json()["mode"] == "pessimistic"

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_missing_node_id_422(self, mock_build):
        client = _make_test_app()
        resp = client.get("/api/topology/vpc/vpc-test/propagation")
        assert resp.status_code == 422  # FastAPI required param

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_invalid_mode_422(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test/propagation",
            params={"node_id": "nat-1", "mode": "invalid_mode"},
        )

        assert resp.status_code == 422
        assert "Invalid mode" in resp.json()["detail"]

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_node_not_found_404(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test/propagation",
            params={"node_id": "nonexistent-node"},
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_max_depth_param(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test/propagation",
            params={"node_id": "nat-1", "max_depth": 2},
        )

        assert resp.status_code == 200

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_max_depth_boundary_zero(self, mock_build):
        client = _make_test_app()
        resp = client.get(
            "/api/topology/vpc/vpc-test/propagation",
            params={"node_id": "nat-1", "max_depth": 0},
        )
        assert resp.status_code == 422  # ge=1

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_vpc_build_failure_404(self, mock_build):
        mock_build.side_effect = Exception("VPC not found")
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-bad/propagation",
            params={"node_id": "nat-1"},
        )

        assert resp.status_code == 404

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_propagation_response_schema(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test/propagation",
            params={"node_id": "igw-1", "mode": "realistic"},
        )

        data = resp.json()
        assert "root_failure" in data
        assert "mode" in data
        assert "waves" in data
        assert "summary" in data
        assert "total_affected" in data["summary"]
        assert "blast_radius_score" in data["summary"]
        assert "propagation_time_ms" in data
        assert "rca_context_block" in data


# ── GET /vpc/{vpc_id}/changes ────────────────────────────────────────


class TestChangesEndpoint:
    def _setup_store(self, tmpdir: str) -> DeltaStore:
        db_path = os.path.join(tmpdir, "test.db")
        store = DeltaStore(db_path=db_path)
        now = datetime.now(tz=timezone.utc)
        store.store([
            TopologyChange(
                change_type="node_added",
                entity_id="nat-new",
                entity_type="nat",
                source="cloudtrail",
                source_detail="CreateNatGateway",
                new_value={"vpc_id": "vpc-test", "event_name": "CreateNatGateway"},
                timestamp=(now - timedelta(minutes=10)).isoformat(),
            ),
            TopologyChange(
                change_type="node_removed",
                entity_id="subnet-old",
                entity_type="subnet",
                source="discovery",
                source_detail="graph diff",
                new_value={"vpc_id": "vpc-test"},
                timestamp=(now - timedelta(minutes=5)).isoformat(),
            ),
            TopologyChange(
                change_type="node_updated",
                entity_id="sg-456",
                entity_type="sg",
                source="cloudtrail",
                source_detail="AuthorizeSecurityGroupIngress",
                new_value={"vpc_id": "vpc-other"},
                timestamp=(now - timedelta(minutes=3)).isoformat(),
            ),
        ])
        return store

    @patch("src.aci.topology.api.get_delta_store")
    def test_basic_changes(self, mock_get_store):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._setup_store(tmpdir)
            mock_get_store.return_value = store
            client = _make_test_app()

            resp = client.get("/api/topology/vpc/vpc-test/changes")

            assert resp.status_code == 200
            data = resp.json()
            assert "changes" in data
            assert "count" in data
            assert "summary" in data
            assert data["vpc_id"] == "vpc-test"

    @patch("src.aci.topology.api.get_delta_store")
    def test_changes_source_filter(self, mock_get_store):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._setup_store(tmpdir)
            mock_get_store.return_value = store
            client = _make_test_app()

            resp = client.get(
                "/api/topology/vpc/vpc-test/changes",
                params={"source": "cloudtrail"},
            )

            data = resp.json()
            assert data["source_filter"] == "cloudtrail"
            for c in data["changes"]:
                assert c["source"] == "cloudtrail"

    @patch("src.aci.topology.api.get_delta_store")
    def test_changes_invalid_source_422(self, mock_get_store):
        client = _make_test_app()
        resp = client.get(
            "/api/topology/vpc/vpc-test/changes",
            params={"source": "invalid_source"},
        )
        assert resp.status_code == 422
        assert "Invalid source" in resp.json()["detail"]

    @patch("src.aci.topology.api.get_delta_store")
    def test_changes_since_param(self, mock_get_store):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._setup_store(tmpdir)
            mock_get_store.return_value = store
            client = _make_test_app()

            since = (datetime.now(tz=timezone.utc) - timedelta(minutes=7)).isoformat()
            resp = client.get(
                "/api/topology/vpc/vpc-test/changes",
                params={"since": since},
            )

            assert resp.status_code == 200

    @patch("src.aci.topology.api.get_delta_store")
    def test_changes_invalid_since_422(self, mock_get_store):
        client = _make_test_app()
        resp = client.get(
            "/api/topology/vpc/vpc-test/changes",
            params={"since": "not-a-timestamp"},
        )
        assert resp.status_code == 422
        assert "Invalid 'since'" in resp.json()["detail"]

    @patch("src.aci.topology.api.get_delta_store")
    def test_changes_limit(self, mock_get_store):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._setup_store(tmpdir)
            mock_get_store.return_value = store
            client = _make_test_app()

            resp = client.get(
                "/api/topology/vpc/vpc-test/changes",
                params={"limit": 1},
            )

            assert resp.status_code == 200

    @patch("src.aci.topology.api.get_delta_store")
    def test_changes_empty_result(self, mock_get_store):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "empty.db")
            store = DeltaStore(db_path=db_path)
            mock_get_store.return_value = store
            client = _make_test_app()

            resp = client.get("/api/topology/vpc/vpc-test/changes")

            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0
            assert data["changes"] == []

    @patch("src.aci.topology.api.get_delta_store")
    def test_changes_vpc_scope_isolation(self, mock_get_store):
        """Changes for vpc-other should not appear when querying vpc-test."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._setup_store(tmpdir)
            mock_get_store.return_value = store
            client = _make_test_app()

            resp = client.get("/api/topology/vpc/vpc-other/changes")
            data = resp.json()

            # Only sg-456 (vpc-other) should appear
            vpc_other_entities = [c["entity_id"] for c in data["changes"]]
            assert "sg-456" in vpc_other_entities
            # nat-new and subnet-old are vpc-test, should not appear
            assert "nat-new" not in vpc_other_entities
            assert "subnet-old" not in vpc_other_entities


# ── GET /vpc/{vpc_id}?annotate_propagation=... ───────────────────────


class TestAnnotatePropagationEndpoint:
    @patch("src.aci.topology.api._build_vpc_graph")
    def test_no_annotation_returns_base(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get("/api/topology/vpc/vpc-test")

        assert resp.status_code == 200
        data = resp.json()
        # No propagation overlay
        assert data.get("metadata", {}).get("propagation") is None

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_with_annotation(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test",
            params={"annotate_propagation": "nat-1"},
        )

        assert resp.status_code == 200
        data = resp.json()
        meta_prop = data.get("metadata", {}).get("propagation")
        assert meta_prop is not None
        assert meta_prop["origin"] == "nat-1"
        assert "blast_radius" in meta_prop
        assert "affected_count" in meta_prop

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_annotation_nonexistent_node_returns_base(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test",
            params={"annotate_propagation": "doesnt-exist"},
        )

        assert resp.status_code == 200
        data = resp.json()
        # Should return base graph without propagation
        assert data.get("metadata", {}).get("propagation") is None

    @patch("src.aci.topology.api._build_vpc_graph")
    def test_annotation_nodes_have_propagation_data(self, mock_build):
        mock_build.return_value = _build_test_graph()
        client = _make_test_app()

        resp = client.get(
            "/api/topology/vpc/vpc-test",
            params={"annotate_propagation": "igw-1"},
        )

        data = resp.json()
        # At least the origin node should have propagation data
        annotated_nodes = [
            n for n in data["nodes"]
            if n.get("data", {}).get("propagation") is not None
        ]
        assert len(annotated_nodes) >= 1
        origin_node = next(
            (n for n in annotated_nodes if n["id"] == "igw-1"),
            None,
        )
        assert origin_node is not None
        assert origin_node["data"]["propagation"]["is_origin"] is True


# ── annotate_propagation_overlay() unit tests ────────────────────────


class TestAnnotatePropagationOverlay:
    def _make_rf(self) -> SerializedGraph:
        return SerializedGraph(
            nodes=[
                GraphNode(id="n1", type="natNode", data={"label": "NAT-1", "status": "healthy"}),
                GraphNode(id="n2", type="subnetNode", data={"label": "Subnet-1", "status": "healthy"}),
                GraphNode(id="n3", type="rtbNode", data={"label": "RTB-1", "status": "healthy"}),
            ],
            edges=[
                GraphEdge(id="e1", source="n1", target="n2", data={"label": "", "style": "solid"}),
                GraphEdge(id="e2", source="n2", target="n3", data={"label": "", "style": "solid"}),
            ],
            metadata=GraphMetadata(node_count=3, edge_count=2),
        )

    def _make_prop_result(self) -> PropagationResult:
        return PropagationResult(
            origin_node="n1",
            mode=PropagationMode.REALISTIC,
            affected_nodes=["n1", "n2"],
            edge_weights={("n1", "n2"): 0.8},
            total_impact_score=0.4,
            critical_path=["n1", "n2"],
            waves=[
                PropagationWave(depth=0, affected=[
                    WaveEntry(node_id="n1", node_type="nat", impact_level=ImpactLevel.FAILED, reason="root"),
                ]),
                PropagationWave(depth=1, affected=[
                    WaveEntry(node_id="n2", node_type="subnet", impact_level=ImpactLevel.DEGRADED, reason="downstream"),
                ]),
            ],
        )

    def test_overlay_adds_propagation_to_nodes(self):
        rf = self._make_rf()
        prop = self._make_prop_result()

        result = annotate_propagation_overlay(rf, prop)

        n1 = next(n for n in result.nodes if n.id == "n1")
        assert "propagation" in n1.data
        assert n1.data["propagation"]["wave"] == 0
        assert n1.data["propagation"]["is_origin"] is True

        n2 = next(n for n in result.nodes if n.id == "n2")
        assert "propagation" in n2.data
        assert n2.data["propagation"]["wave"] == 1
        assert n2.data["propagation"]["is_origin"] is False

    def test_unaffected_node_no_propagation(self):
        rf = self._make_rf()
        prop = self._make_prop_result()

        result = annotate_propagation_overlay(rf, prop)

        n3 = next(n for n in result.nodes if n.id == "n3")
        assert "propagation" not in n3.data

    def test_overlay_adds_propagation_to_edges(self):
        rf = self._make_rf()
        prop = self._make_prop_result()

        result = annotate_propagation_overlay(rf, prop)

        e1 = next(e for e in result.edges if e.id == "e1")
        assert "propagation" in e1.data
        assert e1.data["propagation"]["weight"] == 0.8
        assert e1.data["propagation"]["on_critical_path"] is True

        e2 = next(e for e in result.edges if e.id == "e2")
        assert "propagation" not in e2.data

    def test_overlay_adds_metadata(self):
        rf = self._make_rf()
        prop = self._make_prop_result()

        result = annotate_propagation_overlay(rf, prop)

        assert result.metadata.propagation is not None
        assert result.metadata.propagation["origin"] == "n1"
        assert result.metadata.propagation["blast_radius"] == 0.4
        assert result.metadata.propagation["affected_count"] == 2
        assert result.metadata.propagation["wave_count"] == 2

    def test_overlay_empty_propagation(self):
        rf = self._make_rf()
        prop = PropagationResult(
            origin_node="nonexistent",
            mode=PropagationMode.REALISTIC,
        )

        result = annotate_propagation_overlay(rf, prop)

        # No nodes should have propagation
        for n in result.nodes:
            assert "propagation" not in n.data
        assert result.metadata.propagation is not None
        assert result.metadata.propagation["affected_count"] == 0
