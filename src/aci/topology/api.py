"""Topology API endpoints — FastAPI router for graph-based topology queries.

Adapted from agenticops-chat graph API. Uses boto3 directly instead of
network_tools wrappers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
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
from .engine import InfraGraph
from .serializers import to_reactflow
from .types import SerializedGraph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/topology", tags=["topology"])


# ── Boto3 topology builders ─────────────────────────────────────────


def _get_vpc_topology(region: str, vpc_id: str) -> dict[str, Any]:
    """Fetch VPC topology from AWS and return structured dict.

    This replaces the agenticops-chat dependency on network_tools.analyze_vpc_topology().
    """
    ec2 = boto3.client("ec2", region_name=region)

    topo: dict[str, Any] = {
        "vpc_id": vpc_id,
        "vpc_cidr": "",
        "vpc_name": "",
        "internet_gateways": [],
        "subnets": [],
        "route_tables": [],
        "nat_gateways": [],
        "transit_gateway_attachments": [],
        "vpc_peering_connections": [],
        "vpc_endpoints": [],
        "security_group_dependency_map": {},
        "blackhole_routes": [],
    }

    # VPC details
    try:
        vpcs = ec2.describe_vpcs(VpcIds=[vpc_id])["Vpcs"]
        if vpcs:
            vpc = vpcs[0]
            topo["vpc_cidr"] = vpc.get("CidrBlock", "")
            for tag in vpc.get("Tags", []):
                if tag["Key"] == "Name":
                    topo["vpc_name"] = tag["Value"]
    except Exception as e:
        logger.warning(f"Failed to describe VPC {vpc_id}: {e}")

    # Internet Gateways
    try:
        igws = ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )["InternetGateways"]
        for igw in igws:
            attachments = [
                {"state": a.get("State", ""), "vpc_id": a.get("VpcId", "")}
                for a in igw.get("Attachments", [])
            ]
            name = ""
            for tag in igw.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            topo["internet_gateways"].append({
                "igw_id": igw["InternetGatewayId"],
                "name": name,
                "attachments": attachments,
            })
    except Exception as e:
        logger.warning(f"Failed to describe IGWs: {e}")

    # Subnets
    try:
        subnets = ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["Subnets"]
        for s in subnets:
            name = ""
            for tag in s.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            subnet_type = "public" if s.get("MapPublicIpOnLaunch", False) else "private"
            topo["subnets"].append({
                "subnet_id": s["SubnetId"],
                "name": name,
                "cidr": s.get("CidrBlock", ""),
                "az": s.get("AvailabilityZone", ""),
                "available_ips": s.get("AvailableIpAddressCount", 0),
                "type": subnet_type,
            })
    except Exception as e:
        logger.warning(f"Failed to describe subnets: {e}")

    # Route Tables
    try:
        rtbs = ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["RouteTables"]
        for rtb in rtbs:
            rtb_id = rtb["RouteTableId"]
            name = ""
            for tag in rtb.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            assoc_subnets = [
                a["SubnetId"]
                for a in rtb.get("Associations", [])
                if a.get("SubnetId")
            ]
            routes = []
            for r in rtb.get("Routes", []):
                dest = r.get("DestinationCidrBlock", r.get("DestinationIpv6CidrBlock", ""))
                target = (
                    r.get("GatewayId")
                    or r.get("NatGatewayId")
                    or r.get("TransitGatewayId")
                    or r.get("VpcPeeringConnectionId")
                    or r.get("NetworkInterfaceId")
                    or "local"
                )
                state = r.get("State", "active")
                routes.append({"destination": dest, "target": target, "state": state})
                if state == "blackhole":
                    topo["blackhole_routes"].append({
                        "route_table_id": rtb_id,
                        "destination": dest,
                    })
            topo["route_tables"].append({
                "route_table_id": rtb_id,
                "name": name,
                "associated_subnets": assoc_subnets,
                "routes": routes,
            })
    except Exception as e:
        logger.warning(f"Failed to describe route tables: {e}")

    # NAT Gateways
    try:
        nats = ec2.describe_nat_gateways(
            Filter=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["NatGateways"]
        for nat in nats:
            name = ""
            for tag in nat.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            topo["nat_gateways"].append({
                "nat_gateway_id": nat["NatGatewayId"],
                "name": name,
                "state": nat.get("State", ""),
                "subnet_id": nat.get("SubnetId", ""),
            })
    except Exception as e:
        logger.warning(f"Failed to describe NAT gateways: {e}")

    # Transit Gateway Attachments
    try:
        atts = ec2.describe_transit_gateway_attachments(
            Filters=[{"Name": "resource-id", "Values": [vpc_id]}]
        )["TransitGatewayAttachments"]
        for att in atts:
            topo["transit_gateway_attachments"].append({
                "attachment_id": att["TransitGatewayAttachmentId"],
                "transit_gateway_id": att.get("TransitGatewayId", ""),
                "state": att.get("State", ""),
            })
    except Exception as e:
        logger.warning(f"Failed to describe TGW attachments: {e}")

    # VPC Peering
    try:
        pcxs = ec2.describe_vpc_peering_connections(
            Filters=[
                {"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]},
            ]
        )["VpcPeeringConnections"]
        # Also check accepter side
        pcxs_acc = ec2.describe_vpc_peering_connections(
            Filters=[
                {"Name": "accepter-vpc-info.vpc-id", "Values": [vpc_id]},
            ]
        )["VpcPeeringConnections"]
        seen = set()
        for pcx in pcxs + pcxs_acc:
            pcx_id = pcx["VpcPeeringConnectionId"]
            if pcx_id in seen:
                continue
            seen.add(pcx_id)
            topo["vpc_peering_connections"].append({
                "pcx_id": pcx_id,
                "requester_vpc": pcx.get("RequesterVpcInfo", {}).get("VpcId", ""),
                "accepter_vpc": pcx.get("AccepterVpcInfo", {}).get("VpcId", ""),
                "status": pcx.get("Status", {}).get("Code", ""),
            })
    except Exception as e:
        logger.warning(f"Failed to describe VPC peering: {e}")

    # VPC Endpoints
    try:
        vpces = ec2.describe_vpc_endpoints(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["VpcEndpoints"]
        for vpce in vpces:
            topo["vpc_endpoints"].append({
                "endpoint_id": vpce["VpcEndpointId"],
                "service_name": vpce.get("ServiceName", ""),
                "state": vpce.get("State", ""),
                "subnet_ids": vpce.get("SubnetIds", []),
            })
    except Exception as e:
        logger.warning(f"Failed to describe VPC endpoints: {e}")

    return topo


def _build_vpc_graph(region: str, vpc_id: str) -> InfraGraph:
    """Build an InfraGraph from a VPC topology."""
    topo = _get_vpc_topology(region, vpc_id)
    return InfraGraph().build_from_vpc_topology(topo)


def _build_region_graph(region: str) -> InfraGraph:
    """Build an InfraGraph from a region topology."""
    ec2 = boto3.client("ec2", region_name=region)

    topo: dict[str, Any] = {
        "region": region,
        "vpcs": [],
        "transit_gateways": [],
        "peering_connections": [],
    }

    # VPCs
    try:
        vpcs = ec2.describe_vpcs()["Vpcs"]
        for vpc in vpcs:
            name = ""
            for tag in vpc.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            topo["vpcs"].append({
                "vpc_id": vpc["VpcId"],
                "name": name,
                "cidr": vpc.get("CidrBlock", ""),
                "state": vpc.get("State", ""),
                "is_default": vpc.get("IsDefault", False),
            })
    except Exception as e:
        logger.warning(f"Failed to describe VPCs: {e}")

    # Transit Gateways
    try:
        tgws = ec2.describe_transit_gateways()["TransitGateways"]
        for tgw in tgws:
            name = ""
            for tag in tgw.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            # Get attachments
            atts = ec2.describe_transit_gateway_attachments(
                Filters=[{"Name": "transit-gateway-id", "Values": [tgw["TransitGatewayId"]]}]
            )["TransitGatewayAttachments"]
            topo["transit_gateways"].append({
                "transit_gateway_id": tgw["TransitGatewayId"],
                "name": name,
                "state": tgw.get("State", ""),
                "attachments": [
                    {
                        "resource_id": a.get("ResourceId", ""),
                        "resource_type": a.get("ResourceType", ""),
                        "state": a.get("State", ""),
                    }
                    for a in atts
                ],
            })
    except Exception as e:
        logger.warning(f"Failed to describe TGWs: {e}")

    # Peering
    try:
        pcxs = ec2.describe_vpc_peering_connections()["VpcPeeringConnections"]
        for pcx in pcxs:
            topo["peering_connections"].append({
                "pcx_id": pcx["VpcPeeringConnectionId"],
                "requester_vpc": pcx.get("RequesterVpcInfo", {}).get("VpcId", ""),
                "accepter_vpc": pcx.get("AccepterVpcInfo", {}).get("VpcId", ""),
                "status": pcx.get("Status", {}).get("Code", ""),
            })
    except Exception as e:
        logger.warning(f"Failed to describe peering: {e}")

    return InfraGraph().build_from_region_topology(topo)


# ── API Endpoints ────────────────────────────────────────────────────


@router.get("/vpc/{vpc_id}")
async def get_vpc_graph(
    vpc_id: str,
    region: str = Query("us-east-1"),
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
    region: str = Query("us-east-1"),
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
    region: str = Query("us-east-1"),
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
    region: str = Query("us-east-1"),
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
    region: str = Query("us-east-1"),
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
    region: str = Query("us-east-1"),
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
    region: str = Query("us-east-1"),
) -> SegmentReport:
    """Analyze network segmentation across all VPCs in a region."""
    try:
        graph = _build_region_graph(region)
        return network_segments(graph)
    except Exception as e:
        logger.exception("Segment analysis failed")
        return JSONResponse({"error": str(e)}, status_code=500)
