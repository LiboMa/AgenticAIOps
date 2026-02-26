"""Tests for src/aci/topology/propagation.py — Fault Propagation Engine.

Covers:
  - Pessimistic mode (all edges weight=1.0)
  - Realistic mode (weight inference)
  - Edge weight inference rules (multi-AZ, ASG, K8s, circuit breaker, NAT, LB)
  - Critical path extraction
  - Max depth limiting
  - Min weight filtering
  - Missing / unknown nodes
  - Convenience helpers (blast_radius, realistic_impact)
"""

from __future__ import annotations

import pytest

from src.aci.topology.engine import InfraGraph
from src.aci.topology.propagation import (
    PropagationMode,
    PropagationResult,
    _find_critical_path,
    _infer_edge_weight,
    blast_radius,
    fault_propagation,
    realistic_impact,
)
from src.aci.topology.types import EdgeAttrs, EdgeType, NodeAttrs, NodeStatus, NodeType


# ── Fixtures ─────────────────────────────────────────────────────────


def _build_linear_graph() -> InfraGraph:
    """A → B → C → D (linear chain)."""
    g = InfraGraph()
    for nid, nt in [("A", NodeType.VPC), ("B", NodeType.SUBNET),
                     ("C", NodeType.NAT_GATEWAY), ("D", NodeType.INTERNET_GATEWAY)]:
        g._add_node(nid, NodeAttrs(node_type=nt, label=nid, status=NodeStatus.HEALTHY))
    g._add_edge("A", "B", EdgeAttrs(edge_type=EdgeType.CONTAINS, label=""))
    g._add_edge("B", "C", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
    g._add_edge("C", "D", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
    return g


def _build_branching_graph() -> InfraGraph:
    """
    A → B → D
    A → C → E
    """
    g = InfraGraph()
    for nid in "ABCDE":
        g._add_node(nid, NodeAttrs(node_type=NodeType.SUBNET, label=nid, status=NodeStatus.HEALTHY))
    g._add_edge("A", "B", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
    g._add_edge("A", "C", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
    g._add_edge("B", "D", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
    g._add_edge("C", "E", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
    return g


def _build_k8s_graph() -> InfraGraph:
    """EKS cluster with deployment (replicas=3) and single-pod deployment."""
    g = InfraGraph()
    g._add_node("cluster", NodeAttrs(node_type=NodeType.EKS_CLUSTER, label="eks", status=NodeStatus.HEALTHY))
    g._add_node("ns/default", NodeAttrs(node_type=NodeType.K8S_NAMESPACE, label="default", status=NodeStatus.HEALTHY))
    g._add_node("deploy-multi", NodeAttrs(
        node_type=NodeType.K8S_DEPLOYMENT, label="web",
        status=NodeStatus.HEALTHY,
        raw={"replicas": 3, "ready_replicas": 3},
    ))
    g._add_node("deploy-single", NodeAttrs(
        node_type=NodeType.K8S_DEPLOYMENT, label="db",
        status=NodeStatus.HEALTHY,
        raw={"replicas": 1, "ready_replicas": 1},
    ))
    g._add_edge("cluster", "ns/default", EdgeAttrs(edge_type=EdgeType.CONTAINS, label=""))
    g._add_edge("ns/default", "deploy-multi", EdgeAttrs(edge_type=EdgeType.CONTAINS, label=""))
    g._add_edge("ns/default", "deploy-single", EdgeAttrs(edge_type=EdgeType.CONTAINS, label=""))
    return g


def _build_asg_graph() -> InfraGraph:
    """VPC → ASG (healthy) → EC2."""
    g = InfraGraph()
    g._add_node("vpc-1", NodeAttrs(node_type=NodeType.VPC, label="vpc", status=NodeStatus.HEALTHY))
    g._add_node("asg-1", NodeAttrs(
        node_type=NodeType.ASG, label="asg",
        status=NodeStatus.HEALTHY,
        raw={"healthy_count": 3, "desired_count": 3},
    ))
    g._add_node("ec2-1", NodeAttrs(node_type=NodeType.EC2_INSTANCE, label="i-1", status=NodeStatus.HEALTHY))
    g._add_edge("vpc-1", "asg-1", EdgeAttrs(edge_type=EdgeType.CONTAINS, label=""))
    g._add_edge("asg-1", "ec2-1", EdgeAttrs(edge_type=EdgeType.CONTAINS, label=""))
    return g


def _build_circuit_breaker_graph() -> InfraGraph:
    """A → B (circuit breaker open) → C."""
    g = InfraGraph()
    g._add_node("A", NodeAttrs(node_type=NodeType.SUBNET, label="A", status=NodeStatus.HEALTHY))
    g._add_node("B", NodeAttrs(
        node_type=NodeType.K8S_SERVICE, label="B",
        status=NodeStatus.HEALTHY,
        raw={"tags": {"circuit_breaker": "open"}},
    ))
    g._add_node("C", NodeAttrs(node_type=NodeType.K8S_SERVICE, label="C", status=NodeStatus.HEALTHY))
    g._add_edge("A", "B", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
    g._add_edge("B", "C", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
    return g


# ── Pessimistic mode tests ───────────────────────────────────────────


class TestPessimisticPropagation:
    def test_linear_all_affected(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC)
        assert set(result.affected_nodes) == {"A", "B", "C", "D"}
        assert result.mode == PropagationMode.PESSIMISTIC

    def test_linear_mid_node(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "B", PropagationMode.PESSIMISTIC)
        # B → C → D only (A is upstream, not downstream)
        assert "B" in result.affected_nodes
        assert "C" in result.affected_nodes
        assert "D" in result.affected_nodes
        assert "A" not in result.affected_nodes

    def test_branching(self):
        g = _build_branching_graph()
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC)
        assert set(result.affected_nodes) == {"A", "B", "C", "D", "E"}

    def test_leaf_node_only_self(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "D", PropagationMode.PESSIMISTIC)
        assert result.affected_nodes == ["D"]

    def test_all_weights_one(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC)
        for w in result.edge_weights.values():
            assert w == 1.0


class TestImpactScore:
    def test_full_graph_impact(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC)
        assert result.total_impact_score == 1.0  # 4/4 nodes

    def test_partial_impact(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "C", PropagationMode.PESSIMISTIC)
        # C + D = 2/4
        assert result.total_impact_score == 0.5

    def test_leaf_impact(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "D", PropagationMode.PESSIMISTIC)
        assert result.total_impact_score == 0.25  # 1/4


# ── Realistic mode tests ─────────────────────────────────────────────


class TestRealisticPropagation:
    def test_circuit_breaker_blocks(self):
        g = _build_circuit_breaker_graph()
        result = fault_propagation(g, "A", PropagationMode.REALISTIC)
        # B has circuit breaker open → weight 0.0 → below min_weight
        assert "C" not in result.affected_nodes
        # B itself should be blocked
        assert len(result.isolated_by) >= 1
        isolated_targets = [e.target for e in result.isolated_by]
        assert "B" in isolated_targets

    def test_asg_low_weight(self):
        g = _build_asg_graph()
        result = fault_propagation(g, "vpc-1", PropagationMode.REALISTIC)
        # ASG healthy (3/3) → weight 0.2, above default min_weight 0.1
        assert "asg-1" in result.affected_nodes
        w = result.edge_weights.get(("vpc-1", "asg-1"))
        assert w == 0.2

    def test_k8s_multi_replica_low_weight(self):
        g = _build_k8s_graph()
        result = fault_propagation(g, "ns/default", PropagationMode.REALISTIC)
        w_multi = result.edge_weights.get(("ns/default", "deploy-multi"))
        w_single = result.edge_weights.get(("ns/default", "deploy-single"))
        assert w_multi == 0.2   # 3 replicas → resilient
        assert w_single == 1.0  # 1 replica → SPOF

    def test_min_weight_filtering(self):
        g = _build_asg_graph()
        # Set min_weight higher than ASG weight (0.2)
        result = fault_propagation(g, "vpc-1", PropagationMode.REALISTIC, min_weight=0.5)
        assert "asg-1" not in result.affected_nodes
        assert any(e.target == "asg-1" for e in result.isolated_by)


# ── Edge weight inference ────────────────────────────────────────────


class TestEdgeWeightInference:
    def test_unknown_node(self):
        g = InfraGraph()
        g._add_node("A", NodeAttrs(node_type=NodeType.VPC, label="A"))
        w, reason = _infer_edge_weight(g, "A", "nonexistent")
        assert w == 1.0
        assert reason == "unknown-node"

    def test_circuit_breaker_open(self):
        g = InfraGraph()
        g._add_node("svc", NodeAttrs(
            node_type=NodeType.K8S_SERVICE, label="svc",
            raw={"tags": {"circuit_breaker": "open"}},
        ))
        w, reason = _infer_edge_weight(g, "x", "svc")
        assert w == 0.0
        assert "circuit-breaker" in reason

    def test_asg_healthy(self):
        g = InfraGraph()
        g._add_node("asg", NodeAttrs(
            node_type=NodeType.ASG, label="asg",
            raw={"healthy_count": 5, "desired_count": 5},
        ))
        w, reason = _infer_edge_weight(g, "x", "asg")
        assert w == 0.2

    def test_asg_degraded(self):
        g = InfraGraph()
        g._add_node("asg", NodeAttrs(
            node_type=NodeType.ASG, label="asg",
            raw={"healthy_count": 1, "desired_count": 3},
        ))
        w, reason = _infer_edge_weight(g, "x", "asg")
        assert w == 1.0
        assert "degraded" in reason

    def test_k8s_single_pod(self):
        g = InfraGraph()
        g._add_node("deploy", NodeAttrs(
            node_type=NodeType.K8S_DEPLOYMENT, label="d",
            raw={"replicas": 1, "ready_replicas": 1},
        ))
        w, reason = _infer_edge_weight(g, "x", "deploy")
        assert w == 1.0
        assert "single-pod" in reason

    def test_k8s_multi_replica(self):
        g = InfraGraph()
        g._add_node("deploy", NodeAttrs(
            node_type=NodeType.K8S_DEPLOYMENT, label="d",
            raw={"replicas": 3, "ready_replicas": 3},
        ))
        w, reason = _infer_edge_weight(g, "x", "deploy")
        assert w == 0.2

    def test_k8s_degraded_replicas(self):
        g = InfraGraph()
        g._add_node("deploy", NodeAttrs(
            node_type=NodeType.K8S_DEPLOYMENT, label="d",
            raw={"replicas": 3, "ready_replicas": 1},
        ))
        w, reason = _infer_edge_weight(g, "x", "deploy")
        assert w == 0.7
        assert "degraded" in reason

    def test_lb_multi_target(self):
        g = InfraGraph()
        g._add_node("alb", NodeAttrs(
            node_type=NodeType.LOAD_BALANCER, label="alb",
            raw={"healthy_target_count": 3},
        ))
        w, reason = _infer_edge_weight(g, "x", "alb")
        assert w == 0.3

    def test_lb_single_target(self):
        g = InfraGraph()
        g._add_node("alb", NodeAttrs(
            node_type=NodeType.LOAD_BALANCER, label="alb",
            raw={"healthy_target_count": 1},
        ))
        w, reason = _infer_edge_weight(g, "x", "alb")
        assert w == 1.0

    def test_nat_multi_az(self):
        g = InfraGraph()
        g._add_node("nat-1", NodeAttrs(
            node_type=NodeType.NAT_GATEWAY, label="nat-1",
            raw={"availability_zone": "us-east-1a"},
        ))
        g._add_node("nat-2", NodeAttrs(
            node_type=NodeType.NAT_GATEWAY, label="nat-2",
            raw={"availability_zone": "us-east-1b"},
        ))
        w, reason = _infer_edge_weight(g, "x", "nat-1")
        assert w == 0.4
        assert "multi-az" in reason

    def test_nat_single_az(self):
        g = InfraGraph()
        g._add_node("nat-1", NodeAttrs(
            node_type=NodeType.NAT_GATEWAY, label="nat-1",
            raw={"availability_zone": "us-east-1a"},
        ))
        w, reason = _infer_edge_weight(g, "x", "nat-1")
        assert w == 1.0
        assert "single-az" in reason

    def test_default_no_redundancy(self):
        g = InfraGraph()
        g._add_node("x", NodeAttrs(node_type=NodeType.VPC, label="x"))
        w, reason = _infer_edge_weight(g, "y", "x")
        assert w == 1.0
        assert "default" in reason

    def test_multi_az_siblings(self):
        """Generic multi-AZ detection for non-special node types."""
        g = InfraGraph()
        g._add_node("sub-1", NodeAttrs(
            node_type=NodeType.SUBNET, label="s1",
            raw={"availability_zone": "us-east-1a"},
        ))
        g._add_node("sub-2", NodeAttrs(
            node_type=NodeType.SUBNET, label="s2",
            raw={"availability_zone": "us-east-1b"},
        ))
        w, reason = _infer_edge_weight(g, "x", "sub-1")
        assert w == 0.3
        assert "multi-az" in reason


# ── Critical path ────────────────────────────────────────────────────


class TestCriticalPath:
    def test_linear(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC)
        assert result.critical_path == ["A", "B", "C", "D"]

    def test_branching_picks_longer(self):
        """With equal weights, picks the path with more hops."""
        g = _build_branching_graph()
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC)
        # Both branches are depth 2; critical path should be length 3
        assert len(result.critical_path) == 3
        assert result.critical_path[0] == "A"

    def test_empty_tree(self):
        path = _find_critical_path({}, {}, "X")
        assert path == ["X"]


# ── Max depth ────────────────────────────────────────────────────────


class TestMaxDepth:
    def test_limits_propagation(self):
        g = _build_linear_graph()  # A→B→C→D (depth 3)
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC, max_depth=1)
        # Depth 0=A, depth 1=B only
        assert "A" in result.affected_nodes
        assert "B" in result.affected_nodes
        assert "C" not in result.affected_nodes
        assert "D" not in result.affected_nodes

    def test_depth_zero_only_origin(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC, max_depth=0)
        assert result.affected_nodes == ["A"]


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_missing_node(self):
        g = _build_linear_graph()
        result = fault_propagation(g, "nonexistent", PropagationMode.PESSIMISTIC)
        assert result.affected_nodes == []
        assert result.total_impact_score == 0.0

    def test_empty_graph(self):
        g = InfraGraph()
        result = fault_propagation(g, "X", PropagationMode.PESSIMISTIC)
        assert result.affected_nodes == []

    def test_isolated_node(self):
        g = InfraGraph()
        g._add_node("alone", NodeAttrs(node_type=NodeType.VPC, label="alone"))
        result = fault_propagation(g, "alone", PropagationMode.PESSIMISTIC)
        assert result.affected_nodes == ["alone"]
        assert result.total_impact_score == 1.0

    def test_propagation_tree_structure(self):
        g = _build_branching_graph()
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC)
        assert "B" in result.propagation_tree.get("A", [])
        assert "C" in result.propagation_tree.get("A", [])
        assert "D" in result.propagation_tree.get("B", [])
        assert "E" in result.propagation_tree.get("C", [])


# ── Convenience helpers ──────────────────────────────────────────────


class TestConvenienceHelpers:
    def test_blast_radius(self):
        g = _build_linear_graph()
        result = blast_radius(g, "A")
        assert result.mode == PropagationMode.PESSIMISTIC
        assert len(result.affected_nodes) == 4

    def test_realistic_impact(self):
        g = _build_asg_graph()
        result = realistic_impact(g, "vpc-1")
        assert result.mode == PropagationMode.REALISTIC
        assert "asg-1" in result.affected_nodes


# ── Cycle handling ───────────────────────────────────────────────────


class TestCycleHandling:
    def test_does_not_loop_on_cycle(self):
        """BFS visited set should prevent infinite loops."""
        g = InfraGraph()
        g._add_node("A", NodeAttrs(node_type=NodeType.SUBNET, label="A"))
        g._add_node("B", NodeAttrs(node_type=NodeType.SUBNET, label="B"))
        g._add_node("C", NodeAttrs(node_type=NodeType.SUBNET, label="C"))
        g._add_edge("A", "B", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
        g._add_edge("B", "C", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
        g._add_edge("C", "A", EdgeAttrs(edge_type=EdgeType.ROUTES_TO, label=""))
        result = fault_propagation(g, "A", PropagationMode.PESSIMISTIC)
        assert set(result.affected_nodes) == {"A", "B", "C"}
