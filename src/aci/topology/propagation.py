"""Fault Propagation Engine — weighted blast-radius analysis.

Computes fault propagation from a failed node through the infrastructure
graph, using edge weights inferred from redundancy/degradation metadata.

Two modes:
  - PESSIMISTIC: All downstream nodes affected (weight=1.0 everywhere).
  - REALISTIC:   Edge weights reflect multi-AZ, ASG, replicas, circuit breakers.

Ref: docs/designs/GRAPH_FAULT_PROPAGATION_DESIGN.md §2
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .engine import InfraGraph
from .types import EdgeType, NodeType

logger = logging.getLogger(__name__)


# ── Data types ───────────────────────────────────────────────────────


class PropagationMode(str, Enum):
    """Fault propagation analysis mode."""

    PESSIMISTIC = "pessimistic"   # Assume all paths propagate (blast radius)
    REALISTIC = "realistic"       # Account for redundancy / degradation


@dataclass
class PropagationEdge:
    """Propagation metadata for a single edge."""

    source: str
    target: str
    weight: float              # 0.0 = fully isolated, 1.0 = fully propagates
    reason: str                # e.g. "multi-az", "asg-healthy", "circuit-breaker-open"


class ImpactLevel(str, Enum):
    """Per-node impact severity after propagation."""

    FAILED = "failed"
    DEGRADED = "degraded"
    AT_RISK = "at_risk"
    HEALTHY = "healthy"


@dataclass
class WaveEntry:
    """A single node affected in a propagation wave."""

    node_id: str
    node_type: str
    impact_level: ImpactLevel
    reason: str


@dataclass
class PropagationWave:
    """One hop of failure spread."""

    depth: int
    affected: list[WaveEntry] = field(default_factory=list)
    edge_cuts: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DegradationFactor:
    """A protective capability that reduces impact."""

    factor_type: str
    node_id: str
    description: str
    mitigation_weight: float


@dataclass
class PropagationResult:
    """Result of fault propagation analysis."""

    origin_node: str
    mode: PropagationMode
    affected_nodes: list[str] = field(default_factory=list)
    propagation_tree: dict[str, list[str]] = field(default_factory=dict)
    edge_weights: dict[tuple[str, str], float] = field(default_factory=dict)
    total_impact_score: float = 0.0          # 0.0-1.0 normalised
    critical_path: list[str] = field(default_factory=list)
    isolated_by: list[PropagationEdge] = field(default_factory=list)
    waves: list[PropagationWave] = field(default_factory=list)
    degradation_factors: list[DegradationFactor] = field(default_factory=list)
    total_failed: int = 0
    total_degraded: int = 0
    total_at_risk: int = 0
    max_depth_reached: int = 0
    propagation_time_ms: int = 0
    rca_context_block: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API / telemetry."""
        return {
            "root_failure": {"id": self.origin_node, "type": ""},
            "mode": self.mode.value,
            "waves": [
                {
                    "depth": w.depth,
                    "affected": [
                        {"node_id": e.node_id, "node_type": e.node_type,
                         "impact_level": e.impact_level.value, "reason": e.reason}
                        for e in w.affected
                    ],
                    "edge_cuts": w.edge_cuts,
                }
                for w in self.waves
            ],
            "summary": {
                "total_affected": len(self.affected_nodes),
                "total_failed": self.total_failed,
                "total_degraded": self.total_degraded,
                "total_at_risk": self.total_at_risk,
                "blast_radius_score": round(self.total_impact_score, 3),
                "max_depth": self.max_depth_reached,
            },
            "degradation_factors": [
                {"type": d.factor_type, "node": d.node_id,
                 "desc": d.description, "weight": d.mitigation_weight}
                for d in self.degradation_factors
            ],
            "propagation_time_ms": self.propagation_time_ms,
            "rca_context_block": self.rca_context_block,
            "critical_path": self.critical_path,
            "affected_nodes": self.affected_nodes,
            "total_impact_score": self.total_impact_score,
        }


# ── Edge weight inference ────────────────────────────────────────────


def _infer_edge_weight(
    graph: InfraGraph,
    source: str,
    target: str,
) -> tuple[float, str]:
    """Infer propagation weight for an edge based on target node's redundancy.

    Convention-over-configuration: automatically detect multi-AZ, ASG health,
    circuit breaker, K8s replica count, etc.

    Returns ``(weight, reason)`` — weight in [0.0, 1.0], reason for audit.
    """
    target_attrs = graph.get_node(target)
    if not target_attrs:
        return 1.0, "unknown-node"

    node_type = target_attrs.get("node_type")
    raw = target_attrs.get("raw", {})
    tags = raw.get("tags", {}) if isinstance(raw, dict) else {}

    # ── Circuit breaker (highest priority — fully blocks) ────────────
    if tags.get("circuit_breaker") == "open":
        return 0.0, "circuit-breaker-open"

    # ── ASG with healthy instances ───────────────────────────────────
    if node_type == NodeType.ASG:
        healthy = raw.get("healthy_count", 0)
        desired = raw.get("desired_count", 1)
        if healthy >= desired and desired > 1:
            return 0.2, f"asg-healthy: {healthy}/{desired}"
        return 1.0, f"asg-degraded: {healthy}/{desired}"

    # ── K8s Deployment replica count ─────────────────────────────────
    if node_type == NodeType.K8S_DEPLOYMENT:
        ready = raw.get("ready_replicas", 0)
        desired = raw.get("replicas", raw.get("desired_replicas", 1))
        if desired <= 1:
            return 1.0, "k8s-single-pod"
        if ready >= desired:
            return 0.2, f"k8s-replicas: {ready}/{desired}"
        return 0.7, f"k8s-degraded: {ready}/{desired}"

    # ── Load balancer with multiple healthy targets ──────────────────
    if node_type == NodeType.LOAD_BALANCER:
        healthy_targets = raw.get("healthy_target_count", 0)
        if healthy_targets >= 2:
            return 0.3, f"lb-multi-target: {healthy_targets}"
        return 1.0, f"lb-targets: {healthy_targets}"

    # ── NAT Gateway — check AZ redundancy ────────────────────────────
    if node_type == NodeType.NAT_GATEWAY:
        nat_nodes = graph.get_nodes_by_type(NodeType.NAT_GATEWAY)
        nat_azs = set()
        for n in nat_nodes:
            nd = graph.get_node(n)
            if nd:
                az = nd.get("raw", {}).get("availability_zone") or nd.get("raw", {}).get("az", "")
                if az:
                    nat_azs.add(az)
        if len(nat_azs) >= 2:
            return 0.4, f"nat-multi-az: {len(nat_azs)} AZs"
        return 1.0, "nat-single-az"

    # ── Multi-AZ siblings (generic) ──────────────────────────────────
    if node_type:
        siblings = graph.get_nodes_by_type(node_type)
        if len(siblings) > 1:
            azs: set[str] = set()
            for s in siblings:
                nd = graph.get_node(s)
                if nd:
                    az = (
                        nd.get("raw", {}).get("availability_zone")
                        or nd.get("raw", {}).get("az", "")
                    )
                    if az:
                        azs.add(az)
            if len(azs) >= 2:
                return 0.3, f"multi-az: {len(azs)} AZs"

    return 1.0, "default-no-redundancy"


# ── Critical path extraction ────────────────────────────────────────


def _find_critical_path(
    tree: dict[str, list[str]],
    weights: dict[tuple[str, str], float],
    origin: str,
) -> list[str]:
    """Find the path with the highest cumulative weight from *origin*.

    Uses DFS over the propagation tree.  Returns the longest-weight path
    which represents the worst-case propagation chain.
    """
    best_path: list[str] = [origin]
    best_weight = 0.0

    stack: list[tuple[str, list[str], float]] = [(origin, [origin], 0.0)]
    while stack:
        node, path, cum_weight = stack.pop()
        children = tree.get(node, [])
        if not children:
            # leaf — check if this is the worst path so far
            if cum_weight > best_weight:
                best_weight = cum_weight
                best_path = path
            continue
        for child in children:
            w = weights.get((node, child), 1.0)
            stack.append((child, path + [child], cum_weight + w))

    return best_path


# ── Main algorithm ───────────────────────────────────────────────────


def fault_propagation(
    graph: InfraGraph,
    failed_node_id: str,
    mode: PropagationMode = PropagationMode.PESSIMISTIC,
    max_depth: int = 10,
    min_weight: float = 0.1,
) -> PropagationResult:
    """Compute fault propagation from a failed node.

    Args:
        graph: The infrastructure graph.
        failed_node_id: Node where the fault originates.
        mode: ``PESSIMISTIC`` (all edges weight=1.0) or ``REALISTIC``
              (weights inferred from redundancy metadata).
        max_depth: Maximum BFS depth.
        min_weight: Edges below this weight are treated as isolated
                    (realistic mode only).

    Returns:
        :class:`PropagationResult` with affected nodes, propagation tree,
        edge weights, impact score, critical path, waves, and rca_context_block.
    """
    import time as _time

    t0 = _time.monotonic()
    g = graph.graph

    if failed_node_id not in g:
        return PropagationResult(
            origin_node=failed_node_id,
            mode=mode,
        )

    visited: dict[str, int] = {}          # node_id → depth
    node_impact: dict[str, ImpactLevel] = {}  # node_id → impact level
    queue: deque[tuple[str, int]] = deque()
    queue.append((failed_node_id, 0))

    tree: dict[str, list[str]] = {}       # parent → [children]
    weights: dict[tuple[str, str], float] = {}
    isolated: list[PropagationEdge] = []
    all_degradation_factors: list[DegradationFactor] = []

    # wave tracking: depth → list of (node_id, impact, reason)
    wave_entries: dict[int, list[WaveEntry]] = {}
    wave_edge_cuts: dict[int, list[dict[str, str]]] = {}

    while queue:
        node, depth = queue.popleft()
        if node in visited or depth > max_depth:
            continue
        visited[node] = depth

        # Root failure is always FAILED
        if node == failed_node_id:
            node_impact[node] = ImpactLevel.FAILED
            nd = g.nodes.get(node, {})
            wave_entries.setdefault(0, []).append(WaveEntry(
                node_id=node,
                node_type=str(nd.get("node_type", "")),
                impact_level=ImpactLevel.FAILED,
                reason="root failure",
            ))

        # Outgoing edges (fault propagates downstream)
        # Plus reverse traversal for bidirectional edge types:
        #   PEERS_WITH, ASSOCIATED_WITH, EXPOSES (per Architect §3.1.2 direction table)
        _BIDIRECTIONAL = frozenset({
            EdgeType.PEERS_WITH,
            EdgeType.ASSOCIATED_WITH,
            EdgeType.EXPOSES,
        })

        neighbors: list[str] = []
        for _, neighbor in g.out_edges(node):
            neighbors.append(neighbor)
        # Reverse edges for bidirectional types
        for predecessor, _ in g.in_edges(node):
            if predecessor in visited:
                continue
            edge_data = g.edges.get((predecessor, node), {})
            et_raw = edge_data.get("edge_type")
            # Compare as string or enum
            if et_raw in _BIDIRECTIONAL or str(et_raw) in {e.value for e in _BIDIRECTIONAL}:
                neighbors.append(predecessor)

        for neighbor in neighbors:
            if neighbor in visited:
                continue

            if mode == PropagationMode.PESSIMISTIC:
                w, reason = 1.0, "pessimistic"
            else:
                w, reason = _infer_edge_weight(graph, node, neighbor)

            weights[(node, neighbor)] = w

            if mode == PropagationMode.REALISTIC and w < min_weight:
                isolated.append(PropagationEdge(node, neighbor, w, reason))
                # Record isolation as degradation factor
                all_degradation_factors.append(DegradationFactor(
                    factor_type=reason.split(":")[0] if ":" in reason else reason,
                    node_id=neighbor,
                    description=reason,
                    mitigation_weight=1.0 - w,
                ))
                continue

            # Determine impact level for this neighbor
            if mode == PropagationMode.REALISTIC:
                if w >= 0.8:
                    impact = ImpactLevel.FAILED
                elif w >= 0.4:
                    impact = ImpactLevel.DEGRADED
                else:
                    impact = ImpactLevel.AT_RISK
                # Collect degradation factor if not full propagation
                if w < 1.0:
                    all_degradation_factors.append(DegradationFactor(
                        factor_type=reason.split(":")[0] if ":" in reason else reason,
                        node_id=neighbor,
                        description=reason,
                        mitigation_weight=1.0 - w,
                    ))
            else:
                impact = ImpactLevel.FAILED

            node_impact[neighbor] = impact
            nd = g.nodes.get(neighbor, {})
            child_depth = depth + 1
            wave_entries.setdefault(child_depth, []).append(WaveEntry(
                node_id=neighbor,
                node_type=str(nd.get("node_type", "")),
                impact_level=impact,
                reason=reason,
            ))

            # Track edge cuts for waves
            edge_data = g.edges.get((node, neighbor), {})
            wave_edge_cuts.setdefault(child_depth, []).append({
                "source": node,
                "target": neighbor,
                "edge_type": str(edge_data.get("edge_type", "")),
            })

            tree.setdefault(node, []).append(neighbor)
            queue.append((neighbor, child_depth))

    # Build waves list
    waves: list[PropagationWave] = []
    for d in sorted(wave_entries.keys()):
        waves.append(PropagationWave(
            depth=d,
            affected=wave_entries[d],
            edge_cuts=wave_edge_cuts.get(d, []),
        ))

    # Critical path (highest cumulative weight)
    critical_path = _find_critical_path(tree, weights, failed_node_id)

    # Normalised impact score
    total_nodes = g.number_of_nodes()
    impact_score = len(visited) / total_nodes if total_nodes > 0 else 0.0

    # Impact counts
    n_failed = sum(1 for v in node_impact.values() if v == ImpactLevel.FAILED)
    n_degraded = sum(1 for v in node_impact.values() if v == ImpactLevel.DEGRADED)
    n_at_risk = sum(1 for v in node_impact.values() if v == ImpactLevel.AT_RISK)
    max_depth_reached = max(visited.values()) if visited else 0

    elapsed_ms = int((_time.monotonic() - t0) * 1000)

    result = PropagationResult(
        origin_node=failed_node_id,
        mode=mode,
        affected_nodes=sorted(visited.keys(), key=lambda n: visited[n]),
        propagation_tree=tree,
        edge_weights=weights,
        total_impact_score=round(impact_score, 4),
        critical_path=critical_path,
        isolated_by=isolated,
        waves=waves,
        degradation_factors=all_degradation_factors,
        total_failed=n_failed,
        total_degraded=n_degraded,
        total_at_risk=n_at_risk,
        max_depth_reached=max_depth_reached,
        propagation_time_ms=elapsed_ms,
    )

    # Render RCA context block
    result.rca_context_block = _render_rca_context_block(result, graph)

    return result


def _render_rca_context_block(
    result: PropagationResult,
    graph: InfraGraph,
    max_chars: int = 2000,
) -> str:
    """Render a human-readable markdown block for RCA prompt injection.

    Truncates to *max_chars* with progressive detail reduction.
    """
    lines: list[str] = []
    lines.append("## 🗺️ Network Topology Context")
    lines.append("")

    # Root info
    nd = graph.graph.nodes.get(result.origin_node, {})
    node_type_label = str(nd.get("node_type", "unknown"))
    lines.append(f"**Failed Resource**: {result.origin_node} ({node_type_label})")
    lines.append(f"**Propagation Mode**: {result.mode.value}")
    lines.append(
        f"**Blast Radius**: {result.total_impact_score:.2f} "
        f"({int(result.total_impact_score * 100)}% of graph affected)"
    )
    lines.append("")

    # Waves (show up to 3)
    for wave in result.waves[:3]:
        if wave.depth == 0:
            lines.append("### Wave 0 (Root Failure)")
        elif wave.depth == 1:
            lines.append("### Wave 1 (Direct Impact)")
        else:
            lines.append(f"### Wave {wave.depth} (Cascading)")

        for entry in wave.affected[:5]:
            lines.append(
                f"- {entry.node_id} [{entry.node_type}] — "
                f"{entry.impact_level.value.upper()}"
                f"{' (' + entry.reason + ')' if entry.reason != 'root failure' and entry.reason != 'pessimistic' else ''}"
            )
        if len(wave.affected) > 5:
            lines.append(f"- ... and {len(wave.affected) - 5} more nodes")
        lines.append("")

    # Summary for deeper waves
    if len(result.waves) > 3:
        deeper_count = sum(len(w.affected) for w in result.waves[3:])
        lines.append(f"*... {len(result.waves) - 3} more waves ({deeper_count} additional nodes)*")
        lines.append("")

    # Degradation factors
    if result.degradation_factors:
        lines.append("### Degradation Factors")
        seen: set[str] = set()
        for df in result.degradation_factors[:5]:
            key = f"{df.factor_type}:{df.node_id}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"- {df.factor_type} on {df.node_id}: "
                f"weight={df.mitigation_weight:.1f} ({df.description})"
            )
        lines.append("")

    # Summary line
    lines.append(
        f"**Summary**: {result.total_failed} failed, "
        f"{result.total_degraded} degraded, "
        f"{result.total_at_risk} at-risk, "
        f"max depth={result.max_depth_reached}, "
        f"propagation={result.propagation_time_ms}ms"
    )

    text = "\n".join(lines)

    # Truncate if over budget
    if len(text) > max_chars:
        text = text[:max_chars - 20] + "\n\n*[truncated]*"

    return text


# ── Convenience helpers ──────────────────────────────────────────────


def blast_radius(
    graph: InfraGraph,
    failed_node_id: str,
) -> PropagationResult:
    """Shortcut: pessimistic fault propagation (worst-case blast radius)."""
    return fault_propagation(graph, failed_node_id, PropagationMode.PESSIMISTIC)


def realistic_impact(
    graph: InfraGraph,
    failed_node_id: str,
    min_weight: float = 0.1,
) -> PropagationResult:
    """Shortcut: realistic fault propagation with redundancy awareness."""
    return fault_propagation(
        graph, failed_node_id, PropagationMode.REALISTIC, min_weight=min_weight,
    )
