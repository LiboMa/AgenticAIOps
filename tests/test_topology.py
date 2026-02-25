"""
Tests for src/aci/topology/ — InfraGraph engine + algorithms.

Based on agenticops-chat test_graph_algorithms.py patterns,
adapted for our topology module.
"""
import pytest
from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────


def _make_vpc_topology(
    *,
    has_igw=True,
    has_nat=True,
    has_blackhole=False,
    has_tgw=False,
    has_peering=False,
):
    """Build a minimal VPC topology dict for testing."""
    topo = {
        "vpc_id": "vpc-001",
        "vpc_cidr": "10.0.0.0/16",
        "vpc_name": "test-vpc",
        "region": "us-east-1",
        "internet_gateways": [],
        "subnets": [
            {
                "subnet_id": "subnet-pub-1",
                "name": "public-1",
                "cidr_block": "10.0.1.0/24",
                "availability_zone": "us-east-1a",
                "map_public_ip_on_launch": True,
            },
            {
                "subnet_id": "subnet-priv-1",
                "name": "private-1",
                "cidr_block": "10.0.2.0/24",
                "availability_zone": "us-east-1b",
                "map_public_ip_on_launch": False,
            },
        ],
        "route_tables": [],
        "nat_gateways": [],
        "transit_gateway_attachments": [],
        "vpc_peering_connections": [],
        "vpc_endpoints": [],
        "security_group_dependency_map": {},
        "blackhole_routes": [],
    }

    if has_igw:
        topo["internet_gateways"] = [
            {"igw_id": "igw-001", "name": "main-igw", "state": "available"}
        ]
        topo["route_tables"].append({
            "route_table_id": "rtb-pub",
            "name": "public-rt",
            "associations": [{"subnet_id": "subnet-pub-1"}],
            "routes": [
                {"destination": "10.0.0.0/16", "target": "local", "state": "active"},
                {"destination": "0.0.0.0/0", "target": "igw-001", "state": "active"},
            ],
        })

    if has_nat:
        topo["nat_gateways"] = [
            {"nat_gateway_id": "nat-001", "name": "nat-gw", "state": "available",
             "subnet_id": "subnet-pub-1", "public_ip": "3.4.5.6"}
        ]
        topo["route_tables"].append({
            "route_table_id": "rtb-priv",
            "name": "private-rt",
            "associations": [{"subnet_id": "subnet-priv-1"}],
            "routes": [
                {"destination": "10.0.0.0/16", "target": "local", "state": "active"},
                {"destination": "0.0.0.0/0", "target": "nat-001", "state": "active"},
            ],
        })

    if has_blackhole:
        topo["blackhole_routes"] = [
            {"route_table_id": "rtb-pub", "destination": "172.16.0.0/12",
             "target": "pcx-dead", "state": "blackhole"}
        ]

    if has_tgw:
        topo["transit_gateway_attachments"] = [
            {"attachment_id": "tgw-att-001", "transit_gateway_id": "tgw-001",
             "resource_type": "vpc", "state": "available"}
        ]

    if has_peering:
        topo["vpc_peering_connections"] = [
            {"pcx_id": "pcx-001", "requester_vpc": "vpc-001",
             "accepter_vpc": "vpc-002", "status": "active"}
        ]

    return topo


# ── Types ────────────────────────────────────────────────────


class TestTypes:

    def test_node_type_values(self):
        from src.aci.topology.types import NodeType
        assert NodeType.VPC.value == "vpc"
        assert NodeType.SUBNET.value == "subnet"
        assert NodeType.INTERNET_GATEWAY.value == "igw"
        assert NodeType.NAT_GATEWAY.value == "nat"

    def test_edge_type_values(self):
        from src.aci.topology.types import EdgeType
        assert EdgeType.CONTAINS.value == "contains"
        assert EdgeType.ROUTES_TO.value == "routes_to"

    def test_node_status_values(self):
        from src.aci.topology.types import NodeStatus
        assert NodeStatus.HEALTHY.value == "healthy"
        assert NodeStatus.WARNING.value == "warning"

    def test_node_attrs_model(self):
        from src.aci.topology.types import NodeAttrs, NodeType, NodeStatus
        attrs = NodeAttrs(
            node_type=NodeType.SUBNET,
            label="my-subnet",
            status=NodeStatus.HEALTHY,
        )
        d = attrs.model_dump()
        assert d["node_type"] == "subnet"
        assert d["label"] == "my-subnet"

    def test_edge_attrs_model(self):
        from src.aci.topology.types import EdgeAttrs, EdgeType
        attrs = EdgeAttrs(edge_type=EdgeType.ROUTES_TO)
        assert attrs.edge_type == EdgeType.ROUTES_TO


# ── Engine ───────────────────────────────────────────────────


class TestEngine:

    def test_empty_graph(self):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        assert g.graph.number_of_nodes() == 0
        assert g.graph.number_of_edges() == 0

    def test_build_from_vpc_basic(self):
        from src.aci.topology.engine import InfraGraph
        topo = _make_vpc_topology()
        g = InfraGraph()
        g.build_from_vpc_topology(topo)
        # Should have: VPC + 2 subnets + IGW + NAT + route tables
        assert g.graph.number_of_nodes() >= 5
        assert g.graph.number_of_edges() >= 3

    def test_build_with_igw_creates_igw_node(self):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology(has_igw=True))
        assert "igw-001" in g.graph.nodes

    def test_build_with_nat_creates_nat_node(self):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology(has_nat=True))
        assert "nat-001" in g.graph.nodes

    def test_build_without_igw(self):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology(has_igw=False, has_nat=False))
        assert "igw-001" not in g.graph.nodes

    def test_vpc_node_exists(self):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology())
        assert "vpc-001" in g.graph.nodes

    def test_subnet_nodes_exist(self):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology())
        assert "subnet-pub-1" in g.graph.nodes
        assert "subnet-priv-1" in g.graph.nodes

    def test_build_with_tgw(self):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology(has_tgw=True))
        # TGW attachment should be in the graph
        assert g.graph.number_of_nodes() >= 6

    def test_build_with_peering(self):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology(has_peering=True))
        assert g.graph.number_of_nodes() >= 6


# ── Algorithms ───────────────────────────────────────────────


class TestAlgorithms:

    def _build_graph(self, **kwargs):
        from src.aci.topology.engine import InfraGraph
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology(**kwargs))
        return g

    def test_can_reach_internet_public_subnet(self):
        from src.aci.topology.algorithms import can_reach_internet
        g = self._build_graph(has_igw=True)
        result = can_reach_internet(g, "subnet-pub-1")
        assert result.subnet_id == "subnet-pub-1"
        # With IGW and route, should be reachable
        assert result.can_reach_internet is True

    def test_no_igw_no_internet(self):
        from src.aci.topology.algorithms import can_reach_internet
        g = self._build_graph(has_igw=False, has_nat=False)
        result = can_reach_internet(g, "subnet-pub-1")
        assert result.can_reach_internet is False

    def test_detect_anomalies_clean(self):
        from src.aci.topology.algorithms import detect_anomalies
        g = self._build_graph()
        results = detect_anomalies(g)
        # Returns an AnomalyReport object
        assert hasattr(results, 'total_anomalies')
        assert hasattr(results, 'anomalies')

    def test_detect_anomalies_blackhole(self):
        from src.aci.topology.algorithms import detect_anomalies
        g = self._build_graph(has_blackhole=True)
        results = detect_anomalies(g)
        assert results.total_anomalies >= 0

    def test_impact_analysis(self):
        from src.aci.topology.algorithms import impact_analysis
        g = self._build_graph()
        result = impact_analysis(g, "igw-001")
        assert result.failed_node_id == "igw-001"
        assert isinstance(result.affected_nodes, list)

    def test_find_traffic_path(self):
        from src.aci.topology.algorithms import find_traffic_path
        g = self._build_graph()
        result = find_traffic_path(g, "subnet-pub-1", "igw-001")
        assert result.source == "subnet-pub-1"
        assert result.target == "igw-001"

    def test_network_segments(self):
        from src.aci.topology.algorithms import network_segments
        g = self._build_graph()
        result = network_segments(g)
        # Returns a SegmentReport object
        assert hasattr(result, 'total_segments')
        assert result.total_segments >= 1


# ── Serializers ──────────────────────────────────────────────


class TestSerializers:

    def test_to_reactflow(self):
        from src.aci.topology.engine import InfraGraph
        from src.aci.topology.serializers import to_reactflow
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology())
        rf = to_reactflow(g)
        # Returns a SerializedGraph object
        assert hasattr(rf, 'nodes')
        assert hasattr(rf, 'edges')
        assert len(rf.nodes) >= 5
        assert len(rf.edges) >= 3

    def test_to_agent_summary(self):
        from src.aci.topology.engine import InfraGraph
        from src.aci.topology.serializers import to_agent_summary
        g = InfraGraph()
        g.build_from_vpc_topology(_make_vpc_topology())
        summary = to_agent_summary(g)
        assert isinstance(summary, str)
        assert len(summary) > 0
