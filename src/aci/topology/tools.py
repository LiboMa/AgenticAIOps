"""Topology-based Strands tools for Agent use.

Each tool builds an InfraGraph via the collector, runs the appropriate
algorithm, and returns JSON results for LLM consumption.

These tools are NOT auto-registered — import them explicitly when needed.
"""

from __future__ import annotations

import json
import logging

from strands import tool

from .algorithms import (
    can_reach_internet,
    detect_anomalies,
    find_traffic_path,
    impact_analysis,
    network_segments,
)
from .collector import collect_region_topology, collect_vpc_topology
from .engine import InfraGraph
from .serializers import to_agent_summary

logger = logging.getLogger(__name__)


def _build_vpc_graph(region: str, vpc_id: str) -> InfraGraph:
    """Build graph from VPC topology via collector."""
    topo = collect_vpc_topology(region, vpc_id)
    return InfraGraph().build_from_vpc_topology(topo)


def _build_region_graph(region: str) -> InfraGraph:
    """Build graph from region topology via collector."""
    topo = collect_region_topology(region)
    return InfraGraph().build_from_region_topology(topo)


@tool
def query_reachability(region: str, vpc_id: str, subnet_id: str) -> str:
    """Check if a subnet can reach the Internet, returning the exact path or blocking reason.

    Builds a topology graph for the VPC and traces the path from the subnet
    through route tables and gateways to the Internet Gateway. Reports
    blackhole routes that block connectivity.

    Args:
        region: AWS region (e.g., 'ap-southeast-1')
        vpc_id: VPC ID to analyze
        subnet_id: Subnet ID to check reachability for

    Returns:
        JSON with can_reach_internet (bool), path (list of node IDs),
        path_details (per-hop type and label), and blocking_reason if unreachable.
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        result = can_reach_internet(graph, subnet_id)
        return result.model_dump_json(indent=2)
    except Exception as e:
        logger.exception("query_reachability failed")
        return json.dumps({"error": str(e)})


@tool
def query_impact_radius(region: str, vpc_id: str, resource_id: str) -> str:
    """Simulate a resource failure and return the blast radius.

    Removes the specified node from the topology graph and computes
    which subnets lose Internet connectivity and which connections are broken.

    Args:
        region: AWS region (e.g., 'ap-southeast-1')
        vpc_id: VPC ID to analyze
        resource_id: Resource ID to simulate failure for (e.g., nat-xxx, igw-xxx)

    Returns:
        JSON with affected_nodes, lost_connections, isolated_subnets, and severity.
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        result = impact_analysis(graph, resource_id)
        return result.model_dump_json(indent=2)
    except Exception as e:
        logger.exception("query_impact_radius failed")
        return json.dumps({"error": str(e)})


@tool
def find_network_path(region: str, vpc_id: str, source: str, target: str) -> str:
    """Find the network path between two resources in a VPC.

    Traces traffic flow through route tables, gateways, and subnets.
    Returns up to 5 shortest paths with per-hop details.

    Args:
        region: AWS region (e.g., 'ap-southeast-1')
        vpc_id: VPC ID to analyze
        source: Source resource ID (e.g., subnet-xxx)
        target: Target resource ID (e.g., igw-xxx, nat-xxx, subnet-yyy)

    Returns:
        JSON with paths (list of node ID lists) and path_details (per-hop info).
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        result = find_traffic_path(graph, source, target)
        return result.model_dump_json(indent=2)
    except Exception as e:
        logger.exception("find_network_path failed")
        return json.dumps({"error": str(e)})


@tool
def detect_network_anomalies(region: str, vpc_id: str) -> str:
    """Detect structural anomalies in a VPC's network topology.

    Checks for orphan nodes, blackhole routes, routing cycles,
    unreachable public subnets, and nodes in error state.

    Args:
        region: AWS region (e.g., 'ap-southeast-1')
        vpc_id: VPC ID to analyze

    Returns:
        JSON with total_anomalies, anomaly list, and summary string.
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        result = detect_anomalies(graph)
        return result.model_dump_json(indent=2)
    except Exception as e:
        logger.exception("detect_network_anomalies failed")
        return json.dumps({"error": str(e)})


@tool
def analyze_network_segments(region: str) -> str:
    """Analyze network segmentation across all VPCs in a region.

    Builds a region-level topology graph and identifies connected components,
    isolated VPCs, and cross-VPC connectivity via TGW and peering.

    Args:
        region: AWS region (e.g., 'ap-southeast-1')

    Returns:
        JSON with segments, isolated_vpcs, and graph_summary.
    """
    try:
        graph = _build_region_graph(region)
        result = network_segments(graph)
        summary = to_agent_summary(graph)
        output = result.model_dump()
        output["graph_summary"] = summary
        return json.dumps(output, indent=2)
    except Exception as e:
        logger.exception("analyze_network_segments failed")
        return json.dumps({"error": str(e)})
