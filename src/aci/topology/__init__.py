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
    VpcTopology,
    RegionTopology,
)
from .engine import InfraGraph
from .propagation import (
    PropagationMode,
    PropagationEdge,
    PropagationResult,
    PropagationWave,
    WaveEntry,
    DegradationFactor,
    ImpactLevel,
    fault_propagation,
    blast_radius,
    realistic_impact,
)
from .delta import (
    TopologyChange,
    DeltaStore,
    capture_delta,
    format_recent_changes,
    get_delta_store,
)
from .cache import GraphCache, graph_cache

__all__ = [
    # engine
    "InfraGraph",
    # types
    "NodeType",
    "EdgeType",
    "NodeStatus",
    "NodeAttrs",
    "EdgeAttrs",
    "GraphNode",
    "GraphEdge",
    "GraphMetadata",
    "SerializedGraph",
    "VpcTopology",
    "RegionTopology",
    # propagation (NEW)
    "PropagationMode",
    "PropagationEdge",
    "PropagationResult",
    "PropagationWave",
    "WaveEntry",
    "DegradationFactor",
    "ImpactLevel",
    "fault_propagation",
    "blast_radius",
    "realistic_impact",
    # delta (NEW)
    "TopologyChange",
    "DeltaStore",
    "capture_delta",
    "format_recent_changes",
    "get_delta_store",
    # cache (NEW)
    "GraphCache",
    "graph_cache",
]
