"""Gap-filling tests for topology module — covers collector, API, tools, status derivation.

Written by Architect to unblock Developer + Tester who hit tool validation issues.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.aci.topology.engine import InfraGraph
from src.aci.topology.types import (
    EdgeType, NodeStatus, NodeType,
    VpcTopology, RegionTopology,
    GraphNode, GraphEdge, GraphMetadata, SerializedGraph,
)
from src.aci.topology.algorithms import (
    can_reach_internet, detect_anomalies, find_traffic_path,
    impact_analysis, network_segments,
)
from src.aci.topology.serializers import to_agent_summary, to_reactflow


# ── Pydantic Schema Validation ───────────────────────────────────────


class TestPydanticSchemas:
    """VpcTopology / RegionTopology contract validation."""

    def test_vpc_topology_minimal(self):
        t = VpcTopology(vpc_id="vpc-1", vpc_cidr="10.0.0.0/16")
        assert t.vpc_id == "vpc-1"
        assert t.subnets == []
        assert t.security_group_dependency_map == {}

    def test_vpc_topology_full(self):
        t = VpcTopology(
            vpc_id="vpc-1", vpc_cidr="10.0.0.0/16", vpc_name="test",
            region="us-east-1",
            internet_gateways=[{"igw_id": "igw-1"}],
            subnets=[{"subnet_id": "s-1"}],
            nat_gateways=[{"nat_gateway_id": "nat-1"}],
        )
        assert len(t.internet_gateways) == 1
        assert len(t.nat_gateways) == 1

    def test_region_topology_minimal(self):
        t = RegionTopology(region="us-east-1")
        assert t.vpcs == []
        assert t.transit_gateways == []

    def test_region_topology_full(self):
        t = RegionTopology(
            region="us-east-1",
            vpcs=[{"vpc_id": "vpc-1"}],
            transit_gateways=[{"transit_gateway_id": "tgw-1"}],
            peering_connections=[{"pcx_id": "pcx-1"}],
        )
        assert len(t.vpcs) == 1

    def test_serialized_graph_model(self):
        g = SerializedGraph(
            nodes=[GraphNode(id="n1", type="vpcNode")],
            edges=[GraphEdge(id="e1", source="n1", target="n2")],
            metadata=GraphMetadata(node_count=1, edge_count=1),
        )
        assert g.metadata.node_count == 1


# ── Status Derivation Branch Coverage ────────────────────────────────


class TestDeriveStatus:
    """Full branch coverage for all 6 _derive_*_status() helpers."""

    # IGW
    def test_igw_attached(self):
        assert InfraGraph._derive_igw_status([{"state": "attached"}]) == NodeStatus.HEALTHY

    def test_igw_detaching(self):
        assert InfraGraph._derive_igw_status([{"state": "detaching"}]) == NodeStatus.WARNING

    def test_igw_no_attachments(self):
        assert InfraGraph._derive_igw_status([]) == NodeStatus.ERROR

    def test_igw_other_state(self):
        assert InfraGraph._derive_igw_status([{"state": "detached"}]) == NodeStatus.ERROR

    # Subnet
    def test_subnet_healthy(self):
        assert InfraGraph._derive_subnet_status({"available_ips": 100}) == NodeStatus.HEALTHY

    def test_subnet_warning(self):
        assert InfraGraph._derive_subnet_status({"available_ips": 7}) == NodeStatus.WARNING

    def test_subnet_error(self):
        assert InfraGraph._derive_subnet_status({"available_ips": 2}) == NodeStatus.ERROR

    def test_subnet_unknown(self):
        assert InfraGraph._derive_subnet_status({}) == NodeStatus.UNKNOWN

    # NAT
    def test_nat_available(self):
        assert InfraGraph._derive_nat_status({"state": "available"}) == NodeStatus.HEALTHY

    def test_nat_pending(self):
        assert InfraGraph._derive_nat_status({"state": "pending"}) == NodeStatus.WARNING

    def test_nat_failed(self):
        assert InfraGraph._derive_nat_status({"state": "failed"}) == NodeStatus.ERROR

    def test_nat_deleted(self):
        assert InfraGraph._derive_nat_status({"state": "deleted"}) == NodeStatus.ERROR

    def test_nat_deleting(self):
        assert InfraGraph._derive_nat_status({"state": "deleting"}) == NodeStatus.ERROR

    def test_nat_unknown(self):
        assert InfraGraph._derive_nat_status({"state": "weird"}) == NodeStatus.UNKNOWN

    # TGW
    def test_tgw_available(self):
        assert InfraGraph._derive_tgw_status({"state": "available"}) == NodeStatus.HEALTHY

    def test_tgw_modifying(self):
        assert InfraGraph._derive_tgw_status({"state": "modifying"}) == NodeStatus.WARNING

    def test_tgw_pending(self):
        assert InfraGraph._derive_tgw_status({"state": "pendingAcceptance"}) == NodeStatus.WARNING

    def test_tgw_failing(self):
        assert InfraGraph._derive_tgw_status({"state": "failing"}) == NodeStatus.ERROR

    def test_tgw_unknown(self):
        assert InfraGraph._derive_tgw_status({"state": "other"}) == NodeStatus.UNKNOWN

    # Peering
    def test_peering_active(self):
        assert InfraGraph._derive_peering_status({"status": "active"}) == NodeStatus.HEALTHY

    def test_peering_pending(self):
        assert InfraGraph._derive_peering_status({"status": "pending-acceptance"}) == NodeStatus.WARNING

    def test_peering_provisioning(self):
        assert InfraGraph._derive_peering_status({"status": "provisioning"}) == NodeStatus.WARNING

    def test_peering_failed(self):
        assert InfraGraph._derive_peering_status({"status": "failed"}) == NodeStatus.ERROR

    def test_peering_expired(self):
        assert InfraGraph._derive_peering_status({"status": "expired"}) == NodeStatus.ERROR

    def test_peering_rejected(self):
        assert InfraGraph._derive_peering_status({"status": "rejected"}) == NodeStatus.ERROR

    def test_peering_unknown(self):
        assert InfraGraph._derive_peering_status({"status": "other"}) == NodeStatus.UNKNOWN

    # Endpoint
    def test_endpoint_available(self):
        assert InfraGraph._derive_endpoint_status({"state": "available"}) == NodeStatus.HEALTHY

    def test_endpoint_pending(self):
        assert InfraGraph._derive_endpoint_status({"state": "pending"}) == NodeStatus.WARNING

    def test_endpoint_pending_acceptance(self):
        assert InfraGraph._derive_endpoint_status({"state": "pendingAcceptance"}) == NodeStatus.WARNING

    def test_endpoint_failed(self):
        assert InfraGraph._derive_endpoint_status({"state": "failed"}) == NodeStatus.ERROR

    def test_endpoint_rejected(self):
        assert InfraGraph._derive_endpoint_status({"state": "rejected"}) == NodeStatus.ERROR

    def test_endpoint_deleted(self):
        assert InfraGraph._derive_endpoint_status({"state": "deleted"}) == NodeStatus.ERROR

    def test_endpoint_unknown(self):
        assert InfraGraph._derive_endpoint_status({"state": "other"}) == NodeStatus.UNKNOWN


# ── Engine: VPC Endpoints, SG deps, Peering ──────────────────────────


class TestEngineAdvanced:
    """Cover VPC endpoints, security group dependencies, peering in engine."""

    def test_vpc_endpoints_in_graph(self):
        topo = {
            "vpc_id": "vpc-1", "vpc_cidr": "10.0.0.0/16", "vpc_name": "t",
            "internet_gateways": [], "subnets": [
                {"subnet_id": "s-1", "name": "s1", "cidr": "10.0.1.0/24",
                 "az": "us-east-1a", "type": "private", "available_ips": 200}
            ],
            "route_tables": [], "nat_gateways": [],
            "transit_gateway_attachments": [], "vpc_peering_connections": [],
            "vpc_endpoints": [
                {"endpoint_id": "vpce-1", "service_name": "com.amazonaws.us-east-1.s3",
                 "state": "available", "subnet_ids": ["s-1"]},
            ],
            "security_group_dependency_map": {}, "blackhole_routes": [],
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        ep = g.get_node("vpce-1")
        assert ep is not None
        assert ep["node_type"] == NodeType.VPC_ENDPOINT
        assert ep["label"] == "s3"
        assert ep["status"] == NodeStatus.HEALTHY
        # HOSTED_IN edge to subnet
        neighbors = g.get_neighbors("vpce-1", EdgeType.HOSTED_IN)
        assert "s-1" in neighbors

    def test_security_group_dependencies(self):
        topo = {
            "vpc_id": "vpc-1", "vpc_cidr": "10.0.0.0/16", "vpc_name": "t",
            "internet_gateways": [], "subnets": [], "route_tables": [],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [],
            "security_group_dependency_map": {
                "sg-1": {"name": "web", "references": ["sg-2"]},
                "sg-2": {"name": "db", "references": []},
            },
            "blackhole_routes": [],
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        sg1 = g.get_node("sg-1")
        assert sg1 is not None
        assert sg1["node_type"] == NodeType.SECURITY_GROUP
        # sg-1 references sg-2
        neighbors = g.get_neighbors("sg-1", EdgeType.REFERENCES)
        assert "sg-2" in neighbors

    def test_vpc_peering_in_graph(self):
        topo = {
            "vpc_id": "vpc-1", "vpc_cidr": "10.0.0.0/16", "vpc_name": "t",
            "internet_gateways": [], "subnets": [], "route_tables": [],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [
                {"pcx_id": "pcx-1", "requester_vpc": "vpc-1",
                 "accepter_vpc": "vpc-2", "status": "active"},
            ],
            "vpc_endpoints": [], "security_group_dependency_map": {},
            "blackhole_routes": [],
        }
        g = InfraGraph().build_from_vpc_topology(topo)
        pcx = g.get_node("pcx-1")
        assert pcx is not None
        assert pcx["node_type"] == NodeType.PEERING
        assert pcx["status"] == NodeStatus.HEALTHY

    def test_region_peering_both_local(self):
        """Both VPCs in region → direct edge."""
        topo = {
            "region": "us-east-1",
            "vpcs": [
                {"vpc_id": "vpc-1", "name": "v1", "cidr": "10.0.0.0/16", "state": "available"},
                {"vpc_id": "vpc-2", "name": "v2", "cidr": "10.1.0.0/16", "state": "available"},
            ],
            "transit_gateways": [],
            "peering_connections": [
                {"pcx_id": "pcx-1", "requester_vpc": "vpc-1",
                 "accepter_vpc": "vpc-2", "status": "active"},
            ],
        }
        g = InfraGraph().build_from_region_topology(topo)
        assert g.graph.has_edge("vpc-1", "vpc-2")

    def test_region_peering_one_external(self):
        """One VPC external → synthetic node created."""
        topo = {
            "region": "us-east-1",
            "vpcs": [{"vpc_id": "vpc-1", "name": "v1", "cidr": "10.0.0.0/16", "state": "available"}],
            "transit_gateways": [],
            "peering_connections": [
                {"pcx_id": "pcx-1", "requester_vpc": "vpc-1",
                 "accepter_vpc": "vpc-ext", "status": "active"},
            ],
        }
        g = InfraGraph().build_from_region_topology(topo)
        ext = g.get_node("vpc-ext")
        assert ext is not None
        assert "(external)" in ext["label"]

    def test_node_count_edge_count_properties(self):
        g = InfraGraph()
        assert g.node_count == 0
        assert g.edge_count == 0

    def test_get_node_missing(self):
        g = InfraGraph()
        assert g.get_node("nope") is None

    def test_get_neighbors_missing_node(self):
        g = InfraGraph()
        assert g.get_neighbors("nope") == []


# ── Collector boto3 mock tests ───────────────────────────────────────


def _make_mock_ec2_full():
    """Comprehensive mock EC2 client with all resource types."""
    m = MagicMock()
    m.describe_vpcs.return_value = {"Vpcs": [{
        "VpcId": "vpc-c1", "CidrBlock": "10.0.0.0/16",
        "Tags": [{"Key": "Name", "Value": "collector-vpc"}],
    }]}
    m.describe_internet_gateways.return_value = {"InternetGateways": [{
        "InternetGatewayId": "igw-c1",
        "Attachments": [{"VpcId": "vpc-c1", "State": "attached"}],
        "Tags": [{"Key": "Name", "Value": "c-igw"}],
    }]}
    m.describe_subnets.return_value = {"Subnets": [
        {"SubnetId": "sub-c1", "CidrBlock": "10.0.1.0/24",
         "AvailabilityZone": "us-east-1a", "AvailableIpAddressCount": 200,
         "MapPublicIpOnLaunch": True, "Tags": [{"Key": "Name", "Value": "pub-sub"}]},
        {"SubnetId": "sub-c2", "CidrBlock": "10.0.2.0/24",
         "AvailabilityZone": "us-east-1b", "AvailableIpAddressCount": 200,
         "MapPublicIpOnLaunch": False, "Tags": []},
    ]}
    m.describe_route_tables.return_value = {"RouteTables": [{
        "RouteTableId": "rtb-c1",
        "Associations": [{"SubnetId": "sub-c1"}],
        "Routes": [
            {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active"},
            {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-c1", "State": "active"},
        ],
        "Tags": [{"Key": "Name", "Value": "pub-rt"}],
    }]}
    m.describe_nat_gateways.return_value = {"NatGateways": [{
        "NatGatewayId": "nat-c1", "State": "available", "SubnetId": "sub-c1",
        "Tags": [{"Key": "Name", "Value": "c-nat"}],
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
        "TransitGatewayId": "tgw-c1",
        "State": "available",
        "Tags": [{"Key": "Name", "Value": "c-tgw"}],
    }]}
    return m


class TestCollectorVpc:
    """collector.collect_vpc_topology with full boto3 mocks."""

    def test_collect_vpc_full(self):
        from src.aci.topology.collector import collect_vpc_topology
        mock_ec2 = _make_mock_ec2_full()
        with patch("src.aci.topology.collector.boto3.client", return_value=mock_ec2):
            topo = collect_vpc_topology("us-east-1", "vpc-c1")
        assert topo["vpc_id"] == "vpc-c1"
        assert topo["vpc_name"] == "collector-vpc"
        assert len(topo["internet_gateways"]) == 1
        assert topo["internet_gateways"][0]["igw_id"] == "igw-c1"
        assert len(topo["subnets"]) == 2
        assert topo["subnets"][0]["type"] == "public"
        assert topo["subnets"][1]["type"] == "private"
        assert len(topo["nat_gateways"]) == 1
        assert topo["nat_gateways"][0]["nat_gateway_id"] == "nat-c1"
        assert len(topo["transit_gateway_attachments"]) == 1
        assert len(topo["vpc_peering_connections"]) == 1
        assert topo["vpc_peering_connections"][0]["pcx_id"] == "pcx-c1"
        assert len(topo["vpc_endpoints"]) == 1
        assert "sg-c1" in topo["security_group_dependency_map"]
        sg = topo["security_group_dependency_map"]["sg-c1"]
        assert "sg-c2" in sg["references"]

    def test_collect_vpc_boto3_errors_graceful(self):
        """Each describe_* failure should be caught and return empty list."""
        from src.aci.topology.collector import collect_vpc_topology
        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.side_effect = Exception("boom")
        mock_ec2.describe_internet_gateways.side_effect = Exception("boom")
        mock_ec2.describe_subnets.side_effect = Exception("boom")
        mock_ec2.describe_route_tables.side_effect = Exception("boom")
        mock_ec2.describe_nat_gateways.side_effect = Exception("boom")
        mock_ec2.describe_transit_gateway_attachments.side_effect = Exception("boom")
        mock_ec2.describe_vpc_peering_connections.side_effect = Exception("boom")
        mock_ec2.describe_vpc_endpoints.side_effect = Exception("boom")
        mock_ec2.describe_security_groups.side_effect = Exception("boom")
        with patch("src.aci.topology.collector.boto3.client", return_value=mock_ec2):
            topo = collect_vpc_topology("us-east-1", "vpc-err")
        assert topo["vpc_id"] == "vpc-err"
        assert topo["subnets"] == []
        assert topo["nat_gateways"] == []
        assert topo["vpc_endpoints"] == []

    def test_collect_vpc_blackhole_detection(self):
        """Route with state=blackhole should populate blackhole_routes."""
        from src.aci.topology.collector import collect_vpc_topology
        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-bh", "CidrBlock": "10.0.0.0/16", "Tags": []}]}
        mock_ec2.describe_internet_gateways.return_value = {"InternetGateways": []}
        mock_ec2.describe_subnets.return_value = {"Subnets": []}
        mock_ec2.describe_route_tables.return_value = {"RouteTables": [{
            "RouteTableId": "rtb-bh",
            "Associations": [],
            "Routes": [
                {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-gone", "State": "blackhole"},
            ],
            "Tags": [],
        }]}
        mock_ec2.describe_nat_gateways.return_value = {"NatGateways": []}
        mock_ec2.describe_transit_gateway_attachments.return_value = {"TransitGatewayAttachments": []}
        mock_ec2.describe_vpc_peering_connections.return_value = {"VpcPeeringConnections": []}
        mock_ec2.describe_vpc_endpoints.return_value = {"VpcEndpoints": []}
        mock_ec2.describe_security_groups.return_value = {"SecurityGroups": []}
        with patch("src.aci.topology.collector.boto3.client", return_value=mock_ec2):
            topo = collect_vpc_topology("us-east-1", "vpc-bh")
        assert len(topo["blackhole_routes"]) == 1
        assert topo["blackhole_routes"][0]["route_table_id"] == "rtb-bh"

    def test_collect_vpc_peering_dedup(self):
        """Same peering seen from both requester and accepter should be deduped."""
        from src.aci.topology.collector import collect_vpc_topology
        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-d", "CidrBlock": "10.0.0.0/16", "Tags": []}]}
        mock_ec2.describe_internet_gateways.return_value = {"InternetGateways": []}
        mock_ec2.describe_subnets.return_value = {"Subnets": []}
        mock_ec2.describe_route_tables.return_value = {"RouteTables": []}
        mock_ec2.describe_nat_gateways.return_value = {"NatGateways": []}
        mock_ec2.describe_transit_gateway_attachments.return_value = {"TransitGatewayAttachments": []}
        pcx = {
            "VpcPeeringConnectionId": "pcx-dup",
            "RequesterVpcInfo": {"VpcId": "vpc-d"},
            "AccepterVpcInfo": {"VpcId": "vpc-e"},
            "Status": {"Code": "active"},
        }
        # Same PCX returned from both filters
        mock_ec2.describe_vpc_peering_connections.return_value = {"VpcPeeringConnections": [pcx]}
        mock_ec2.describe_vpc_endpoints.return_value = {"VpcEndpoints": []}
        mock_ec2.describe_security_groups.return_value = {"SecurityGroups": []}
        with patch("src.aci.topology.collector.boto3.client", return_value=mock_ec2):
            topo = collect_vpc_topology("us-east-1", "vpc-d")
        # Should appear only once despite being returned by both describe calls
        assert len(topo["vpc_peering_connections"]) == 1


class TestCollectorRegion:
    """collector.collect_region_topology tests."""

    def test_collect_region_basic(self):
        from src.aci.topology.collector import collect_region_topology
        mock_ec2 = _make_mock_ec2_full()
        with patch("src.aci.topology.collector.boto3.client", return_value=mock_ec2):
            topo = collect_region_topology("us-east-1")
        assert topo["region"] == "us-east-1"
        assert len(topo["vpcs"]) >= 1
        assert len(topo["transit_gateways"]) >= 1
        assert len(topo["peering_connections"]) >= 1

    def test_collect_region_errors_graceful(self):
        from src.aci.topology.collector import collect_region_topology
        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.side_effect = Exception("fail")
        mock_ec2.describe_transit_gateways.side_effect = Exception("fail")
        mock_ec2.describe_vpc_peering_connections.side_effect = Exception("fail")
        with patch("src.aci.topology.collector.boto3.client", return_value=mock_ec2):
            topo = collect_region_topology("us-east-1")
        assert topo["vpcs"] == []
        assert topo["transit_gateways"] == []


class TestCollectorHelpers:
    def test_get_name_tag_found(self):
        from src.aci.topology.collector import _get_name_tag
        assert _get_name_tag({"Tags": [{"Key": "Name", "Value": "hello"}]}) == "hello"

    def test_get_name_tag_missing(self):
        from src.aci.topology.collector import _get_name_tag
        assert _get_name_tag({}) == ""
        assert _get_name_tag({"Tags": [{"Key": "Env", "Value": "prod"}]}) == ""


# ── FastAPI TestClient Endpoint Tests ────────────────────────────────


class TestTopologyAPIEndpoints:
    """Test all 7 API endpoints via FastAPI TestClient with mocked collector."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.aci.topology.api import router

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

        # Standard VPC topo for mocking
        self.vpc_topo = {
            "vpc_id": "vpc-api", "vpc_cidr": "10.0.0.0/16", "vpc_name": "api-vpc",
            "internet_gateways": [
                {"igw_id": "igw-api", "name": "api-igw",
                 "attachments": [{"vpc_id": "vpc-api", "state": "attached"}]}
            ],
            "subnets": [
                {"subnet_id": "sub-api-pub", "name": "pub", "cidr": "10.0.1.0/24",
                 "az": "us-east-1a", "type": "public", "available_ips": 200},
                {"subnet_id": "sub-api-priv", "name": "priv", "cidr": "10.0.2.0/24",
                 "az": "us-east-1a", "type": "private", "available_ips": 200},
            ],
            "route_tables": [
                {"route_table_id": "rtb-api", "name": "pub-rt",
                 "associated_subnets": ["sub-api-pub"],
                 "routes": [
                     {"destination": "10.0.0.0/16", "target": "local", "state": "active"},
                     {"destination": "0.0.0.0/0", "target": "igw-api", "state": "active"},
                 ]},
            ],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [],
            "security_group_dependency_map": {}, "blackhole_routes": [],
        }
        self.region_topo = {
            "region": "us-east-1",
            "vpcs": [
                {"vpc_id": "vpc-r1", "name": "v1", "cidr": "10.0.0.0/16", "state": "available"},
                {"vpc_id": "vpc-r2", "name": "v2", "cidr": "10.1.0.0/16", "state": "available"},
            ],
            "transit_gateways": [
                {"transit_gateway_id": "tgw-r1", "name": "tgw", "state": "available",
                 "attachments": [
                     {"resource_id": "vpc-r1", "resource_type": "vpc", "state": "available"},
                     {"resource_id": "vpc-r2", "resource_type": "vpc", "state": "available"},
                 ]},
            ],
            "peering_connections": [],
        }

    @patch("src.aci.topology.api.collect_vpc_topology")
    def test_get_vpc_graph(self, mock_collect):
        mock_collect.return_value = self.vpc_topo
        r = self.client.get("/api/topology/vpc/vpc-api?region=us-east-1")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data
        assert "edges" in data
        assert data["metadata"]["node_count"] > 0

    @patch("src.aci.topology.api.collect_region_topology")
    def test_get_region_graph(self, mock_collect):
        mock_collect.return_value = self.region_topo
        r = self.client.get("/api/topology/region?region=us-east-1")
        assert r.status_code == 200
        data = r.json()
        assert data["metadata"]["node_count"] >= 2

    @patch("src.aci.topology.api.collect_vpc_topology")
    def test_get_reachability(self, mock_collect):
        mock_collect.return_value = self.vpc_topo
        r = self.client.get("/api/topology/vpc/vpc-api/reachability/sub-api-pub?region=us-east-1")
        assert r.status_code == 200
        data = r.json()
        assert "can_reach_internet" in data

    @patch("src.aci.topology.api.collect_vpc_topology")
    def test_get_impact(self, mock_collect):
        mock_collect.return_value = self.vpc_topo
        r = self.client.get("/api/topology/vpc/vpc-api/impact/igw-api?region=us-east-1")
        assert r.status_code == 200
        data = r.json()
        assert "failed_node_id" in data

    @patch("src.aci.topology.api.collect_vpc_topology")
    def test_get_path(self, mock_collect):
        mock_collect.return_value = self.vpc_topo
        r = self.client.get("/api/topology/vpc/vpc-api/path?source=sub-api-pub&target=igw-api&region=us-east-1")
        assert r.status_code == 200
        data = r.json()
        assert "paths_found" in data

    @patch("src.aci.topology.api.collect_vpc_topology")
    def test_get_anomalies(self, mock_collect):
        mock_collect.return_value = self.vpc_topo
        r = self.client.get("/api/topology/vpc/vpc-api/anomalies?region=us-east-1")
        assert r.status_code == 200
        data = r.json()
        assert "anomalies" in data

    @patch("src.aci.topology.api.collect_region_topology")
    def test_get_segments(self, mock_collect):
        mock_collect.return_value = self.region_topo
        r = self.client.get("/api/topology/region/segments?region=us-east-1")
        assert r.status_code == 200
        data = r.json()
        assert "total_segments" in data


# ── Strands Tools Tests ──────────────────────────────────────────────


class TestStrandsTools:
    """Test all 5 Strands agent tools with mocked collector."""

    @staticmethod
    def _vpc_topo():
        return {
            "vpc_id": "vpc-t", "vpc_cidr": "10.0.0.0/16", "vpc_name": "tool-vpc",
            "internet_gateways": [
                {"igw_id": "igw-t", "name": "t-igw",
                 "attachments": [{"vpc_id": "vpc-t", "state": "attached"}]}
            ],
            "subnets": [
                {"subnet_id": "sub-t1", "name": "pub", "cidr": "10.0.1.0/24",
                 "az": "us-east-1a", "type": "public", "available_ips": 200},
            ],
            "route_tables": [
                {"route_table_id": "rtb-t", "name": "rt",
                 "associated_subnets": ["sub-t1"],
                 "routes": [
                     {"destination": "10.0.0.0/16", "target": "local", "state": "active"},
                     {"destination": "0.0.0.0/0", "target": "igw-t", "state": "active"},
                 ]},
            ],
            "nat_gateways": [], "transit_gateway_attachments": [],
            "vpc_peering_connections": [], "vpc_endpoints": [],
            "security_group_dependency_map": {}, "blackhole_routes": [],
        }

    @patch("src.aci.topology.tools.collect_vpc_topology")
    def test_query_reachability(self, mock_collect):
        from src.aci.topology.tools import query_reachability
        mock_collect.return_value = self._vpc_topo()
        result = query_reachability(region="us-east-1", vpc_id="vpc-t", subnet_id="sub-t1")
        data = json.loads(result)
        assert "can_reach_internet" in data

    @patch("src.aci.topology.tools.collect_vpc_topology")
    def test_query_impact_radius(self, mock_collect):
        from src.aci.topology.tools import query_impact_radius
        mock_collect.return_value = self._vpc_topo()
        result = query_impact_radius(region="us-east-1", vpc_id="vpc-t", resource_id="igw-t")
        data = json.loads(result)
        assert "failed_node_id" in data

    @patch("src.aci.topology.tools.collect_vpc_topology")
    def test_find_network_path(self, mock_collect):
        from src.aci.topology.tools import find_network_path
        mock_collect.return_value = self._vpc_topo()
        result = find_network_path(region="us-east-1", vpc_id="vpc-t",
                                   source="sub-t1", target="igw-t")
        data = json.loads(result)
        assert "paths_found" in data

    @patch("src.aci.topology.tools.collect_vpc_topology")
    def test_detect_network_anomalies(self, mock_collect):
        from src.aci.topology.tools import detect_network_anomalies
        mock_collect.return_value = self._vpc_topo()
        result = detect_network_anomalies(region="us-east-1", vpc_id="vpc-t")
        data = json.loads(result)
        assert "anomalies" in data

    @patch("src.aci.topology.tools.collect_region_topology")
    def test_analyze_network_segments(self, mock_collect):
        from src.aci.topology.tools import analyze_network_segments
        mock_collect.return_value = {
            "region": "us-east-1",
            "vpcs": [{"vpc_id": "vpc-s1", "name": "v1", "cidr": "10.0.0.0/16", "state": "available"}],
            "transit_gateways": [], "peering_connections": [],
        }
        result = analyze_network_segments(region="us-east-1")
        data = json.loads(result)
        assert "total_segments" in data
        assert "graph_summary" in data

    @patch("src.aci.topology.tools.collect_vpc_topology")
    def test_tool_error_returns_json(self, mock_collect):
        """Tools should return JSON error on exception, not raise."""
        from src.aci.topology.tools import query_reachability
        mock_collect.side_effect = Exception("boto3 failure")
        result = query_reachability(region="us-east-1", vpc_id="vpc-x", subnet_id="sub-x")
        data = json.loads(result)
        assert "error" in data
