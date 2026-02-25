"""Topology type definitions for infrastructure graph modeling.

Adapted from agenticops-chat graph module for the ACI subsystem.
Extends NodeType to cover K8s + AWS compute resources (not just networking).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """Infrastructure resource types represented as graph nodes."""

    # AWS Networking
    VPC = "vpc"
    SUBNET = "subnet"
    ROUTE_TABLE = "route_table"
    INTERNET_GATEWAY = "igw"
    NAT_GATEWAY = "nat"
    TRANSIT_GATEWAY = "tgw"
    TGW_ATTACHMENT = "tgw_attachment"
    PEERING = "peering"
    VPC_ENDPOINT = "endpoint"
    SECURITY_GROUP = "security_group"
    LOAD_BALANCER = "load_balancer"

    # AWS Compute / Services (new)
    EC2_INSTANCE = "ec2_instance"
    RDS_INSTANCE = "rds_instance"
    LAMBDA_FUNCTION = "lambda_function"
    EKS_CLUSTER = "eks_cluster"
    ASG = "auto_scaling_group"

    # Kubernetes (new)
    K8S_NAMESPACE = "k8s_namespace"
    K8S_DEPLOYMENT = "k8s_deployment"
    K8S_SERVICE = "k8s_service"
    K8S_POD = "k8s_pod"
    K8S_NODE = "k8s_node"
    K8S_INGRESS = "k8s_ingress"


class EdgeType(str, Enum):
    """Relationship types between infrastructure nodes."""

    CONTAINS = "contains"
    ROUTES_TO = "routes_to"
    ASSOCIATED_WITH = "associated"
    ATTACHED_TO = "attached_to"
    PEERS_WITH = "peers_with"
    HOSTED_IN = "hosted_in"
    REFERENCES = "references"
    SERVES = "serves"

    # K8s relationships (new)
    EXPOSES = "exposes"          # Service → Deployment
    RUNS_ON = "runs_on"          # Pod → Node
    SELECTS = "selects"          # Service → Pod
    DEPENDS_ON = "depends_on"    # Service → Service (inferred)


class NodeStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class NodeAttrs(BaseModel):
    """Attributes stored on graph nodes."""

    node_type: NodeType
    label: str
    status: NodeStatus = NodeStatus.UNKNOWN
    resource_type: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class EdgeAttrs(BaseModel):
    """Attributes stored on graph edges."""

    edge_type: EdgeType
    label: str = ""
    state: str = ""


class GraphNode(BaseModel):
    """Serialized graph node for API output (ReactFlow compatible)."""

    id: str
    type: str
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Serialized graph edge for API output."""

    id: str
    source: str
    target: str
    type: str = "topologyEdge"
    data: dict[str, Any] = Field(default_factory=dict)


class GraphMetadata(BaseModel):
    """Graph-level metadata."""

    node_count: int = 0
    edge_count: int = 0
    node_type_counts: dict[str, int] = Field(default_factory=dict)
    has_anomalies: bool = False
    anomaly_count: int = 0


class SerializedGraph(BaseModel):
    """Complete serialized graph for API responses."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    metadata: GraphMetadata = Field(default_factory=GraphMetadata)
