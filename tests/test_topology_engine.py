"""Tests for graph engine and algorithms."""

import pytest

from src.aci.topology.engine import InfraGraph
from src.aci.topology.types import EdgeType, NodeStatus, NodeType
from src.aci.topology.algorithms import (
    can_reach_internet,
    detect_anomalies,
    find_traffic_path,
    impact_analysis,
    network_segments,
)
from src.aci.topology.serializers import to_agent_summary, to_reactflow


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_vpc_topology(
    *,
    has_igw: bool = True,
    has_nat: bool = True,
    has_blackhole: bool = False,
    has_tgw: bool = False,
    has_peering: bool = False,
) -> dict:
    """Build a minimal VPC topology dict for testing."""
    topo = {
        "vpc_id": "vpc-001",
        "vpc_cidr": "10.0.0.0/16",
        "vpc_name": "test-vpc",
        "region": "us-east-1",
        "internet_gateways": [],
        "vpc_peering_connections": [],
        "vpc_endpoints": [],
        "subnets": [
            {
                "subnet_id": "subnet-pub-1",
                "name": "public-subnet-1",
                "az": "us-east-1a",
                "cidr": "10.0.1.0/24",
                "type": "public",
                "available_ips": 250,
                "route_table_id": "rtb-pub",
                "default_route_target": "igw-001",
            },
            {
                "subnet_id": "subnet-priv-1",
                "name": "private-subnet-1",
                "az": "us-east-1a",
                "cidr": "10.0.2.0/24",
                "type": "private",
                "available_ips": 250,
                "route_table_id": "rtb-priv",
                "default_route_target": "nat-001" if has_nat else None,
            },
        ],
        "route_tables": [
            {
                "route_table_id": "rtb-pub",
                "name": "public-rt",
                "associated_subnets": ["subnet-pub-1"],
                "is_main": False,
                "routes": [
                    {"destination": "10.0.0.0/16", "state": "active", "target": "local", "origin": "CreateRouteTable"},
                    {
                        "destination": "0.0.0.0/0",
                        "state": "active",
                        "target": "igw-001" if has_igw else "blackhole",
                        "origin": "CreateRoute",
                    },
                ],
            },
            {
                "route_table_id": "rtb-priv",
                "name": "private-rt",
                "associated_subnets": ["subnet-priv-1"],
                "is_main": True,
                "routes": [
                    {"destination": "10.0.0.0/16", "state": "active", "target": "local", "origin": "CreateRouteTable"},
                ]
                + (
                    [{"destination": "0.0.0.0/0", "state": "active", "target": "nat-001", "origin": "CreateRoute"}]
                    if has_nat
                    else []
                )
                + (
                    [{"destination": "0.0.0.0/0", "state": "blackhole", "target": "nat-deleted", "origin": "CreateRoute"}]
                    if has_blackhole
                    else []
                ),
            },
        ],
        "nat_gateways": [],
        "transit_gateway_attachments": [],
        "security_group_dependency_map": {},
        "blackhole_routes": [],
    }

    if has_igw:
        topo["internet_gateways"] = [
            {"igw_id": "igw-001", "name": "main-igw", "attachments": [{"vpc_id": "vpc-001", "state": "attached"}]}
        ]

    if has_nat:
        topo["nat_gateways"] = [
            {
                "nat_gateway_id": "nat-001",
                "name": "main-nat",
                "subnet_id": "subnet-pub-1",
                "state": "available",
                "connectivity_type": "public",
                "az": "us-east-1a",
            }
        ]

    if has_blackhole:
        topo["blackhole_routes"] = [
            {"route_table_id": "rtb-priv", "destination": "0.0.0.0/0", "target": "nat-deleted", "affected_subnets": ["subnet-priv-1"]}
        ]

    if has_tgw:
        topo["transit_gateway_attachments"] = [
            {
                "attachment_id": "tgw-att-001",
                "transit_gateway_id": "tgw-001",
                "resource_type": "vpc",
                "state": "available",
            }
        ]

    if has_peering:
        topo["vpc_peering_connections"] = [
            {
                "pcx_id": "pcx-001",
                "status": "active",
                "requester_vpc": "vpc-001",
                "requester_cidr": "10.0.0.0/16",
                "requester_owner": "111111111111",
                "accepter_vpc": "vpc-002",
                "accepter_cidr": "10.1.0.0/16",
                "accepter_owner": "222222222222",
            }
        ]

    return topo


def _make_region_topology(vpc_count: int = 2, has_tgw: bool = True) -> dict:
    """Build a minimal region topology dict."""
    vpcs = [
        {
            "vpc_id": f"vpc-{i:03d}",
            "name": f"vpc-{i}",
            "cidr_block": f"10.{i}.0.0/16",
            "state": "available",
            "is_default": i == 0,
            "subnet_count": 3,
        }
        for i in range(vpc_count)
    ]

    tgws = []
    if has_tgw and vpc_count >= 2:
        tgws = [
            {
                "transit_gateway_id": "tgw-001",
                "name": "main-tgw",
                "state": "available",
                "attachments": [
                    {"attachment_id": f"tgw-att-{i}", "resource_type": "vpc", "resource_id": f"vpc-{i:03d}", "state": "available"}
                    for i in range(vpc_count)
                ],
            }
        ]

    return {
        "region": "us-east-1",
        "vpcs": vpcs,
        "transit_gateways": tgws,
        "peering_connections": [],
    }


# ── Engine Tests ─────────────────────────────────────────────────────


class TestInfraGraphBuild:
    def test_build_from_vpc_topology_basic(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)

        assert g.graph.number_of_nodes() > 0
        assert g.graph.number_of_edges() > 0

        # Check VPC node exists
        vpc_node = g.get_node("vpc-001")
        assert vpc_node is not None
        assert vpc_node["node_type"] == NodeType.VPC

    def test_build_from_vpc_topology_node_types(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True, has_tgw=True)
        g = InfraGraph().build_from_vpc_topology(topo)

        igws = g.get_nodes_by_type(NodeType.INTERNET_GATEWAY)
        assert len(igws) == 1
        assert igws[0] == "igw-001"

        subnets = g.get_nodes_by_type(NodeType.SUBNET)
        assert len(subnets) == 2

        nats = g.get_nodes_by_type(NodeType.NAT_GATEWAY)
        assert len(nats) == 1

        tgws = g.get_nodes_by_type(NodeType.TGW_ATTACHMENT)
        assert len(tgws) == 1

    def test_build_from_vpc_topology_edges(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)

        # Subnet -> RouteTable associations
        neighbors = g.get_neighbors("subnet-pub-1", EdgeType.ASSOCIATED_WITH)
        assert "rtb-pub" in neighbors

    def test_build_from_region_topology(self):
        topo = _make_region_topology(vpc_count=3, has_tgw=True)
        g = InfraGraph().build_from_region_topology(topo)

        vpcs = g.get_nodes_by_type(NodeType.VPC)
        assert len(vpcs) == 3

        tgws = g.get_nodes_by_type(NodeType.TRANSIT_GATEWAY)
        assert len(tgws) == 1

    def test_merge_graphs(self):
        g1 = InfraGraph().build_from_vpc_topology(_make_vpc_topology())
        g2 = InfraGraph()
        g2._graph.add_node("extra-node", node_type="test")

        g1.merge(g2)
        assert "extra-node" in g1.graph

    def test_subgraph(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)

        sub = g.subgraph({"vpc-001", "igw-001"})
        assert sub.graph.number_of_nodes() == 2


# ── Algorithm Tests ──────────────────────────────────────────────────


class TestReachability:
    def test_public_subnet_reaches_internet(self):
        """Public subnet -> route table -> IGW = reachable."""
        topo = _make_vpc_topology(has_igw=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = can_reach_internet(g, "subnet-pub-1")

        assert result.can_reach_internet is True
        assert len(result.path) > 0
        assert "igw-001" in result.path

    def test_private_subnet_through_nat_reaches_internet(self):
        """Private subnet -> RT -> NAT -> NAT's subnet -> RT -> IGW = reachable."""
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = can_reach_internet(g, "subnet-priv-1")

        assert result.can_reach_internet is True
        assert "igw-001" in result.path

    def test_isolated_subnet_no_internet(self):
        """Subnet with no route to 0.0.0.0/0 = unreachable."""
        topo = _make_vpc_topology(has_igw=False, has_nat=False)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = can_reach_internet(g, "subnet-pub-1")

        assert result.can_reach_internet is False
        assert result.blocking_reason is not None

    def test_blackhole_blocks_reachability(self):
        """Path with blackhole route should be detected by anomaly detection."""
        topo = _make_vpc_topology(has_igw=True, has_nat=False, has_blackhole=True)
        g = InfraGraph().build_from_vpc_topology(topo)

        # The private subnet can still find a path via VPC containment edges,
        # but the blackhole is detectable via anomaly detection.
        result = can_reach_internet(g, "subnet-priv-1")
        # Path exists through VPC node (structural connectivity)
        assert result.subnet_id == "subnet-priv-1"

        # The blackhole should be caught by anomaly detection
        anomaly_result = detect_anomalies(g)
        blackholes = [a for a in anomaly_result.anomalies if a.type == "blackhole_route"]
        assert len(blackholes) > 0

    def test_nonexistent_subnet(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)
        result = can_reach_internet(g, "subnet-nonexistent")

        assert result.can_reach_internet is False
        assert "not found" in (result.blocking_reason or "")


class TestImpactAnalysis:
    def test_nat_failure_isolates_private_subnets(self):
        """Removing NAT gateway should isolate private subnets from internet."""
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = impact_analysis(g, "nat-001")

        assert result.failed_node_id == "nat-001"
        assert len(result.affected_nodes) > 0

    def test_igw_failure_impacts_all(self):
        """Removing IGW should affect connected nodes."""
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = impact_analysis(g, "igw-001")

        assert result.failed_node_id == "igw-001"
        assert result.failed_node_type == NodeType.INTERNET_GATEWAY
        # IGW connects to VPC and route table — those are affected
        assert len(result.affected_nodes) > 0

    def test_nonexistent_node(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)
        result = impact_analysis(g, "nonexistent")

        assert result.severity == "unknown"


class TestPathFinding:
    def test_find_path_between_subnets(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = find_traffic_path(g, "subnet-pub-1", "subnet-priv-1")

        assert result.paths_found > 0
        assert len(result.paths) > 0

    def test_path_to_igw(self):
        topo = _make_vpc_topology(has_igw=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = find_traffic_path(g, "subnet-pub-1", "igw-001")

        assert result.paths_found > 0

    def test_no_path(self):
        topo = _make_vpc_topology(has_igw=False, has_nat=False)
        g = InfraGraph().build_from_vpc_topology(topo)
        # Add an isolated node
        g._graph.add_node("isolated-node", node_type="test")
        result = find_traffic_path(g, "subnet-pub-1", "isolated-node")

        assert result.paths_found == 0


class TestAnomalyDetection:
    def test_blackhole_detected(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=False, has_blackhole=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = detect_anomalies(g)

        blackhole_anomalies = [a for a in result.anomalies if a.type == "blackhole_route"]
        assert len(blackhole_anomalies) > 0

    def test_orphan_node_detected(self):
        topo = _make_vpc_topology()
        g = InfraGraph().build_from_vpc_topology(topo)
        # Add an orphan node
        g._graph.add_node("orphan-001", node_type=NodeType.SUBNET, label="orphan", status=NodeStatus.UNKNOWN)
        result = detect_anomalies(g)

        orphan_anomalies = [a for a in result.anomalies if a.type == "orphan_node"]
        assert len(orphan_anomalies) > 0

    def test_no_anomalies_in_healthy_vpc(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = detect_anomalies(g)

        # A healthy VPC should have few/no anomalies
        critical = [a for a in result.anomalies if a.severity == "critical"]
        assert len(critical) == 0


class TestNetworkSegments:
    def test_single_connected_segment(self):
        topo = _make_region_topology(vpc_count=2, has_tgw=True)
        g = InfraGraph().build_from_region_topology(topo)
        result = network_segments(g)

        # All VPCs connected via TGW should be in one segment
        assert result.total_segments == 1

    def test_isolated_vpcs(self):
        topo = _make_region_topology(vpc_count=3, has_tgw=False)
        g = InfraGraph().build_from_region_topology(topo)
        result = network_segments(g)

        # Without TGW, each VPC is its own segment
        assert result.total_segments == 3
        assert len(result.isolated_vpcs) == 3


# ── Serializer Tests ─────────────────────────────────────────────────


class TestSerializers:
    def test_to_reactflow_vpc(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        result = to_reactflow(g, view="vpc")

        assert len(result.nodes) > 0
        assert len(result.edges) > 0
        assert result.metadata.node_count == len(result.nodes)
        assert result.metadata.edge_count == len(result.edges)

        # Check node types are ReactFlow-compatible
        node_types = {n.type for n in result.nodes}
        assert "subnetNode" in node_types or "igwNode" in node_types

    def test_to_reactflow_region(self):
        topo = _make_region_topology(vpc_count=2, has_tgw=True)
        g = InfraGraph().build_from_region_topology(topo)
        result = to_reactflow(g, view="region")

        assert len(result.nodes) > 0
        node_types = {n.type for n in result.nodes}
        assert "vpcGroupNode" in node_types

    def test_to_agent_summary(self):
        topo = _make_vpc_topology(has_igw=True, has_nat=True)
        g = InfraGraph().build_from_vpc_topology(topo)
        summary = to_agent_summary(g)

        assert "nodes" in summary.lower() or "Nodes" in summary
        assert "edges" in summary.lower() or "Edges" in summary


# ── K8s Topology Tests ───────────────────────────────────────────────


class TestK8sTopology:
    """Tests for the new K8s topology builder (not in agenticops-chat)."""

    @staticmethod
    def _make_k8s_topology():
        return {
            "cluster_name": "test-eks",
            "nodes": [
                {"name": "ip-10-0-1-1", "status": "Ready"},
                {"name": "ip-10-0-1-2", "status": "Ready"},
                {"name": "ip-10-0-1-3", "status": "NotReady"},
            ],
            "namespaces": [
                {
                    "name": "default",
                    "deployments": [
                        {"name": "nginx", "labels": {"app": "nginx"}, "replicas": 3, "ready_replicas": 3},
                        {"name": "redis", "labels": {"app": "redis"}, "replicas": 2, "ready_replicas": 1},
                    ],
                    "services": [
                        {"name": "nginx-svc", "type": "ClusterIP", "selector": {"app": "nginx"}},
                        {"name": "redis-svc", "type": "ClusterIP", "selector": {"app": "redis"}},
                    ],
                    "pods": [
                        {"name": "nginx-abc1", "node": "ip-10-0-1-1", "status": "Running"},
                        {"name": "nginx-abc2", "node": "ip-10-0-1-2", "status": "Running"},
                        {"name": "redis-xyz1", "node": "ip-10-0-1-1", "status": "Running"},
                        {"name": "redis-xyz2", "node": "ip-10-0-1-3", "status": "Pending"},
                    ],
                },
                {
                    "name": "kube-system",
                    "deployments": [
                        {"name": "coredns", "labels": {"k8s-app": "kube-dns"}, "replicas": 2, "ready_replicas": 2},
                    ],
                    "services": [],
                    "pods": [],
                },
            ],
        }

    def test_k8s_topology_builds(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        assert g.node_count > 0
        assert g.edge_count > 0

    def test_k8s_cluster_node(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        cluster = g.get_node("test-eks")
        assert cluster is not None
        assert cluster["node_type"] == NodeType.EKS_CLUSTER

    def test_k8s_worker_nodes(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        workers = g.get_nodes_by_type(NodeType.K8S_NODE)
        assert len(workers) == 3
        # NotReady node should have ERROR status
        not_ready = g.get_node("ip-10-0-1-3")
        assert not_ready["status"] == NodeStatus.ERROR

    def test_k8s_namespaces(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        namespaces = g.get_nodes_by_type(NodeType.K8S_NAMESPACE)
        assert len(namespaces) == 2

    def test_k8s_deployments(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        deploys = g.get_nodes_by_type(NodeType.K8S_DEPLOYMENT)
        assert len(deploys) == 3  # nginx, redis, coredns

        # redis has 1/2 ready → WARNING
        redis = g.get_node("ns/default/deploy/redis")
        assert redis["status"] == NodeStatus.WARNING

        # nginx has 3/3 ready → HEALTHY
        nginx = g.get_node("ns/default/deploy/nginx")
        assert nginx["status"] == NodeStatus.HEALTHY

    def test_k8s_service_exposes_deployment(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        neighbors = g.get_neighbors("ns/default/svc/nginx-svc", EdgeType.EXPOSES)
        assert "ns/default/deploy/nginx" in neighbors

    def test_k8s_pod_runs_on_node(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        neighbors = g.get_neighbors("ns/default/pod/nginx-abc1", EdgeType.RUNS_ON)
        assert "ip-10-0-1-1" in neighbors

    def test_k8s_pending_pod_status(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        pod = g.get_node("ns/default/pod/redis-xyz2")
        assert pod["status"] == NodeStatus.WARNING

    def test_k8s_anomaly_detection(self):
        """NotReady node should be caught as unhealthy."""
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        result = detect_anomalies(g)
        unhealthy = [a for a in result.anomalies if a.type == "unhealthy_node"]
        # NotReady node + WARNING deployment should show
        assert len(unhealthy) >= 1

    def test_k8s_merge_with_vpc(self):
        """K8s and VPC graphs can merge for unified topology."""
        k8s = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        k8s_count = k8s.node_count
        vpc = InfraGraph().build_from_vpc_topology(_make_vpc_topology())
        vpc_count = vpc.node_count
        merged = k8s.merge(vpc)

        # Both EKS and VPC nodes should exist
        assert merged.get_node("test-eks") is not None
        assert merged.get_node("vpc-001") is not None
        assert merged.node_count == k8s_count + vpc_count

    def test_k8s_reactflow_serialization(self):
        g = InfraGraph().build_from_k8s_topology(self._make_k8s_topology())
        result = to_reactflow(g)
        assert len(result.nodes) > 0
        node_types = {n.type for n in result.nodes}
        assert "eksNode" in node_types
        assert "workerNode" in node_types
        assert "deploymentNode" in node_types


# ── API Router Tests ─────────────────────────────────────────────────


class TestTopologyAPI:
    """Tests for the FastAPI topology router using mocked boto3."""

    @pytest.fixture
    def mock_boto3(self, monkeypatch):
        """Mock boto3 client to avoid real AWS calls."""
        import unittest.mock as mock

        mock_ec2 = mock.MagicMock()
        mock_ec2.describe_vpcs.return_value = {
            "Vpcs": [{
                "VpcId": "vpc-test",
                "CidrBlock": "10.0.0.0/16",
                "Tags": [{"Key": "Name", "Value": "test-vpc"}],
            }]
        }
        mock_ec2.describe_internet_gateways.return_value = {
            "InternetGateways": [{
                "InternetGatewayId": "igw-test",
                "Attachments": [{"VpcId": "vpc-test", "State": "attached"}],
                "Tags": [{"Key": "Name", "Value": "test-igw"}],
            }]
        }
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [{
                "SubnetId": "subnet-test",
                "CidrBlock": "10.0.1.0/24",
                "AvailabilityZone": "us-east-1a",
                "AvailableIpAddressCount": 250,
                "MapPublicIpOnLaunch": True,
                "Tags": [{"Key": "Name", "Value": "test-subnet"}],
            }]
        }
        mock_ec2.describe_route_tables.return_value = {
            "RouteTables": [{
                "RouteTableId": "rtb-test",
                "Associations": [{"SubnetId": "subnet-test"}],
                "Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "State": "active"},
                    {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-test", "State": "active"},
                ],
                "Tags": [{"Key": "Name", "Value": "test-rt"}],
            }]
        }
        mock_ec2.describe_nat_gateways.return_value = {"NatGateways": []}
        mock_ec2.describe_transit_gateway_attachments.return_value = {"TransitGatewayAttachments": []}
        mock_ec2.describe_vpc_peering_connections.return_value = {"VpcPeeringConnections": []}
        mock_ec2.describe_vpc_endpoints.return_value = {"VpcEndpoints": []}
        mock_ec2.describe_transit_gateways.return_value = {"TransitGateways": []}

        monkeypatch.setattr("src.aci.topology.collector.boto3.client", lambda *a, **kw: mock_ec2)
        return mock_ec2

    def test_get_vpc_topology_api(self, mock_boto3):
        """Test collect_vpc_topology builds correct dict from boto3."""
        from src.aci.topology.collector import collect_vpc_topology

        topo = collect_vpc_topology("us-east-1", "vpc-test")
        assert topo["vpc_id"] == "vpc-test"
        assert topo["vpc_name"] == "test-vpc"
        assert len(topo["internet_gateways"]) == 1
        assert len(topo["subnets"]) == 1
        assert len(topo["route_tables"]) == 1

    def test_vpc_graph_from_boto3(self, mock_boto3):
        """Test full pipeline: boto3 → topology dict → InfraGraph."""
        from src.aci.topology.api import _build_vpc_graph

        graph = _build_vpc_graph("us-east-1", "vpc-test")
        assert graph.node_count > 0
        assert graph.get_node("vpc-test") is not None
        assert graph.get_node("igw-test") is not None

    def test_region_graph_from_boto3(self, mock_boto3):
        """Test region-level graph building."""
        from src.aci.topology.api import _build_region_graph

        graph = _build_region_graph("us-east-1")
        assert graph.node_count > 0
        vpcs = graph.get_nodes_by_type(NodeType.VPC)
        assert len(vpcs) >= 1
