"""Graph serializers — convert InfraGraph to ReactFlow JSON and agent summaries.

Adapted from agenticops-chat. Extended with K8s node type mappings.
"""

from __future__ import annotations

from typing import Any, Literal

from .engine import InfraGraph
from .types import (
    EdgeType,
    GraphEdge,
    GraphMetadata,
    GraphNode,
    NodeStatus,
    NodeType,
    SerializedGraph,
)

# ── ReactFlow type mapping ───────────────────────────────────────────

NODE_TYPE_TO_REACTFLOW: dict[str, str] = {
    # AWS Networking
    NodeType.SUBNET: "subnetNode",
    NodeType.INTERNET_GATEWAY: "igwNode",
    NodeType.NAT_GATEWAY: "natNode",
    NodeType.TRANSIT_GATEWAY: "tgwNode",
    NodeType.TGW_ATTACHMENT: "tgwNode",
    NodeType.PEERING: "peeringNode",
    NodeType.VPC_ENDPOINT: "endpointNode",
    NodeType.ROUTE_TABLE: "routeTableNode",
    NodeType.SECURITY_GROUP: "sgNode",
    NodeType.LOAD_BALANCER: "lbNode",
    NodeType.VPC: "vpcGroupNode",
    # AWS Compute
    NodeType.EC2_INSTANCE: "ec2Node",
    NodeType.RDS_INSTANCE: "rdsNode",
    NodeType.LAMBDA_FUNCTION: "lambdaNode",
    NodeType.EKS_CLUSTER: "eksNode",
    NodeType.ASG: "asgNode",
    # K8s
    NodeType.K8S_NAMESPACE: "namespaceNode",
    NodeType.K8S_DEPLOYMENT: "deploymentNode",
    NodeType.K8S_SERVICE: "serviceNode",
    NodeType.K8S_POD: "podNode",
    NodeType.K8S_NODE: "workerNode",
    NodeType.K8S_INGRESS: "ingressNode",
}

REGION_NODE_TYPE_TO_REACTFLOW: dict[str, str] = {
    NodeType.VPC: "vpcGroupNode",
    NodeType.TRANSIT_GATEWAY: "tgwHubNode",
}

# ── Rank constants (dagre layer assignment) ──────────────────────────

RANK_EXTERNAL = 0
RANK_PUBLIC = 1
RANK_NAT = 2
RANK_PRIVATE = 3
RANK_ENDPOINT = 4

RANK_BY_NODE_TYPE: dict[str, int] = {
    NodeType.INTERNET_GATEWAY: RANK_EXTERNAL,
    NodeType.TGW_ATTACHMENT: RANK_EXTERNAL,
    NodeType.TRANSIT_GATEWAY: RANK_EXTERNAL,
    NodeType.PEERING: RANK_EXTERNAL,
    NodeType.NAT_GATEWAY: RANK_NAT,
    NodeType.VPC_ENDPOINT: RANK_ENDPOINT,
}


# ── Edge style mapping ───────────────────────────────────────────────

def _edge_style(edge_type: str, state: str) -> str:
    if state == "blackhole":
        return "blackhole"
    if edge_type == EdgeType.HOSTED_IN:
        return "dashed"
    if edge_type == EdgeType.REFERENCES:
        return "dotted"
    return "solid"


# ── Serializers ──────────────────────────────────────────────────────


def to_reactflow(
    graph: InfraGraph,
    view: Literal["vpc", "region"] = "vpc",
) -> SerializedGraph:
    """Convert InfraGraph to ReactFlow-compatible JSON."""
    g = graph.graph
    type_map = REGION_NODE_TYPE_TO_REACTFLOW if view == "region" else NODE_TYPE_TO_REACTFLOW

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    node_type_counts: dict[str, int] = {}
    anomaly_count = 0

    # Build subnet → rank mapping for route tables
    subnet_rtb_rank: dict[str, int] = {}
    for node_id, data in g.nodes(data=True):
        if data.get("node_type") == NodeType.SUBNET:
            raw = data.get("raw", {})
            subnet_type = raw.get("type", "private")
            rank = RANK_PUBLIC if subnet_type == "public" else RANK_PRIVATE
            for _, target, edata in g.out_edges(node_id, data=True):
                if edata.get("edge_type") == EdgeType.ASSOCIATED_WITH:
                    current = subnet_rtb_rank.get(target)
                    if current is None or rank < current:
                        subnet_rtb_rank[target] = rank

    # Nodes
    for node_id, data in g.nodes(data=True):
        node_type = data.get("node_type", "")
        rf_type = type_map.get(node_type, "default")
        status = data.get("status", NodeStatus.UNKNOWN)
        raw = data.get("raw", {})

        if node_type == NodeType.SUBNET:
            subnet_type = raw.get("type", "private")
            rank = RANK_PUBLIC if subnet_type == "public" else RANK_PRIVATE
        elif node_type == NodeType.ROUTE_TABLE:
            rank = subnet_rtb_rank.get(node_id, RANK_PRIVATE)
        else:
            rank = RANK_BY_NODE_TYPE.get(node_type, RANK_PRIVATE)

        has_issue = status == NodeStatus.ERROR

        node_data: dict[str, Any] = {
            "label": data.get("label", node_id),
            "resourceType": data.get("resource_type", ""),
            "raw": raw,
            "status": status,
            "hasIssue": has_issue,
            "rank": rank,
        }

        if view == "region" and node_type == NodeType.VPC:
            node_data.update({
                "vpcId": raw.get("vpc_id", node_id),
                "cidr": raw.get("cidr_block", raw.get("cidr", "")),
                "subnetCount": raw.get("subnet_count", 0),
                "isDefault": raw.get("is_default", False),
                "state": raw.get("state", "available"),
            })
        elif view == "region" and node_type == NodeType.TRANSIT_GATEWAY:
            node_data.update({
                "tgwId": raw.get("transit_gateway_id", node_id),
                "state": raw.get("state", "unknown"),
                "attachmentCount": len(raw.get("attachments", [])),
            })

        nodes.append(GraphNode(id=node_id, type=rf_type, data=node_data))

        nt_str = str(node_type)
        node_type_counts[nt_str] = node_type_counts.get(nt_str, 0) + 1
        if has_issue:
            anomaly_count += 1

    # Edges
    for u, v, data in g.edges(data=True):
        edge_type = data.get("edge_type", "")
        state = data.get("state", "")
        style = _edge_style(edge_type, state)
        label = data.get("label", "")

        if view == "vpc" and edge_type in (EdgeType.CONTAINS,):
            continue

        edges.append(GraphEdge(
            id=f"e-{u}-{v}-{label}".replace("/", "_"),
            source=u,
            target=v,
            data={"label": label, "style": style, "edgeType": edge_type},
        ))

    metadata = GraphMetadata(
        node_count=len(nodes),
        edge_count=len(edges),
        node_type_counts=node_type_counts,
        has_anomalies=anomaly_count > 0,
        anomaly_count=anomaly_count,
    )

    return SerializedGraph(nodes=nodes, edges=edges, metadata=metadata)


# ── Propagation overlay for ReactFlow ────────────────────────────────


def annotate_propagation_overlay(
    rf: SerializedGraph,
    prop_result: "PropagationResult",
) -> SerializedGraph:
    """Overlay fault propagation data onto an existing ReactFlow graph.

    Adds ``propagation`` key to each affected node's data dict with:
      - ``wave``: BFS depth (0 = root failure)
      - ``impact``: cumulative weight at that node
      - ``is_origin``: True for the root failure node

    Adds ``propagation`` key to affected edges with:
      - ``weight``: edge propagation weight
      - ``on_critical_path``: True if on the critical path

    Also sets ``metadata.propagation`` summary.
    """
    from .propagation import PropagationResult  # noqa: F811

    # Build lookup: node_id → wave info
    node_waves: dict[str, dict] = {}
    for wave in prop_result.waves:
        for entry in wave.affected:
            node_waves[entry.node_id] = {
                "wave": wave.depth,
                "impact": entry.cumulative_weight if hasattr(entry, "cumulative_weight") else 1.0,
                "impact_level": entry.impact_level.value if hasattr(entry.impact_level, "value") else str(entry.impact_level),
                "is_origin": wave.depth == 0,
            }

    # Build edge lookup from edge_weights
    prop_edges: dict[tuple[str, str], dict] = {}
    for (src, tgt), weight in prop_result.edge_weights.items():
        prop_edges[(src, tgt)] = {
            "weight": weight,
            "on_critical_path": False,
        }

    # Mark critical path edges
    cp = prop_result.critical_path
    for i in range(len(cp) - 1):
        key = (cp[i], cp[i + 1])
        if key in prop_edges:
            prop_edges[key]["on_critical_path"] = True

    # Annotate nodes
    for node in rf.nodes:
        if node.id in node_waves:
            node.data["propagation"] = node_waves[node.id]

    # Annotate edges
    for edge in rf.edges:
        key = (edge.source, edge.target)
        rev_key = (edge.target, edge.source)
        if key in prop_edges:
            edge.data["propagation"] = prop_edges[key]
        elif rev_key in prop_edges:
            edge.data["propagation"] = prop_edges[rev_key]

    # Add propagation summary to metadata
    rf.metadata.propagation = {
        "origin": prop_result.origin_node,
        "mode": prop_result.mode.value if hasattr(prop_result.mode, "value") else str(prop_result.mode),
        "blast_radius": prop_result.total_impact_score,
        "affected_count": len(prop_result.affected_nodes),
        "wave_count": len(prop_result.waves),
    }

    return rf


def to_agent_summary(graph: InfraGraph) -> str:
    """Convert InfraGraph to an agent-friendly text summary."""
    g = graph.graph
    lines: list[str] = []

    type_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        nt = data.get("node_type", "unknown")
        type_counts[nt] = type_counts.get(nt, 0) + 1

    lines.append(f"Graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
    lines.append("Node types:")
    for nt, count in sorted(type_counts.items()):
        lines.append(f"  {nt}: {count}")

    status_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        s = data.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    lines.append("Status:")
    for s, count in sorted(status_counts.items()):
        lines.append(f"  {s}: {count}")

    blackholes = [
        (u, v, d) for u, v, d in g.edges(data=True)
        if d.get("state") == "blackhole"
    ]
    if blackholes:
        lines.append(f"Blackhole routes: {len(blackholes)}")
        for u, v, d in blackholes:
            lines.append(f"  {u} -> {v} ({d.get('label', '')})")

    error_nodes = [
        (n, d) for n, d in g.nodes(data=True)
        if d.get("status") == NodeStatus.ERROR
    ]
    if error_nodes:
        lines.append(f"Error nodes: {len(error_nodes)}")
        for n, d in error_nodes:
            lines.append(f"  {n} ({d.get('label', '')}) - {d.get('node_type', '')}")

    return "\n".join(lines)
