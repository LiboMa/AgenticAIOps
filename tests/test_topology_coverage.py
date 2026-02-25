"""[tester] Coverage gap tests for topology module — part 1: derive_status + engine edge cases.

Fills gaps: engine.py 71%→85%+, algorithms.py 87%→95%+
"""
import pytest
from src.aci.topology.engine import InfraGraph
from src.aci.topology.types import EdgeType, NodeStatus, NodeType
from src.aci.topology.algorithms import (
    can_reach_internet, detect_anomalies, find_traffic_path,
    impact_analysis, network_segments,
)
from src.aci.topology.serializers import to_reactflow, to_agent_summary


# ── _derive_*_status tests ──────────────────────────────────────────


class TestDeriveStatus:
    """Test all branches of _derive_*_status helpers."""

    def test_igw_status_no_attachments(self):
        assert InfraGraph._derive_igw_status([]) == NodeStatus.ERROR

    def test_igw_status_attached(self):
        assert InfraGraph._derive_igw_status([{"state": "attached"}]) == NodeStatus.HEALTHY

    def test_igw_status_detaching(self):
        assert InfraGraph._derive_igw_status([{"state": "detaching"}]) == NodeStatus.WARNING

    def test_igw_status_other(self):
        assert InfraGraph._derive_igw_status([{"state": "detached"}]) == NodeStatus.ERROR

    def test_subnet_status_none_ips(self):
        assert InfraGraph._derive_subnet_status({}) == NodeStatus.UNKNOWN

    def test_subnet_status_healthy(self):
        assert InfraGraph._derive_subnet_status({"available_ips": 100}) == NodeStatus.HEALTHY

    def test_subnet_status_warning(self):
        assert InfraGraph._derive_subnet_status({"available_ips": 7}) == NodeStatus.WARNING

    def test_subnet_status_error(self):
        assert InfraGraph._derive_subnet_status({"available_ips": 3}) == NodeStatus.ERROR

    def test_subnet_status_boundary_10(self):
        assert InfraGraph._derive_subnet_status({"available_ips": 10}) == NodeStatus.HEALTHY

    def test_subnet_status_boundary_5(self):
        assert InfraGraph._derive_subnet_status({"available_ips": 5}) == NodeStatus.WARNING

    def test_nat_status_available(self):
        assert InfraGraph._derive_nat_status({"state": "available"}) == NodeStatus.HEALTHY

    def test_nat_status_pending(self):
        assert InfraGraph._derive_nat_status({"state": "pending"}) == NodeStatus.WARNING

    def test_nat_status_failed(self):
        assert InfraGraph._derive_nat_status({"state": "failed"}) == NodeStatus.ERROR

    def test_nat_status_deleted(self):
        assert InfraGraph._derive_nat_status({"state": "deleted"}) == NodeStatus.ERROR

    def test_nat_status_deleting(self):
        assert InfraGraph._derive_nat_status({"state": "deleting"}) == NodeStatus.ERROR

    def test_nat_status_unknown(self):
        assert InfraGraph._derive_nat_status({"state": "something"}) == NodeStatus.UNKNOWN

    def test_tgw_status_available(self):
        assert InfraGraph._derive_tgw_status({"state": "available"}) == NodeStatus.HEALTHY

    def test_tgw_status_modifying(self):
        assert InfraGraph._derive_tgw_status({"state": "modifying"}) == NodeStatus.WARNING

    def test_tgw_status_pending_acceptance(self):
        assert InfraGraph._derive_tgw_status({"state": "pendingAcceptance"}) == NodeStatus.WARNING

    def test_tgw_status_failing(self):
        assert InfraGraph._derive_tgw_status({"state": "failing"}) == NodeStatus.ERROR

    def test_tgw_status_deleting(self):
        assert InfraGraph._derive_tgw_status({"state": "deleting"}) == NodeStatus.ERROR

    def test_tgw_status_unknown(self):
        assert InfraGraph._derive_tgw_status({"state": "other"}) == NodeStatus.UNKNOWN

    def test_peering_status_active(self):
        assert InfraGraph._derive_peering_status({"status": "active"}) == NodeStatus.HEALTHY

    def test_peering_status_pending(self):
        assert InfraGraph._derive_peering_status({"status": "pending-acceptance"}) == NodeStatus.WARNING

    def test_peering_status_provisioning(self):
        assert InfraGraph._derive_peering_status({"status": "provisioning"}) == NodeStatus.WARNING

    def test_peering_status_failed(self):
        assert InfraGraph._derive_peering_status({"status": "failed"}) == NodeStatus.ERROR

    def test_peering_status_expired(self):
        assert InfraGraph._derive_peering_status({"status": "expired"}) == NodeStatus.ERROR

    def test_peering_status_rejected(self):
        assert InfraGraph._derive_peering_status({"status": "rejected"}) == NodeStatus.ERROR

    def test_peering_status_unknown(self):
        assert InfraGraph._derive_peering_status({"status": "other"}) == NodeStatus.UNKNOWN

    def test_endpoint_status_available(self):
        assert InfraGraph._derive_endpoint_status({"state": "available"}) == NodeStatus.HEALTHY

    def test_endpoint_status_pending(self):
        assert InfraGraph._derive_endpoint_status({"state": "pending"}) == NodeStatus.WARNING

    def test_endpoint_status_pending_acceptance(self):
        assert InfraGraph._derive_endpoint_status({"state": "pendingAcceptance"}) == NodeStatus.WARNING

    def test_endpoint_status_failed(self):
        assert InfraGraph._derive_endpoint_status({"state": "failed"}) == NodeStatus.ERROR

    def test_endpoint_status_rejected(self):
        assert InfraGraph._derive_endpoint_status({"state": "rejected"}) == NodeStatus.ERROR

    def test_endpoint_status_deleted(self):
        assert InfraGraph._derive_endpoint_status({"state": "deleted"}) == NodeStatus.ERROR

    def test_endpoint_status_unknown(self):
        assert InfraGraph._derive_endpoint_status({"state": "other"}) == NodeStatus.UNKNOWN


# ── VPC Endpoints engine tests ──────────────────────────────────────


class TestEngineVpcEndpoints:
    def test_vpc_endpoint_nodes_created(self):
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [
                {"subnet_id": "sub-1", "name": "s1", "type": "private", "available_ips": 50}
            ],
            "route_tables": [], "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "blackhole_routes": [],
            "security_group_dependency_map": {},
            "vpc_endpoints": [
                {"endpoint_id": "vpce-001", "service_name": "com.amazonaws.us-east-1.s3",
                 "state": "available", "subnet_ids": ["sub-1"]},
            ],
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        endpoints = g.get_nodes_by_type(NodeType.VPC_ENDPOINT)
        assert len(endpoints) == 1
        assert endpoints[0] == "vpce-001"
        node = g.get_node("vpce-001")
        assert node["status"] == NodeStatus.HEALTHY
        assert node["label"] == "s3"

    def test_vpc_endpoint_hosted_in_subnet(self):
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [
                {"subnet_id": "sub-1", "name": "s1", "type": "private", "available_ips": 50}
            ],
            "route_tables": [], "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "blackhole_routes": [],
            "security_group_dependency_map": {},
            "vpc_endpoints": [
                {"endpoint_id": "vpce-001", "service_name": "com.amazonaws.us-east-1.s3",
                 "state": "available", "subnet_ids": ["sub-1"]},
            ],
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        neighbors = g.get_neighbors("vpce-001", EdgeType.HOSTED_IN)
        assert "sub-1" in neighbors

    def test_vpc_endpoint_pending_status(self):
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [],
            "route_tables": [], "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "blackhole_routes": [],
            "security_group_dependency_map": {},
            "vpc_endpoints": [
                {"endpoint_id": "vpce-002", "service_name": "com.amazonaws.us-east-1.dynamodb",
                 "state": "pending", "subnet_ids": []},
            ],
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        node = g.get_node("vpce-002")
        assert node["status"] == NodeStatus.WARNING


# ── Security Group engine tests ─────────────────────────────────────


class TestEngineSecurityGroups:
    def test_sg_nodes_created(self):
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [], "route_tables": [],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [], "blackhole_routes": [],
            "security_group_dependency_map": {
                "sg-001": {"name": "web-sg", "references": ["sg-002"]},
                "sg-002": {"name": "db-sg", "references": []},
            },
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        sgs = g.get_nodes_by_type(NodeType.SECURITY_GROUP)
        assert len(sgs) == 2

    def test_sg_references_edges(self):
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [], "route_tables": [],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [], "blackhole_routes": [],
            "security_group_dependency_map": {
                "sg-001": {"name": "web-sg", "references": ["sg-002"]},
                "sg-002": {"name": "db-sg", "references": []},
            },
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        neighbors = g.get_neighbors("sg-001", EdgeType.REFERENCES)
        assert "sg-002" in neighbors


# ── VPC Peering engine tests ────────────────────────────────────────


class TestEnginePeering:
    def test_peering_node_created(self):
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [], "route_tables": [],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_endpoints": [], "blackhole_routes": [],
            "security_group_dependency_map": {},
            "vpc_peering_connections": [
                {"pcx_id": "pcx-001", "status": "active",
                 "requester_vpc": "vpc-001", "accepter_vpc": "vpc-002"},
            ],
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        peerings = g.get_nodes_by_type(NodeType.PEERING)
        assert len(peerings) == 1
        node = g.get_node("pcx-001")
        assert node["status"] == NodeStatus.HEALTHY

    def test_peering_peers_with_edge(self):
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [], "route_tables": [],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_endpoints": [], "blackhole_routes": [],
            "security_group_dependency_map": {},
            "vpc_peering_connections": [
                {"pcx_id": "pcx-001", "status": "active",
                 "requester_vpc": "vpc-001", "accepter_vpc": "vpc-002"},
            ],
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        neighbors = g.get_neighbors("pcx-001", EdgeType.PEERS_WITH)
        assert "vpc-001" in neighbors


# ── Region with peering tests ───────────────────────────────────────


class TestRegionPeering:
    def test_region_peering_both_local(self):
        """Both VPCs in region → direct edge."""
        topo = {
            "region": "us-east-1",
            "vpcs": [
                {"vpc_id": "vpc-001", "name": "v1"},
                {"vpc_id": "vpc-002", "name": "v2"},
            ],
            "transit_gateways": [],
            "peering_connections": [
                {"pcx_id": "pcx-001", "requester_vpc": "vpc-001",
                 "accepter_vpc": "vpc-002", "status": "active"},
            ],
        }
        g = InfraGraph().build_from_region_topology(topo)
        neighbors = g.get_neighbors("vpc-001", EdgeType.PEERS_WITH)
        assert "vpc-002" in neighbors

    def test_region_peering_one_external(self):
        """One VPC external → creates external node."""
        topo = {
            "region": "us-east-1",
            "vpcs": [{"vpc_id": "vpc-001", "name": "v1"}],
            "transit_gateways": [],
            "peering_connections": [
                {"pcx_id": "pcx-001", "requester_vpc": "vpc-001",
                 "accepter_vpc": "vpc-ext", "status": "active",
                 "accepter_cidr": "10.99.0.0/16"},
            ],
        }
        g = InfraGraph().build_from_region_topology(topo)
        ext_node = g.get_node("vpc-ext")
        assert ext_node is not None
        assert "external" in ext_node["label"]
        assert ext_node["status"] == NodeStatus.UNKNOWN


# ── Advanced anomaly detection tests ────────────────────────────────


class TestAnomaliesAdvanced:
    def test_routing_cycle_detected(self):
        """Routing cycle should be caught."""
        g = InfraGraph()
        g._graph.add_node("rtb-a", node_type=NodeType.ROUTE_TABLE, label="rtb-a",
                          status=NodeStatus.HEALTHY, raw={})
        g._graph.add_node("rtb-b", node_type=NodeType.ROUTE_TABLE, label="rtb-b",
                          status=NodeStatus.HEALTHY, raw={})
        g._graph.add_edge("rtb-a", "rtb-b", edge_type=EdgeType.ROUTES_TO, label="10.0.0.0/8", state="active")
        g._graph.add_edge("rtb-b", "rtb-a", edge_type=EdgeType.ROUTES_TO, label="10.1.0.0/8", state="active")
        result = detect_anomalies(g)
        cycles = [a for a in result.anomalies if a.type == "routing_cycle"]
        assert len(cycles) >= 1
        assert cycles[0].severity == "critical"

    def test_unreachable_public_subnet_detected(self):
        """Public subnet with no IGW path → anomaly."""
        g = InfraGraph()
        # Add an IGW that is NOT connected to the public subnet
        g._graph.add_node("igw-001", node_type=NodeType.INTERNET_GATEWAY,
                          label="igw", status=NodeStatus.HEALTHY, raw={})
        g._graph.add_node("sub-pub", node_type=NodeType.SUBNET,
                          label="pub-sub", status=NodeStatus.HEALTHY,
                          raw={"type": "public"})
        # No edge between them — subnet is unreachable
        result = detect_anomalies(g)
        unreachable = [a for a in result.anomalies if a.type == "unreachable_subnet"]
        assert len(unreachable) >= 1
        assert unreachable[0].severity == "high"

    def test_error_status_nodes_detected(self):
        """Nodes with ERROR status → unhealthy_node anomaly."""
        g = InfraGraph()
        g._graph.add_node("nat-bad", node_type=NodeType.NAT_GATEWAY,
                          label="broken-nat", status=NodeStatus.ERROR,
                          resource_type="NAT Gateway", raw={})
        result = detect_anomalies(g)
        unhealthy = [a for a in result.anomalies if a.type == "unhealthy_node"]
        assert len(unhealthy) >= 1
        assert unhealthy[0].node_id == "nat-bad"

    def test_anomaly_summary_format(self):
        """Summary string should list anomaly types."""
        g = InfraGraph()
        g._graph.add_node("orphan", node_type=NodeType.SUBNET, label="o",
                          status=NodeStatus.UNKNOWN, raw={})
        result = detect_anomalies(g)
        assert "orphan_node" in result.summary


# ── Serializer edge case tests ──────────────────────────────────────


class TestSerializerEdgeCases:
    def test_region_tgw_node_details(self):
        """Region view TGW should have tgwHubNode type and extra data."""
        topo = {
            "region": "us-east-1",
            "vpcs": [{"vpc_id": "vpc-001", "name": "v1"}],
            "transit_gateways": [{
                "transit_gateway_id": "tgw-001", "name": "main-tgw",
                "state": "available",
                "attachments": [{"resource_id": "vpc-001", "resource_type": "vpc", "state": "available"}],
            }],
            "peering_connections": [],
        }
        g = InfraGraph().build_from_region_topology(topo)
        result = to_reactflow(g, view="region")
        tgw_nodes = [n for n in result.nodes if n.type == "tgwHubNode"]
        assert len(tgw_nodes) == 1
        assert tgw_nodes[0].data.get("tgwId") == "tgw-001"
        assert tgw_nodes[0].data.get("state") == "available"

    def test_edge_style_hosted_in_is_dashed(self):
        """HOSTED_IN edges should have 'dashed' style."""
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [
                {"subnet_id": "sub-1", "name": "s1", "type": "private", "available_ips": 50}
            ],
            "route_tables": [], "nat_gateways": [],
            "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [
                {"endpoint_id": "vpce-001", "service_name": "com.amazonaws.s3",
                 "state": "available", "subnet_ids": ["sub-1"]}
            ], "blackhole_routes": [], "security_group_dependency_map": {},
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        result = to_reactflow(g, view="vpc")
        hosted_edges = [e for e in result.edges if e.data.get("edgeType") == EdgeType.HOSTED_IN]
        assert len(hosted_edges) >= 1
        assert hosted_edges[0].data["style"] == "dashed"

    def test_edge_style_references_is_dotted(self):
        """REFERENCES edges should have 'dotted' style."""
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [], "route_tables": [],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [], "blackhole_routes": [],
            "security_group_dependency_map": {
                "sg-001": {"name": "web", "references": ["sg-002"]},
                "sg-002": {"name": "db", "references": []},
            },
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        result = to_reactflow(g, view="vpc")
        ref_edges = [e for e in result.edges if e.data.get("edgeType") == EdgeType.REFERENCES]
        assert len(ref_edges) >= 1
        assert ref_edges[0].data["style"] == "dotted"

    def test_contains_edges_filtered_in_vpc_view(self):
        """CONTAINS edges should NOT appear in vpc view."""
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [], "subnets": [
                {"subnet_id": "sub-1", "name": "s1", "type": "public", "available_ips": 50}
            ],
            "route_tables": [], "nat_gateways": [],
            "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [],
            "blackhole_routes": [], "security_group_dependency_map": {},
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        result = to_reactflow(g, view="vpc")
        contains_edges = [e for e in result.edges if e.data.get("edgeType") == EdgeType.CONTAINS]
        assert len(contains_edges) == 0

    def test_blackhole_edge_style(self):
        """Blackhole edges should have 'blackhole' style."""
        topo = {
            "vpc_id": "vpc-001", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
            "internet_gateways": [
                {"igw_id": "igw-001", "name": "igw", "attachments": [{"state": "attached"}]}
            ],
            "subnets": [
                {"subnet_id": "sub-1", "name": "s1", "type": "public", "available_ips": 50}
            ],
            "route_tables": [{
                "route_table_id": "rtb-1", "associated_subnets": ["sub-1"],
                "routes": [
                    {"destination": "10.99.0.0/16", "target": "igw-001", "state": "blackhole"},
                ],
            }],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [],
            "blackhole_routes": [{"route_table_id": "rtb-1", "destination": "10.99.0.0/16"}],
            "security_group_dependency_map": {},
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        result = to_reactflow(g, view="vpc")
        bh_edges = [e for e in result.edges if e.data.get("style") == "blackhole"]
        assert len(bh_edges) >= 1


# ── Pydantic schema validation tests ────────────────────────────────


class TestPydanticSchemas:
    def test_vpc_topology_schema(self):
        from src.aci.topology.types import VpcTopology
        t = VpcTopology(vpc_id="vpc-001", vpc_cidr="10.0.0.0/16")
        assert t.vpc_id == "vpc-001"
        assert t.subnets == []
        assert t.security_group_dependency_map == {}

    def test_region_topology_schema(self):
        from src.aci.topology.types import RegionTopology
        t = RegionTopology(region="us-east-1")
        assert t.region == "us-east-1"
        assert t.vpcs == []
        assert t.transit_gateways == []




# ── Part 2: API, tools, collector ────────────────────────────────────
# Fills gaps: api.py 42%→90%+, tools.py 0%→80%+, collector.py 63%→80%+

import json
import unittest.mock as mock

from fastapi.testclient import TestClient


# ── Shared mock fixtures ────────────────────────────────────────────


def _minimal_vpc_topo():
    return {
        "vpc_id": "vpc-t", "vpc_cidr": "10.0.0.0/16", "vpc_name": "test",
        "internet_gateways": [
            {"igw_id": "igw-t", "name": "igw", "attachments": [{"state": "attached"}]}
        ],
        "subnets": [
            {"subnet_id": "sub-1", "name": "pub-sub", "type": "public", "available_ips": 100},
            {"subnet_id": "sub-2", "name": "priv-sub", "type": "private", "available_ips": 100},
        ],
        "route_tables": [
            {"route_table_id": "rtb-1", "associated_subnets": ["sub-1"],
             "routes": [{"destination": "0.0.0.0/0", "target": "igw-t", "state": "active"}]},
            {"route_table_id": "rtb-2", "associated_subnets": ["sub-2"],
             "routes": [{"destination": "10.0.0.0/16", "target": "local", "state": "active"}]},
        ],
        "nat_gateways": [],
        "transit_gateway_attachments": [],
        "vpc_peering_connections": [],
        "vpc_endpoints": [],
        "security_group_dependency_map": {},
        "blackhole_routes": [],
    }


def _minimal_region_topo():
    return {
        "region": "us-east-1",
        "vpcs": [
            {"vpc_id": "vpc-001", "name": "v1", "state": "available"},
            {"vpc_id": "vpc-002", "name": "v2", "state": "available"},
        ],
        "transit_gateways": [],
        "peering_connections": [],
    }


# ── API endpoint tests ──────────────────────────────────────────────


class TestTopologyAPIEndpoints:
    """Test all 7 FastAPI endpoints with mocked collector."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        from fastapi import FastAPI
        from src.aci.topology.api import router
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_get_vpc_graph(self):
        with mock.patch("src.aci.topology.api.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            resp = self.client.get("/api/topology/vpc/vpc-t?region=us-east-1")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert data["metadata"]["node_count"] > 0

    def test_get_region_graph(self):
        with mock.patch("src.aci.topology.api.collect_region_topology", return_value=_minimal_region_topo()):
            resp = self.client.get("/api/topology/region?region=us-east-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["node_count"] >= 2

    def test_get_reachability(self):
        with mock.patch("src.aci.topology.api.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            resp = self.client.get("/api/topology/vpc/vpc-t/reachability/sub-1?region=us-east-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["subnet_id"] == "sub-1"
        assert data["can_reach_internet"] is True

    def test_get_reachability_unreachable(self):
        with mock.patch("src.aci.topology.api.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            resp = self.client.get("/api/topology/vpc/vpc-t/reachability/sub-2?region=us-east-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["subnet_id"] == "sub-2"

    def test_get_impact(self):
        with mock.patch("src.aci.topology.api.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            resp = self.client.get("/api/topology/vpc/vpc-t/impact/igw-t?region=us-east-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed_node_id"] == "igw-t"

    def test_get_path(self):
        with mock.patch("src.aci.topology.api.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            resp = self.client.get("/api/topology/vpc/vpc-t/path?source=sub-1&target=igw-t&region=us-east-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "sub-1"
        assert data["target"] == "igw-t"
        assert data["paths_found"] > 0

    def test_get_anomalies(self):
        with mock.patch("src.aci.topology.api.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            resp = self.client.get("/api/topology/vpc/vpc-t/anomalies?region=us-east-1")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_anomalies" in data
        assert "anomalies" in data

    def test_get_segments(self):
        with mock.patch("src.aci.topology.api.collect_region_topology", return_value=_minimal_region_topo()):
            resp = self.client.get("/api/topology/region/segments?region=us-east-1")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_segments" in data
        # 2 VPCs with no TGW → 2 segments
        assert data["total_segments"] == 2

    def test_vpc_graph_error_handling(self):
        with mock.patch("src.aci.topology.api.collect_vpc_topology", side_effect=Exception("AWS error")):
            resp = self.client.get("/api/topology/vpc/vpc-bad?region=us-east-1")
        assert resp.status_code == 500
        assert "error" in resp.json()


# ── Strands tools tests ─────────────────────────────────────────────


class TestTopologyTools:
    """Test all 5 Strands @tool functions."""

    def test_query_reachability(self):
        from src.aci.topology.tools import query_reachability
        with mock.patch("src.aci.topology.tools.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            result = query_reachability(region="us-east-1", vpc_id="vpc-t", subnet_id="sub-1")
        data = json.loads(result)
        assert data["can_reach_internet"] is True
        assert "igw-t" in data["path"]

    def test_query_reachability_error(self):
        from src.aci.topology.tools import query_reachability
        with mock.patch("src.aci.topology.tools.collect_vpc_topology", side_effect=Exception("fail")):
            result = query_reachability(region="us-east-1", vpc_id="vpc-t", subnet_id="sub-1")
        data = json.loads(result)
        assert "error" in data

    def test_query_impact_radius(self):
        from src.aci.topology.tools import query_impact_radius
        with mock.patch("src.aci.topology.tools.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            result = query_impact_radius(region="us-east-1", vpc_id="vpc-t", resource_id="igw-t")
        data = json.loads(result)
        assert data["failed_node_id"] == "igw-t"
        assert "affected_nodes" in data

    def test_find_network_path(self):
        from src.aci.topology.tools import find_network_path
        with mock.patch("src.aci.topology.tools.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            result = find_network_path(region="us-east-1", vpc_id="vpc-t", source="sub-1", target="igw-t")
        data = json.loads(result)
        assert data["paths_found"] > 0

    def test_detect_network_anomalies(self):
        from src.aci.topology.tools import detect_network_anomalies
        with mock.patch("src.aci.topology.tools.collect_vpc_topology", return_value=_minimal_vpc_topo()):
            result = detect_network_anomalies(region="us-east-1", vpc_id="vpc-t")
        data = json.loads(result)
        assert "total_anomalies" in data

    def test_analyze_network_segments(self):
        from src.aci.topology.tools import analyze_network_segments
        with mock.patch("src.aci.topology.tools.collect_region_topology", return_value=_minimal_region_topo()):
            result = analyze_network_segments(region="us-east-1")
        data = json.loads(result)
        assert "total_segments" in data
        assert "graph_summary" in data


# ── Collector boto3 tests ────────────────────────────────────────────


class TestCollectorBoto3:
    """Test collector.py with mocked boto3 client."""

    def _make_mock_ec2(self):
        m = mock.MagicMock()
        m.describe_vpcs.return_value = {"Vpcs": [{
            "VpcId": "vpc-c1", "CidrBlock": "10.0.0.0/16",
            "Tags": [{"Key": "Name", "Value": "coll-vpc"}],
        }]}
        m.describe_internet_gateways.return_value = {"InternetGateways": [{
            "InternetGatewayId": "igw-c1",
            "Attachments": [{"VpcId": "vpc-c1", "State": "attached"}],
            "Tags": [{"Key": "Name", "Value": "coll-igw"}],
        }]}
        m.describe_subnets.return_value = {"Subnets": [{
            "SubnetId": "sub-c1", "CidrBlock": "10.0.1.0/24",
            "AvailabilityZone": "us-east-1a", "AvailableIpAddressCount": 200,
            "MapPublicIpOnLaunch": True,
            "Tags": [{"Key": "Name", "Value": "coll-sub"}],
        }]}
        m.describe_route_tables.return_value = {"RouteTables": [{
            "RouteTableId": "rtb-c1",
            "Associations": [{"SubnetId": "sub-c1"}],
            "Routes": [
                {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active"},
                {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-c1", "State": "active"},
            ],
            "Tags": [{"Key": "Name", "Value": "coll-rt"}],
        }]}
        m.describe_nat_gateways.return_value = {"NatGateways": [{
            "NatGatewayId": "nat-c1", "SubnetId": "sub-c1",
            "State": "available",
            "Tags": [{"Key": "Name", "Value": "coll-nat"}],
        }]}
        m.describe_transit_gateway_attachments.return_value = {"TransitGatewayAttachments": [{
            "TransitGatewayAttachmentId": "tgw-att-c1",
            "TransitGatewayId": "tgw-c1", "State": "available",
        }]}
        m.describe_vpc_peering_connections.return_value = {"VpcPeeringConnections": [{
            "VpcPeeringConnectionId": "pcx-c1",
            "RequesterVpcInfo": {"VpcId": "vpc-c1"},
            "AccepterVpcInfo": {"VpcId": "vpc-c2"},
            "Status": {"Code": "active"},
        }]}
        m.describe_vpc_endpoints.return_value = {"VpcEndpoints": [{
            "VpcEndpointId": "vpce-c1",
            "ServiceName": "com.amazonaws.us-east-1.s3",
            "State": "available", "SubnetIds": ["sub-c1"],
        }]}
        m.describe_security_groups.return_value = {"SecurityGroups": [
            {"GroupId": "sg-c1", "GroupName": "web",
             "IpPermissions": [{"UserIdGroupPairs": [{"GroupId": "sg-c2"}]}],
             "IpPermissionsEgress": []},
            {"GroupId": "sg-c2", "GroupName": "db",
             "IpPermissions": [], "IpPermissionsEgress": []},
        ]}
        m.describe_transit_gateways.return_value = {"TransitGateways": [{
            "TransitGatewayId": "tgw-c1", "State": "available",
            "Tags": [{"Key": "Name", "Value": "coll-tgw"}],
        }]}
        return m

    def test_collect_vpc_topology_full(self):
        from src.aci.topology.collector import collect_vpc_topology
        with mock.patch("boto3.client", return_value=self._make_mock_ec2()):
            topo = collect_vpc_topology("us-east-1", "vpc-c1")
        assert topo["vpc_id"] == "vpc-c1"
        assert topo["vpc_name"] == "coll-vpc"
        assert len(topo["internet_gateways"]) == 1
        assert len(topo["subnets"]) == 1
        assert len(topo["route_tables"]) == 1
        assert len(topo["nat_gateways"]) == 1
        assert len(topo["transit_gateway_attachments"]) == 1
        assert len(topo["vpc_peering_connections"]) == 1
        assert len(topo["vpc_endpoints"]) == 1
        assert "sg-c1" in topo["security_group_dependency_map"]

    def test_collect_vpc_nat_gateway_fields(self):
        from src.aci.topology.collector import collect_vpc_topology
        with mock.patch("boto3.client", return_value=self._make_mock_ec2()):
            topo = collect_vpc_topology("us-east-1", "vpc-c1")
        nat = topo["nat_gateways"][0]
        assert nat["nat_gateway_id"] == "nat-c1"
        assert nat["subnet_id"] == "sub-c1"
        assert nat["state"] == "available"

    def test_collect_vpc_sg_references(self):
        from src.aci.topology.collector import collect_vpc_topology
        with mock.patch("boto3.client", return_value=self._make_mock_ec2()):
            topo = collect_vpc_topology("us-east-1", "vpc-c1")
        sg_map = topo["security_group_dependency_map"]
        assert "sg-c2" in sg_map["sg-c1"]["references"]
        assert sg_map["sg-c2"]["references"] == []

    def test_collect_vpc_blackhole_route(self):
        from src.aci.topology.collector import collect_vpc_topology
        m = self._make_mock_ec2()
        m.describe_route_tables.return_value = {"RouteTables": [{
            "RouteTableId": "rtb-bh",
            "Associations": [],
            "Routes": [
                {"DestinationCidrBlock": "10.99.0.0/16", "GatewayId": "igw-gone", "State": "blackhole"},
            ],
            "Tags": [],
        }]}
        with mock.patch("boto3.client", return_value=m):
            topo = collect_vpc_topology("us-east-1", "vpc-c1")
        assert len(topo["blackhole_routes"]) == 1
        assert topo["blackhole_routes"][0]["destination"] == "10.99.0.0/16"

    def test_collect_region_topology(self):
        from src.aci.topology.collector import collect_region_topology
        m = self._make_mock_ec2()
        with mock.patch("boto3.client", return_value=m):
            topo = collect_region_topology("us-east-1")
        assert topo["region"] == "us-east-1"
        assert len(topo["vpcs"]) == 1
        assert len(topo["transit_gateways"]) == 1
        assert len(topo["peering_connections"]) == 1

    def test_collect_vpc_handles_api_errors(self):
        """Collector should handle individual API failures gracefully."""
        from src.aci.topology.collector import collect_vpc_topology
        m = mock.MagicMock()
        m.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-err", "CidrBlock": "10.0.0.0/16", "Tags": []}]}
        m.describe_internet_gateways.side_effect = Exception("IGW API error")
        m.describe_subnets.side_effect = Exception("Subnet API error")
        m.describe_route_tables.side_effect = Exception("RT API error")
        m.describe_nat_gateways.side_effect = Exception("NAT API error")
        m.describe_transit_gateway_attachments.side_effect = Exception("TGW API error")
        m.describe_vpc_peering_connections.side_effect = Exception("PCX API error")
        m.describe_vpc_endpoints.side_effect = Exception("VPCE API error")
        m.describe_security_groups.side_effect = Exception("SG API error")
        with mock.patch("boto3.client", return_value=m):
            topo = collect_vpc_topology("us-east-1", "vpc-err")
        # Should still return a valid dict with empty lists
        assert topo["vpc_id"] == "vpc-err"
        assert topo["internet_gateways"] == []
        assert topo["subnets"] == []
        assert topo["nat_gateways"] == []


