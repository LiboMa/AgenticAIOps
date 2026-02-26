"""Tests for fault propagation integration — waves, rca_context_block, DetectResult enrichment.

Covers:
  1. PropagationResult wave tracking + impact counts
  2. rca_context_block rendering + truncation
  3. to_dict() serialization
  4. DetectResult topology_context / propagation_result fields
  5. _build_analysis_prompt() network context injection
  6. IncidentOrchestrator topology context extraction
  7. Edge weight inference for degradation factors
  8. ImpactLevel classification by weight
"""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from collections import OrderedDict

from src.aci.topology.engine import InfraGraph
from src.aci.topology.types import NodeType, EdgeType, NodeAttrs, EdgeAttrs, NodeStatus
from src.aci.topology.propagation import (
    fault_propagation,
    blast_radius,
    realistic_impact,
    PropagationMode,
    PropagationResult,
    PropagationWave,
    WaveEntry,
    DegradationFactor,
    ImpactLevel,
    _infer_edge_weight,
    _render_rca_context_block,
)
from src.detect_agent import DetectResult, DetectAgent


# ── Fixtures ─────────────────────────────────────────────────────────


def _build_simple_graph() -> InfraGraph:
    """Build a small VPC graph for testing: VPC → Subnet → NAT → Pod chain."""
    g = InfraGraph()
    # VPC
    g._add_node("vpc-1", NodeAttrs(
        node_type=NodeType.VPC, label="test-vpc", status=NodeStatus.HEALTHY,
    ))
    # Subnets
    g._add_node("subnet-pub", NodeAttrs(
        node_type=NodeType.SUBNET, label="public-subnet", status=NodeStatus.HEALTHY,
        raw={"availability_zone": "us-east-1a"},
    ))
    g._add_node("subnet-priv-1a", NodeAttrs(
        node_type=NodeType.SUBNET, label="private-1a", status=NodeStatus.HEALTHY,
        raw={"availability_zone": "us-east-1a"},
    ))
    g._add_node("subnet-priv-1b", NodeAttrs(
        node_type=NodeType.SUBNET, label="private-1b", status=NodeStatus.HEALTHY,
        raw={"availability_zone": "us-east-1b"},
    ))
    # NAT Gateway
    g._add_node("nat-1", NodeAttrs(
        node_type=NodeType.NAT_GATEWAY, label="nat-gw-1", status=NodeStatus.HEALTHY,
        raw={"availability_zone": "us-east-1a"},
    ))
    # Route table
    g._add_node("rtb-priv", NodeAttrs(
        node_type=NodeType.ROUTE_TABLE, label="rtb-private", status=NodeStatus.HEALTHY,
    ))
    # K8s node
    g._add_node("node-1", NodeAttrs(
        node_type=NodeType.K8S_NODE, label="k8s-node-1", status=NodeStatus.HEALTHY,
    ))
    # K8s deployment (multi-replica)
    g._add_node("deploy-1", NodeAttrs(
        node_type=NodeType.K8S_DEPLOYMENT, label="web-app", status=NodeStatus.HEALTHY,
        raw={"replicas": 3, "ready_replicas": 3},
    ))
    # K8s service
    g._add_node("svc-1", NodeAttrs(
        node_type=NodeType.K8S_SERVICE, label="web-svc", status=NodeStatus.HEALTHY,
    ))

    # Edges: VPC → Subnet, NAT → Subnet, RTB → NAT, Service → Deployment
    g._add_edge("vpc-1", "subnet-pub", EdgeAttrs(edge_type=EdgeType.CONTAINS))
    g._add_edge("vpc-1", "subnet-priv-1a", EdgeAttrs(edge_type=EdgeType.CONTAINS))
    g._add_edge("vpc-1", "subnet-priv-1b", EdgeAttrs(edge_type=EdgeType.CONTAINS))
    g._add_edge("nat-1", "subnet-priv-1a", EdgeAttrs(edge_type=EdgeType.HOSTED_IN))
    g._add_edge("nat-1", "subnet-priv-1b", EdgeAttrs(edge_type=EdgeType.HOSTED_IN))
    g._add_edge("rtb-priv", "nat-1", EdgeAttrs(edge_type=EdgeType.ROUTES_TO))
    g._add_edge("svc-1", "deploy-1", EdgeAttrs(edge_type=EdgeType.EXPOSES))
    g._add_edge("node-1", "deploy-1", EdgeAttrs(edge_type=EdgeType.RUNS_ON))

    return g


def _build_deep_chain_graph() -> InfraGraph:
    """Build a deep chain: A → B → C → D → E for max depth testing."""
    g = InfraGraph()
    for i in range(6):
        g._add_node(f"n{i}", NodeAttrs(
            node_type=NodeType.K8S_SERVICE, label=f"svc-{i}", status=NodeStatus.HEALTHY,
        ))
    for i in range(5):
        g._add_edge(f"n{i}", f"n{i+1}", EdgeAttrs(edge_type=EdgeType.DEPENDS_ON))
    return g


def _build_multi_az_nat_graph() -> InfraGraph:
    """Graph with 2 NATs in different AZs (for realistic degradation)."""
    g = InfraGraph()
    g._add_node("nat-a", NodeAttrs(
        node_type=NodeType.NAT_GATEWAY, label="nat-1a", status=NodeStatus.HEALTHY,
        raw={"availability_zone": "us-east-1a"},
    ))
    g._add_node("nat-b", NodeAttrs(
        node_type=NodeType.NAT_GATEWAY, label="nat-1b", status=NodeStatus.HEALTHY,
        raw={"availability_zone": "us-east-1b"},
    ))
    g._add_node("subnet-1", NodeAttrs(
        node_type=NodeType.SUBNET, label="priv-1", status=NodeStatus.HEALTHY,
    ))
    g._add_edge("nat-a", "subnet-1", EdgeAttrs(edge_type=EdgeType.HOSTED_IN))
    g._add_edge("nat-b", "subnet-1", EdgeAttrs(edge_type=EdgeType.HOSTED_IN))
    return g


# ── Tests: Wave Tracking ────────────────────────────────────────────


class TestWaveTracking:
    """Verify wave-based propagation output."""

    def test_root_failure_is_wave_0(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        assert len(result.waves) >= 1
        wave0 = result.waves[0]
        assert wave0.depth == 0
        assert any(e.node_id == "nat-1" for e in wave0.affected)
        root_entry = [e for e in wave0.affected if e.node_id == "nat-1"][0]
        assert root_entry.impact_level == ImpactLevel.FAILED
        assert root_entry.reason == "root failure"

    def test_direct_impact_is_wave_1(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        wave1_nodes = set()
        for w in result.waves:
            if w.depth == 1:
                wave1_nodes = {e.node_id for e in w.affected}
        # NAT → subnet-priv-1a, subnet-priv-1b via HOSTED_IN
        assert "subnet-priv-1a" in wave1_nodes
        assert "subnet-priv-1b" in wave1_nodes

    def test_deep_chain_multiple_waves(self):
        g = _build_deep_chain_graph()
        result = fault_propagation(g, "n0", mode=PropagationMode.PESSIMISTIC)
        assert result.max_depth_reached == 5
        assert len(result.waves) == 6  # wave 0 through 5

    def test_max_depth_limits_waves(self):
        g = _build_deep_chain_graph()
        result = fault_propagation(g, "n0", max_depth=2)
        assert result.max_depth_reached <= 2
        assert len(result.affected_nodes) <= 3  # n0, n1, n2

    def test_wave_edge_cuts_tracked(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        # Wave 1 should have edge cuts from nat-1
        wave1 = [w for w in result.waves if w.depth == 1]
        if wave1:
            assert len(wave1[0].edge_cuts) > 0
            sources = {ec["source"] for ec in wave1[0].edge_cuts}
            assert "nat-1" in sources


# ── Tests: Impact Level Classification ──────────────────────────────


class TestImpactLevels:

    def test_pessimistic_all_failed(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        # In pessimistic mode, all affected nodes should be FAILED
        for w in result.waves:
            for entry in w.affected:
                assert entry.impact_level == ImpactLevel.FAILED

    def test_realistic_deployment_degraded(self):
        """Multi-replica deployment should be DEGRADED or AT_RISK, not FAILED."""
        g = _build_simple_graph()
        result = fault_propagation(g, "svc-1", mode=PropagationMode.REALISTIC)
        deploy_entries = []
        for w in result.waves:
            for e in w.affected:
                if e.node_id == "deploy-1":
                    deploy_entries.append(e)
        # deploy-1 has 3 replicas, so should be degraded or at_risk
        if deploy_entries:
            assert deploy_entries[0].impact_level in (ImpactLevel.DEGRADED, ImpactLevel.AT_RISK)

    def test_total_failed_count(self):
        g = _build_deep_chain_graph()
        result = fault_propagation(g, "n0", mode=PropagationMode.PESSIMISTIC)
        assert result.total_failed == 6  # all nodes
        assert result.total_degraded == 0
        assert result.total_at_risk == 0


# ── Tests: Degradation Factors ──────────────────────────────────────


class TestDegradationFactors:

    def test_multi_az_nat_factor(self):
        """When a NAT fails but target subnet has multi-AZ subnets, detect it."""
        g = InfraGraph()
        g._add_node("nat-a", NodeAttrs(
            node_type=NodeType.NAT_GATEWAY, label="nat-1a", status=NodeStatus.HEALTHY,
            raw={"availability_zone": "us-east-1a"},
        ))
        # Target is another NAT (multi-AZ sibling) — tests nat-multi-az rule
        g._add_node("nat-b", NodeAttrs(
            node_type=NodeType.NAT_GATEWAY, label="nat-1b", status=NodeStatus.HEALTHY,
            raw={"availability_zone": "us-east-1b"},
        ))
        g._add_edge("nat-a", "nat-b", EdgeAttrs(edge_type=EdgeType.PEERS_WITH))
        result = fault_propagation(g, "nat-a", mode=PropagationMode.REALISTIC)
        # nat-b is a NAT with a multi-AZ sibling → should see degradation factor
        has_nat_factor = any("nat" in d.factor_type for d in result.degradation_factors)
        assert has_nat_factor

    def test_k8s_replicas_factor(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "svc-1", mode=PropagationMode.REALISTIC)
        # deploy-1 has 3 replicas → should see k8s-replicas factor
        k8s_factors = [d for d in result.degradation_factors if "k8s" in d.description]
        if k8s_factors:
            assert k8s_factors[0].mitigation_weight > 0

    def test_pessimistic_no_factors(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        # Pessimistic mode should not produce degradation factors
        assert len(result.degradation_factors) == 0


# ── Tests: Edge Weight Inference ─────────────────────────────────────


class TestEdgeWeightInference:

    def test_circuit_breaker_blocks(self):
        g = InfraGraph()
        g._add_node("src", NodeAttrs(node_type=NodeType.K8S_SERVICE, label="src"))
        g._add_node("tgt", NodeAttrs(
            node_type=NodeType.K8S_SERVICE, label="tgt",
            raw={"tags": {"circuit_breaker": "open"}},
        ))
        w, reason = _infer_edge_weight(g, "src", "tgt")
        assert w == 0.0
        assert "circuit-breaker" in reason

    def test_asg_healthy_low_weight(self):
        g = InfraGraph()
        g._add_node("src", NodeAttrs(node_type=NodeType.K8S_SERVICE, label="src"))
        g._add_node("asg-1", NodeAttrs(
            node_type=NodeType.ASG, label="asg",
            raw={"healthy_count": 3, "desired_count": 3},
        ))
        w, reason = _infer_edge_weight(g, "src", "asg-1")
        assert w <= 0.3
        assert "asg-healthy" in reason

    def test_single_pod_high_weight(self):
        g = InfraGraph()
        g._add_node("src", NodeAttrs(node_type=NodeType.K8S_SERVICE, label="src"))
        g._add_node("dep", NodeAttrs(
            node_type=NodeType.K8S_DEPLOYMENT, label="dep",
            raw={"replicas": 1, "ready_replicas": 1},
        ))
        w, reason = _infer_edge_weight(g, "src", "dep")
        assert w == 1.0

    def test_unknown_node_full_weight(self):
        g = InfraGraph()
        g._add_node("src", NodeAttrs(node_type=NodeType.K8S_SERVICE, label="src"))
        # Don't add target at all
        w, reason = _infer_edge_weight(g, "src", "nonexistent")
        assert w == 1.0


# ── Tests: RCA Context Block Rendering ──────────────────────────────


class TestRCAContextBlock:

    def test_block_contains_header(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        assert "## 🗺️ Network Topology Context" in result.rca_context_block

    def test_block_contains_root_failure(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        assert "nat-1" in result.rca_context_block
        assert "Failed Resource" in result.rca_context_block

    def test_block_contains_blast_radius(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        assert "Blast Radius" in result.rca_context_block

    def test_block_contains_wave_headers(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        assert "Wave 0 (Root Failure)" in result.rca_context_block

    def test_block_contains_summary(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        assert "Summary" in result.rca_context_block
        assert "failed" in result.rca_context_block

    def test_block_truncation(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        block = _render_rca_context_block(result, g, max_chars=100)
        assert len(block) <= 120  # some slack for truncation marker
        assert "[truncated]" in block

    def test_block_realistic_mode_shows_factors(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "svc-1", mode=PropagationMode.REALISTIC)
        if result.degradation_factors:
            assert "Degradation Factors" in result.rca_context_block

    def test_empty_graph_node_not_found(self):
        g = InfraGraph()
        result = fault_propagation(g, "nonexistent")
        assert result.rca_context_block == ""  # empty result, no rendering
        assert result.affected_nodes == []


# ── Tests: to_dict() Serialization ──────────────────────────────────


class TestPropagationResultSerialization:

    def test_to_dict_keys(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        d = result.to_dict()
        assert "root_failure" in d
        assert "mode" in d
        assert "waves" in d
        assert "summary" in d
        assert "degradation_factors" in d
        assert "rca_context_block" in d
        assert "critical_path" in d

    def test_to_dict_json_serializable(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        d = result.to_dict()
        # Should not raise
        json_str = json.dumps(d, default=str)
        parsed = json.loads(json_str)
        assert parsed["mode"] == "pessimistic"

    def test_summary_counts(self):
        g = _build_deep_chain_graph()
        result = fault_propagation(g, "n0", mode=PropagationMode.PESSIMISTIC)
        d = result.to_dict()
        assert d["summary"]["total_affected"] == 6
        assert d["summary"]["total_failed"] == 6
        assert d["summary"]["max_depth"] == 5

    def test_waves_structure(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1", mode=PropagationMode.PESSIMISTIC)
        d = result.to_dict()
        for wave in d["waves"]:
            assert "depth" in wave
            assert "affected" in wave
            assert "edge_cuts" in wave
            for entry in wave["affected"]:
                assert "node_id" in entry
                assert "node_type" in entry
                assert "impact_level" in entry
                assert "reason" in entry


# ── Tests: DetectResult Fields ──────────────────────────────────────


class TestDetectResultTopologyFields:

    def test_default_none(self):
        r = DetectResult(
            detect_id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            source="manual",
        )
        assert r.topology_context is None
        assert r.propagation_result is None

    def test_to_dict_includes_new_fields(self):
        r = DetectResult(
            detect_id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            source="manual",
            topology_context={"vpc_id": "vpc-123", "anomalies": []},
            propagation_result={"root_failure": {"id": "nat-1"}, "rca_context_block": "test"},
        )
        d = r.to_dict()
        assert d["topology_context"]["vpc_id"] == "vpc-123"
        assert d["propagation_result"]["rca_context_block"] == "test"

    def test_backward_compatible(self):
        """Old consumers that don't use new fields should still work."""
        r = DetectResult(
            detect_id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            source="manual",
        )
        d = r.to_dict()
        assert "topology_context" in d
        assert d["topology_context"] is None
        # Existing fields still present
        assert "detect_id" in d
        assert "anomalies_detected" in d

    def test_extract_vpc_id_from_raw_data(self):
        r = DetectResult(
            detect_id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            source="manual",
            raw_data={"vpc_id": "vpc-abc"},
        )
        vpc = DetectAgent._extract_vpc_id(r)
        assert vpc == "vpc-abc"

    def test_extract_vpc_id_none(self):
        r = DetectResult(
            detect_id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            source="manual",
        )
        vpc = DetectAgent._extract_vpc_id(r)
        assert vpc is None

    def test_extract_failed_resource(self):
        r = DetectResult(
            detect_id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            source="manual",
            anomalies_detected=[
                {"resource_id": "nat-123", "metric": "PacketsDropped"},
            ],
        )
        res = DetectAgent._extract_failed_resource(r)
        assert res == "nat-123"

    def test_extract_failed_resource_none(self):
        r = DetectResult(
            detect_id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            source="manual",
            anomalies_detected=[],
        )
        res = DetectAgent._extract_failed_resource(r)
        assert res is None


# ── Tests: RCA Prompt Injection ──────────────────────────────────────


class TestRCAPromptInjection:

    def test_build_prompt_with_network_context(self):
        from src.rca_inference import _build_analysis_prompt

        # Create a mock correlated event
        event = MagicMock()
        event.alarms = []
        event.anomalies = []
        event.metrics = []
        event.recent_changes = []
        event.health_events = []
        event.region = "us-east-1"
        event.duration_ms = 100
        event.source_status = {}

        ctx = "## 🗺️ Network Topology Context\n**Failed Resource**: nat-1"
        prompt = _build_analysis_prompt(event, network_propagation_context=ctx)
        assert "Network Topology Context" in prompt
        assert "nat-1" in prompt
        assert "topology context to understand infrastructure" in prompt

    def test_build_prompt_without_network_context(self):
        from src.rca_inference import _build_analysis_prompt

        event = MagicMock()
        event.alarms = []
        event.anomalies = []
        event.metrics = []
        event.recent_changes = []
        event.health_events = []
        event.region = "us-east-1"
        event.duration_ms = 100
        event.source_status = {}

        prompt = _build_analysis_prompt(event, network_propagation_context="")
        assert "Network Topology Context" not in prompt


# ── Tests: Convenience Helpers ──────────────────────────────────────


class TestConvenienceHelpers:

    def test_blast_radius_is_pessimistic(self):
        g = _build_simple_graph()
        result = blast_radius(g, "nat-1")
        assert result.mode == PropagationMode.PESSIMISTIC

    def test_realistic_impact_helper(self):
        g = _build_simple_graph()
        result = realistic_impact(g, "nat-1")
        assert result.mode == PropagationMode.REALISTIC

    def test_propagation_time_measured(self):
        g = _build_simple_graph()
        result = fault_propagation(g, "nat-1")
        assert result.propagation_time_ms >= 0


# ── Tests: Critical Path ────────────────────────────────────────────


class TestCriticalPath:

    def test_critical_path_starts_at_origin(self):
        g = _build_deep_chain_graph()
        result = fault_propagation(g, "n0", mode=PropagationMode.PESSIMISTIC)
        assert result.critical_path[0] == "n0"

    def test_critical_path_is_longest(self):
        g = _build_deep_chain_graph()
        result = fault_propagation(g, "n0", mode=PropagationMode.PESSIMISTIC)
        # Chain is n0 → n1 → n2 → n3 → n4 → n5
        assert len(result.critical_path) == 6


# ── Tests: Bidirectional Edge Propagation ────────────────────────────


class TestBidirectionalPropagation:

    def test_peers_with_propagates_both_ways(self):
        """PEERS_WITH is bidirectional — failure should propagate via reverse edge."""
        g = InfraGraph()
        g._add_node("vpc-a", NodeAttrs(node_type=NodeType.VPC, label="vpc-a"))
        g._add_node("vpc-b", NodeAttrs(node_type=NodeType.VPC, label="vpc-b"))
        # Only one directed edge: a → b
        g._add_edge("vpc-a", "vpc-b", EdgeAttrs(edge_type=EdgeType.PEERS_WITH))
        # Fail vpc-b — should still reach vpc-a via reverse PEERS_WITH
        result = fault_propagation(g, "vpc-b", mode=PropagationMode.PESSIMISTIC)
        assert "vpc-a" in result.affected_nodes

    def test_associated_with_propagates_both_ways(self):
        """ASSOCIATED_WITH is bidirectional."""
        g = InfraGraph()
        g._add_node("subnet-1", NodeAttrs(node_type=NodeType.SUBNET, label="sub"))
        g._add_node("rtb-1", NodeAttrs(node_type=NodeType.ROUTE_TABLE, label="rtb"))
        # Edge: subnet → rtb
        g._add_edge("subnet-1", "rtb-1", EdgeAttrs(edge_type=EdgeType.ASSOCIATED_WITH))
        # Fail rtb-1 — should propagate back to subnet-1
        result = fault_propagation(g, "rtb-1", mode=PropagationMode.PESSIMISTIC)
        assert "subnet-1" in result.affected_nodes

    def test_exposes_propagates_both_ways(self):
        """EXPOSES is bidirectional — Service↔Deployment."""
        g = InfraGraph()
        g._add_node("svc", NodeAttrs(node_type=NodeType.K8S_SERVICE, label="svc"))
        g._add_node("deploy", NodeAttrs(
            node_type=NodeType.K8S_DEPLOYMENT, label="deploy",
            raw={"replicas": 1, "ready_replicas": 1},
        ))
        # Edge: svc → deploy
        g._add_edge("svc", "deploy", EdgeAttrs(edge_type=EdgeType.EXPOSES))
        # Fail deploy — should propagate back to svc
        result = fault_propagation(g, "deploy", mode=PropagationMode.PESSIMISTIC)
        assert "svc" in result.affected_nodes

    def test_non_bidirectional_does_not_reverse(self):
        """CONTAINS is NOT bidirectional — child failure should not propagate to parent."""
        g = InfraGraph()
        g._add_node("vpc", NodeAttrs(node_type=NodeType.VPC, label="vpc"))
        g._add_node("subnet", NodeAttrs(node_type=NodeType.SUBNET, label="sub"))
        # Edge: vpc → subnet (CONTAINS)
        g._add_edge("vpc", "subnet", EdgeAttrs(edge_type=EdgeType.CONTAINS))
        # Fail subnet — should NOT propagate back to vpc
        result = fault_propagation(g, "subnet", mode=PropagationMode.PESSIMISTIC)
        assert "vpc" not in result.affected_nodes
        assert result.affected_nodes == ["subnet"]

    def test_replicas_zero_no_division_error(self):
        """replicas=0 should not cause ZeroDivisionError."""
        g = InfraGraph()
        g._add_node("svc", NodeAttrs(node_type=NodeType.K8S_SERVICE, label="svc"))
        g._add_node("deploy", NodeAttrs(
            node_type=NodeType.K8S_DEPLOYMENT, label="deploy",
            raw={"replicas": 0, "ready_replicas": 0},
        ))
        g._add_edge("svc", "deploy", EdgeAttrs(edge_type=EdgeType.EXPOSES))
        # Should not raise
        result = fault_propagation(g, "svc", mode=PropagationMode.REALISTIC)
        assert "deploy" in result.affected_nodes
