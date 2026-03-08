"""Topology coverage tests — targeting uncovered lines in api.py, tools.py,
algorithms.py, and serializers.py.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from src.aci.topology.algorithms import (
    AnomalyReport,
    ImpactResult,
    PathResult,
    ReachabilityResult,
    can_reach_internet,
    detect_anomalies,
    find_traffic_path,
    impact_analysis,
    network_segments,
    _build_path_details,
    _path_has_blackhole,
)
from src.aci.topology.engine import InfraGraph
from src.aci.topology.serializers import to_agent_summary, to_reactflow
from src.aci.topology.types import (
    EdgeType,
    NodeStatus,
    NodeType,
    VpcTopology,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_graph_with_blackhole_path() -> InfraGraph:
    """Build a graph where the path to IGW passes through a blackhole edge."""
    g = InfraGraph()
    g.graph.add_node("subnet-1", node_type=NodeType.SUBNET, label="sub1",
                      status=NodeStatus.HEALTHY, raw={"type": "public"})
    g.graph.add_node("rtb-1", node_type=NodeType.ROUTE_TABLE, label="rtb1",
                      status=NodeStatus.HEALTHY, raw={})
    g.graph.add_node("igw-1", node_type=NodeType.INTERNET_GATEWAY, label="igw1",
                      status=NodeStatus.HEALTHY, raw={})
    # Connect: subnet -> rtb -> igw, but rtb->igw is blackhole
    g.graph.add_edge("subnet-1", "rtb-1", edge_type=EdgeType.ASSOCIATED_WITH,
                     label="assoc", state="")
    g.graph.add_edge("rtb-1", "igw-1", edge_type=EdgeType.ROUTES_TO,
                     label="0.0.0.0/0", state="blackhole")
    return g


def _make_graph_with_error_nodes() -> InfraGraph:
    """Build a graph with error status nodes and blackhole edges for serializer coverage."""
    g = InfraGraph()
    g.graph.add_node("vpc-1", node_type=NodeType.VPC, label="myvpc",
                      status=NodeStatus.HEALTHY, raw={})
    g.graph.add_node("nat-err", node_type=NodeType.NAT_GATEWAY, label="broken-nat",
                      status=NodeStatus.ERROR, raw={}, resource_type="nat")
    g.graph.add_node("subnet-a", node_type=NodeType.SUBNET, label="suba",
                      status=NodeStatus.HEALTHY, raw={"type": "public"})
    g.graph.add_edge("vpc-1", "subnet-a", edge_type=EdgeType.CONTAINS,
                     label="contains", state="")
    g.graph.add_edge("subnet-a", "nat-err", edge_type=EdgeType.ROUTES_TO,
                     label="0.0.0.0/0", state="blackhole")
    return g


def _make_impact_graph() -> InfraGraph:
    """Graph with NAT that multiple subnets depend on for internet."""
    g = InfraGraph()
    g.graph.add_node("igw-1", node_type=NodeType.INTERNET_GATEWAY, label="igw",
                      status=NodeStatus.HEALTHY, raw={})
    g.graph.add_node("nat-1", node_type=NodeType.NAT_GATEWAY, label="nat",
                      status=NodeStatus.HEALTHY, raw={})
    # 4 private subnets that go through NAT to IGW
    for i in range(4):
        sid = f"subnet-{i}"
        g.graph.add_node(sid, node_type=NodeType.SUBNET, label=f"sub{i}",
                          status=NodeStatus.HEALTHY, raw={"type": "private"})
        g.graph.add_edge(sid, "nat-1", edge_type=EdgeType.ROUTES_TO, label="", state="")
    g.graph.add_edge("nat-1", "igw-1", edge_type=EdgeType.ROUTES_TO, label="", state="")
    return g


# ── Test API error paths (api.py lines 76-78, 91-93, 106-108, etc.) ─


class TestApiErrorPaths:
    """Cover all exception-return paths in api.py endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from src.aci.topology.api import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    @patch("src.aci.topology.api._build_vpc_graph", side_effect=RuntimeError("boom"))
    def test_get_vpc_graph_error(self, mock_build, client):
        resp = client.get("/api/topology/vpc/vpc-123?region=us-east-1")
        assert resp.status_code == 500
        assert "boom" in resp.json()["error"]

    @patch("src.aci.topology.api._build_region_graph", side_effect=RuntimeError("boom"))
    def test_get_region_graph_error(self, mock_build, client):
        resp = client.get("/api/topology/region?region=us-east-1")
        assert resp.status_code == 500
        assert "boom" in resp.json()["error"]

    @patch("src.aci.topology.api._build_vpc_graph", side_effect=RuntimeError("boom"))
    def test_get_reachability_error(self, mock_build, client):
        resp = client.get("/api/topology/vpc/vpc-1/reachability/subnet-1?region=us-east-1")
        assert resp.status_code == 500

    @patch("src.aci.topology.api._build_vpc_graph", side_effect=RuntimeError("boom"))
    def test_get_impact_error(self, mock_build, client):
        resp = client.get("/api/topology/vpc/vpc-1/impact/igw-1?region=us-east-1")
        assert resp.status_code == 500

    @patch("src.aci.topology.api._build_vpc_graph", side_effect=RuntimeError("boom"))
    def test_get_path_error(self, mock_build, client):
        resp = client.get("/api/topology/vpc/vpc-1/path?source=a&target=b&region=us-east-1")
        assert resp.status_code == 500

    @patch("src.aci.topology.api._build_vpc_graph", side_effect=RuntimeError("boom"))
    def test_get_anomalies_error(self, mock_build, client):
        resp = client.get("/api/topology/vpc/vpc-1/anomalies?region=us-east-1")
        assert resp.status_code == 500

    @patch("src.aci.topology.api._build_region_graph", side_effect=RuntimeError("boom"))
    def test_get_segments_error(self, mock_build, client):
        resp = client.get("/api/topology/region/segments?region=us-east-1")
        assert resp.status_code == 500


# ── Test tools.py error paths (lines 87-89, 112-114, 135-137, 160-162) ──


class TestToolsErrorPaths:
    """Cover exception-return paths in tools.py."""

    @patch("src.aci.topology.tools._build_vpc_graph", side_effect=ValueError("fail"))
    def test_query_reachability_error(self, mock_build):
        from src.aci.topology.tools import query_reachability
        result = query_reachability(region="us-east-1", vpc_id="vpc-1", subnet_id="subnet-1")
        data = json.loads(result)
        assert "error" in data

    @patch("src.aci.topology.tools._build_vpc_graph", side_effect=ValueError("fail"))
    def test_query_impact_radius_error(self, mock_build):
        from src.aci.topology.tools import query_impact_radius
        result = query_impact_radius(region="us-east-1", vpc_id="vpc-1", resource_id="igw-1")
        data = json.loads(result)
        assert "error" in data

    @patch("src.aci.topology.tools._build_vpc_graph", side_effect=ValueError("fail"))
    def test_find_network_path_error(self, mock_build):
        from src.aci.topology.tools import find_network_path
        result = find_network_path(region="us-east-1", vpc_id="vpc-1",
                                   source="a", target="b")
        data = json.loads(result)
        assert "error" in data

    @patch("src.aci.topology.tools._build_vpc_graph", side_effect=ValueError("fail"))
    def test_detect_network_anomalies_error(self, mock_build):
        from src.aci.topology.tools import detect_network_anomalies
        result = detect_network_anomalies(region="us-east-1", vpc_id="vpc-1")
        data = json.loads(result)
        assert "error" in data

    @patch("src.aci.topology.tools._build_region_graph", side_effect=ValueError("fail"))
    def test_analyze_network_segments_error(self, mock_build):
        from src.aci.topology.tools import analyze_network_segments
        result = analyze_network_segments(region="us-east-1")
        data = json.loads(result)
        assert "error" in data


# ── Test algorithms edge cases ───────────────────────────────────────


class TestBlackholeReachability:
    """Cover blackhole-path branch in can_reach_internet (lines 131, 145-148)."""

    def test_blackhole_blocks_internet(self):
        g = _make_graph_with_blackhole_path()
        result = can_reach_internet(g, "subnet-1")
        assert result.can_reach_internet is False
        assert "blackhole" in result.blocking_reason.lower()
        assert len(result.path) > 0

    def test_no_igw_returns_no_gateway(self):
        """Cover the 'No Internet Gateway found' branch."""
        g = InfraGraph()
        g.graph.add_node("subnet-x", node_type=NodeType.SUBNET, label="s",
                          status=NodeStatus.HEALTHY, raw={})
        result = can_reach_internet(g, "subnet-x")
        assert result.can_reach_internet is False
        assert "No Internet Gateway" in result.blocking_reason


class TestImpactAnalysis:
    """Cover impact_analysis edge cases (lines 209-210, 215-216, 219-220, etc.)."""

    def test_impact_critical_severity(self):
        """Removing NAT isolates >3 subnets → critical severity."""
        g = _make_impact_graph()
        result = impact_analysis(g, "nat-1")
        assert result.severity in ("critical", "high")
        assert len(result.isolated_subnets) >= 1

    def test_impact_unknown_node(self):
        """Node not in graph → severity='unknown'."""
        g = InfraGraph()
        result = impact_analysis(g, "nonexistent-node")
        assert result.severity == "unknown"

    def test_impact_low_severity(self):
        """Remove leaf node with no downstream impact → low."""
        g = InfraGraph()
        g.graph.add_node("subnet-1", node_type=NodeType.SUBNET, label="s1",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("rtb-1", node_type=NodeType.ROUTE_TABLE, label="rtb",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_edge("subnet-1", "rtb-1", edge_type=EdgeType.ASSOCIATED_WITH,
                         label="", state="")
        result = impact_analysis(g, "rtb-1")
        assert result.severity == "low"


class TestFindTrafficPath:
    """Cover find_traffic_path edge cases (lines 258-259, 269-271)."""

    def test_source_not_in_graph(self):
        g = InfraGraph()
        g.graph.add_node("a", node_type=NodeType.SUBNET, label="a",
                          status=NodeStatus.HEALTHY, raw={})
        result = find_traffic_path(g, "missing", "a")
        assert result.paths_found == 0

    def test_no_path_between_disconnected(self):
        g = InfraGraph()
        g.graph.add_node("a", node_type=NodeType.SUBNET, label="a",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("b", node_type=NodeType.SUBNET, label="b",
                          status=NodeStatus.HEALTHY, raw={})
        result = find_traffic_path(g, "a", "b")
        assert result.paths_found == 0

    def test_path_found(self):
        g = InfraGraph()
        g.graph.add_node("s1", node_type=NodeType.SUBNET, label="s1",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("rtb", node_type=NodeType.ROUTE_TABLE, label="rtb",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("igw", node_type=NodeType.INTERNET_GATEWAY, label="igw",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_edge("s1", "rtb", edge_type=EdgeType.ASSOCIATED_WITH, label="", state="")
        g.graph.add_edge("rtb", "igw", edge_type=EdgeType.ROUTES_TO, label="", state="")
        result = find_traffic_path(g, "s1", "igw")
        assert result.paths_found >= 1


class TestPathHelpers:
    """Cover _build_path_details and _path_has_blackhole helpers (lines 480, 492)."""

    def test_build_path_details_missing_node(self):
        """Node not in graph → type='unknown'."""
        g = nx.DiGraph()
        g.add_node("a", node_type="subnet", label="suba")
        details = _build_path_details(g, ["a", "missing-node"])
        assert details[1]["type"] == "unknown"

    def test_path_has_blackhole_true(self):
        g = nx.DiGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b", state="blackhole")
        assert _path_has_blackhole(g, ["a", "b"]) is True

    def test_path_has_blackhole_false(self):
        g = nx.DiGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b", state="active")
        assert _path_has_blackhole(g, ["a", "b"]) is False

    def test_path_has_blackhole_reverse_edge(self):
        """Blackhole on reverse direction edge (v→u)."""
        g = nx.DiGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("b", "a", state="blackhole")
        assert _path_has_blackhole(g, ["a", "b"]) is True


# ── Test anomaly detection edge cases ────────────────────────────────


class TestDetectAnomalies:
    """Cover detect_anomalies branches (lines 310, 353, 362-363, 384-385)."""

    def test_orphan_node_detected(self):
        g = InfraGraph()
        g.graph.add_node("lonely", node_type=NodeType.SUBNET, label="lonely",
                          status=NodeStatus.HEALTHY, raw={})
        result = detect_anomalies(g)
        assert result.total_anomalies >= 1
        types = [a.type for a in result.anomalies]
        assert "orphan_node" in types

    def test_blackhole_edge_detected(self):
        g = InfraGraph()
        g.graph.add_node("rtb-1", node_type=NodeType.ROUTE_TABLE, label="rtb",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("igw-1", node_type=NodeType.INTERNET_GATEWAY, label="igw",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_edge("rtb-1", "igw-1", edge_type=EdgeType.ROUTES_TO,
                         label="0.0.0.0/0", state="blackhole")
        result = detect_anomalies(g)
        types = [a.type for a in result.anomalies]
        assert "blackhole_route" in types

    def test_blackhole_from_route_table_raw(self):
        """Blackhole detected from route table raw data (line 310+)."""
        g = InfraGraph()
        g.graph.add_node("rtb-raw", node_type=NodeType.ROUTE_TABLE, label="rtb",
                          status=NodeStatus.HEALTHY,
                          raw={"routes": [{"state": "blackhole",
                                           "destination": "10.0.0.0/8",
                                           "target": "tgw-xxx"}]})
        g.graph.add_node("other", node_type=NodeType.SUBNET, label="s",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_edge("rtb-raw", "other", edge_type=EdgeType.ASSOCIATED_WITH,
                         label="", state="")
        result = detect_anomalies(g)
        types = [a.type for a in result.anomalies]
        assert "blackhole_route" in types

    def test_routing_cycle_detected(self):
        """Routing cycle detected (lines 353, 362-363)."""
        g = InfraGraph()
        g.graph.add_node("rtb-a", node_type=NodeType.ROUTE_TABLE, label="a",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("rtb-b", node_type=NodeType.ROUTE_TABLE, label="b",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_edge("rtb-a", "rtb-b", edge_type=EdgeType.ROUTES_TO,
                         label="", state="")
        g.graph.add_edge("rtb-b", "rtb-a", edge_type=EdgeType.ROUTES_TO,
                         label="", state="")
        result = detect_anomalies(g)
        types = [a.type for a in result.anomalies]
        assert "routing_cycle" in types

    def test_unreachable_public_subnet(self):
        """Public subnet with no IGW path (lines 384-385)."""
        g = InfraGraph()
        g.graph.add_node("igw-1", node_type=NodeType.INTERNET_GATEWAY, label="igw",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("subnet-pub", node_type=NodeType.SUBNET, label="pub",
                          status=NodeStatus.HEALTHY, raw={"type": "public"})
        # IGW exists but subnet is disconnected from it
        result = detect_anomalies(g)
        types = [a.type for a in result.anomalies]
        assert "unreachable_subnet" in types

    def test_error_status_node(self):
        """Node with ERROR status detected (line 400+)."""
        g = InfraGraph()
        g.graph.add_node("nat-bad", node_type=NodeType.NAT_GATEWAY, label="bad-nat",
                          status=NodeStatus.ERROR, raw={})
        g.graph.add_node("sub", node_type=NodeType.SUBNET, label="s",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_edge("sub", "nat-bad", edge_type=EdgeType.ROUTES_TO,
                         label="", state="")
        result = detect_anomalies(g)
        types = [a.type for a in result.anomalies]
        assert "unhealthy_node" in types

    def test_no_anomalies(self):
        """Clean graph → no anomalies."""
        g = InfraGraph()
        g.graph.add_node("s1", node_type=NodeType.SUBNET, label="s1",
                          status=NodeStatus.HEALTHY, raw={"type": "public"})
        g.graph.add_node("igw", node_type=NodeType.INTERNET_GATEWAY, label="igw",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_edge("s1", "igw", edge_type=EdgeType.ROUTES_TO,
                         label="0.0.0.0/0", state="active")
        result = detect_anomalies(g)
        assert "No anomalies" in result.summary


# ── Test serializers (lines 220-222, 229-231) ───────────────────────


class TestAgentSummarySerializer:
    """Cover blackhole and error-node reporting in to_agent_summary."""

    def test_summary_with_blackholes(self):
        g = _make_graph_with_error_nodes()
        summary = to_agent_summary(g)
        assert "Blackhole routes" in summary
        assert "blackhole" in summary.lower() or "0.0.0.0/0" in summary

    def test_summary_with_error_nodes(self):
        g = _make_graph_with_error_nodes()
        summary = to_agent_summary(g)
        assert "Error nodes" in summary
        assert "broken-nat" in summary

    def test_summary_clean_graph(self):
        g = InfraGraph()
        g.graph.add_node("vpc-1", node_type=NodeType.VPC, label="v",
                          status=NodeStatus.HEALTHY, raw={})
        summary = to_agent_summary(g)
        assert "Graph:" in summary
        assert "Blackhole" not in summary
        assert "Error nodes" not in summary


class TestReactflowSerializer:
    """Cover region-view branches in to_reactflow."""

    def test_region_view_vpc_node(self):
        g = InfraGraph()
        g.graph.add_node("vpc-1", node_type=NodeType.VPC, label="myvpc",
                          status=NodeStatus.HEALTHY,
                          raw={"vpc_id": "vpc-1", "cidr_block": "10.0.0.0/16",
                               "subnet_count": 3, "is_default": False, "state": "available"},
                          resource_type="vpc")
        result = to_reactflow(g, view="region")
        assert len(result.nodes) == 1
        assert result.nodes[0].data["vpcId"] == "vpc-1"

    def test_region_view_tgw_node(self):
        g = InfraGraph()
        g.graph.add_node("tgw-1", node_type=NodeType.TRANSIT_GATEWAY, label="mytgw",
                          status=NodeStatus.HEALTHY,
                          raw={"transit_gateway_id": "tgw-1", "state": "available",
                               "attachments": [{"id": "a1"}]},
                          resource_type="tgw")
        result = to_reactflow(g, view="region")
        assert len(result.nodes) == 1
        assert result.nodes[0].data["tgwId"] == "tgw-1"


class TestNetworkSegments:
    """Cover network_segments algorithm."""

    def test_isolated_vpc(self):
        g = InfraGraph()
        g.graph.add_node("vpc-lonely", node_type=NodeType.VPC, label="lonely",
                          status=NodeStatus.HEALTHY, raw={})
        result = network_segments(g)
        assert result.total_segments == 1
        assert "vpc-lonely" in result.isolated_vpcs

    def test_connected_segments(self):
        g = InfraGraph()
        g.graph.add_node("vpc-1", node_type=NodeType.VPC, label="v1",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("tgw-1", node_type=NodeType.TRANSIT_GATEWAY, label="tgw",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_node("vpc-2", node_type=NodeType.VPC, label="v2",
                          status=NodeStatus.HEALTHY, raw={})
        g.graph.add_edge("vpc-1", "tgw-1", edge_type=EdgeType.ATTACHED_TO, label="", state="")
        g.graph.add_edge("vpc-2", "tgw-1", edge_type=EdgeType.ATTACHED_TO, label="", state="")
        result = network_segments(g)
        assert result.total_segments == 1
        assert len(result.isolated_vpcs) == 0
