"""Topology API endpoints — FastAPI router for graph-based topology queries.

Adapted from agenticops-chat graph API. Uses collector.py for boto3 data
fetching and InfraGraph for graph construction + algorithms.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .algorithms import (
    AnomalyReport,
    ImpactResult,
    PathResult,
    ReachabilityResult,
    SegmentReport,
    can_reach_internet,
    detect_anomalies,
    find_traffic_path,
    impact_analysis,
    network_segments,
)
from .collector import collect_region_topology, collect_vpc_topology
from .engine import InfraGraph
from .serializers import to_reactflow
from .types import SerializedGraph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/topology", tags=["topology"])


# ── Graph builders (using collector) ─────────────────────────────────


def _build_vpc_graph(region: str, vpc_id: str) -> InfraGraph:
    """Build an InfraGraph from a VPC topology via collector."""
    topo = collect_vpc_topology(region, vpc_id)
    return InfraGraph().build_from_vpc_topology(topo)


def _build_region_graph(region: str) -> InfraGraph:
    """Build an InfraGraph from a region topology via collector."""
    topo = collect_region_topology(region)
    return InfraGraph().build_from_region_topology(topo)


# ── API Endpoints ────────────────────────────────────────────────────


@router.get("/vpc/{vpc_id}")
async def get_vpc_graph(
    vpc_id: str,
    region: str = Query("ap-southeast-1"),
) -> SerializedGraph:
    """Get ReactFlow-ready graph for a single VPC."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return to_reactflow(graph, view="vpc")
    except Exception as e:
        logger.exception("Failed to build VPC graph")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/region")
async def get_region_graph(
    region: str = Query("ap-southeast-1"),
) -> SerializedGraph:
    """Get ReactFlow-ready graph for a region (multi-VPC view)."""
    try:
        graph = _build_region_graph(region)
        return to_reactflow(graph, view="region")
    except Exception as e:
        logger.exception("Failed to build region graph")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/reachability/{subnet_id}")
async def get_reachability(
    vpc_id: str,
    subnet_id: str,
    region: str = Query("ap-southeast-1"),
) -> ReachabilityResult:
    """Check if a subnet can reach the Internet."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return can_reach_internet(graph, subnet_id)
    except Exception as e:
        logger.exception("Reachability check failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/impact/{resource_id}")
async def get_impact(
    vpc_id: str,
    resource_id: str,
    region: str = Query("ap-southeast-1"),
) -> ImpactResult:
    """Simulate resource failure and return impact analysis."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return impact_analysis(graph, resource_id)
    except Exception as e:
        logger.exception("Impact analysis failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/path")
async def get_path(
    vpc_id: str,
    source: str = Query(...),
    target: str = Query(...),
    region: str = Query("ap-southeast-1"),
) -> PathResult:
    """Find traffic path between two resources."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return find_traffic_path(graph, source, target)
    except Exception as e:
        logger.exception("Path finding failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/vpc/{vpc_id}/anomalies")
async def get_anomalies(
    vpc_id: str,
    region: str = Query("ap-southeast-1"),
) -> AnomalyReport:
    """Detect structural anomalies in VPC topology."""
    try:
        graph = _build_vpc_graph(region, vpc_id)
        return detect_anomalies(graph)
    except Exception as e:
        logger.exception("Anomaly detection failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/region/segments")
async def get_segments(
    region: str = Query("ap-southeast-1"),
) -> SegmentReport:
    """Analyze network segmentation across all VPCs in a region."""
    try:
        graph = _build_region_graph(region)
        return network_segments(graph)
    except Exception as e:
        logger.exception("Segment analysis failed")
        return JSONResponse({"error": str(e)}, status_code=500)
