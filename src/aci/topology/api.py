"""Topology API endpoints — FastAPI router for graph-based topology queries.

Adapted from agenticops-chat graph API. Uses collector.py for boto3 data
fetching and InfraGraph for graph construction + algorithms.

Phase 4 additions (§3.6):
  - GET /vpc/{vpc_id}/propagation — fault propagation analysis
  - GET /vpc/{vpc_id}/changes     — topology delta queries
  - GET /vpc/{vpc_id}?annotate_propagation=... — ReactFlow overlay
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
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
from .delta import TopologyChange, format_recent_changes, get_delta_store
from .engine import InfraGraph
from .propagation import PropagationMode, PropagationResult, fault_propagation
from .serializers import annotate_propagation_overlay, to_reactflow
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
    annotate_propagation: Optional[str] = Query(
        None,
        description="Node ID to overlay fault propagation data on the graph",
    ),
) -> SerializedGraph:
    """Get ReactFlow-ready graph for a single VPC.

    When ``annotate_propagation`` is provided, runs fault propagation from
    that node and overlays wave/impact data onto the ReactFlow output.
    """
    try:
        graph = _build_vpc_graph(region, vpc_id)
        rf = to_reactflow(graph, view="vpc")

        if annotate_propagation:
            if annotate_propagation not in graph.graph:
                # Node not in graph — return base graph without overlay (graceful)
                logger.warning(
                    "annotate_propagation node %s not in graph, returning base graph",
                    annotate_propagation,
                )
                return rf
            prop_result = fault_propagation(
                graph,
                annotate_propagation,
                mode=PropagationMode.REALISTIC,
            )
            rf = annotate_propagation_overlay(rf, prop_result)

        return rf
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


# ── Phase 4: Propagation + Changes endpoints ────────────────────────


@router.get("/vpc/{vpc_id}/propagation")
async def get_propagation(
    vpc_id: str,
    node_id: str = Query(..., description="Root failure node ID"),
    mode: str = Query("realistic", description="pessimistic | realistic"),
    max_depth: int = Query(10, ge=1, le=100, description="Max BFS depth"),
    region: str = Query("ap-southeast-1"),
) -> dict:
    """Run fault propagation from a node and return the full result.

    Ref: GRAPH_FAULT_PROPAGATION_DESIGN.md §3.6
    """
    # Validate mode
    try:
        prop_mode = PropagationMode(mode)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mode '{mode}'. Must be 'pessimistic' or 'realistic'.",
        )

    try:
        graph = _build_vpc_graph(region, vpc_id)
    except Exception as e:
        logger.exception("Failed to build VPC graph for propagation")
        raise HTTPException(status_code=404, detail=f"VPC {vpc_id} not found: {e}")

    if node_id not in graph.graph:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{node_id}' not found in VPC {vpc_id} graph.",
        )

    result = fault_propagation(graph, node_id, mode=prop_mode, max_depth=max_depth)
    return result.to_dict()


@router.get("/vpc/{vpc_id}/changes")
async def get_changes(
    vpc_id: str,
    since: Optional[str] = Query(
        None,
        description="ISO 8601 timestamp (default: 1 hour ago)",
    ),
    source: Optional[str] = Query(
        None,
        description="Filter by source: discovery | cloudtrail | manual",
    ),
    limit: int = Query(100, ge=1, le=1000, description="Max records"),
    region: str = Query("ap-southeast-1"),
) -> dict:
    """Query topology changes (deltas) for a VPC.

    Ref: GRAPH_FAULT_PROPAGATION_DESIGN.md §3.6
    """
    # Validate source
    valid_sources = {"discovery", "cloudtrail", "manual"}
    if source and source not in valid_sources:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source '{source}'. Must be one of: {', '.join(sorted(valid_sources))}.",
        )

    # Parse since
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
            window = datetime.now(tz=timezone.utc) - since_dt
            if window.total_seconds() <= 0:
                window = timedelta(hours=1)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid 'since' format: '{since}'. Use ISO 8601 (e.g. 2026-02-26T00:00:00Z).",
            )
    else:
        window = timedelta(hours=1)

    store = get_delta_store()
    changes = store.get_recent(window=window, limit=limit)

    # Filter by source if specified
    if source:
        changes = [c for c in changes if c.source == source]

    # Filter by VPC scope — match entity or vpc_id in new_value metadata
    vpc_scoped: list[TopologyChange] = []
    for c in changes:
        # Check if entity belongs to this VPC (from new_value or region metadata)
        nv = c.new_value or {}
        ov = c.old_value or {}
        change_vpc = nv.get("vpc_id", "") or ov.get("vpc_id", "")
        if change_vpc == vpc_id or not change_vpc:
            # Include: matching VPC or VPC-unscoped changes
            vpc_scoped.append(c)

    return {
        "vpc_id": vpc_id,
        "since": (datetime.now(tz=timezone.utc) - window).isoformat(),
        "source_filter": source,
        "count": len(vpc_scoped),
        "changes": [c.to_dict() for c in vpc_scoped],
        "summary": format_recent_changes(vpc_scoped),
    }
