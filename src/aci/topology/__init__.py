"""ACI Topology Engine — Infrastructure graph modeling and analysis.

Provides NetworkX-backed graph engine for AWS VPC / K8s topology,
with algorithms for reachability, impact analysis, anomaly detection,
and network segmentation.

Usage:
    from src.aci.topology import InfraGraph, NodeType, EdgeType
    from src.aci.topology.algorithms import can_reach_internet, detect_anomalies
    from src.aci.topology.api import router as topology_router
"""

from .types import (
    NodeType,
    EdgeType,
    NodeStatus,
    NodeAttrs,
    EdgeAttrs,
    GraphNode,
    GraphEdge,
    GraphMetadata,
    SerializedGraph,
)
from .engine import InfraGraph

__all__ = [
    "InfraGraph",
    "NodeType",
    "EdgeType",
    "NodeStatus",
    "NodeAttrs",
    "EdgeAttrs",
    "GraphNode",
    "GraphEdge",
    "GraphMetadata",
    "SerializedGraph",
]
