"""Topology data collector — fetches VPC/region topology via boto3.

Replaces inline boto3 calls in api.py with a dedicated collector layer.
Outputs dicts that match the schema consumed by InfraGraph.build_from_vpc_topology()
and InfraGraph.build_from_region_topology().

boto3 PascalCase → engine snake_case conversion happens here.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import boto3

logger = logging.getLogger(__name__)

# Default region — aligned with api_server.py _current_region
_DEFAULT_REGION = "ap-southeast-1"


# ── boto3 client factory ────────────────────────────────────────────


def _get_ec2_client(region: str | None = None):
    """Get boto3 EC2 client for the given region."""
    return boto3.client("ec2", region_name=region or _DEFAULT_REGION)


# ── VPC Topology ────────────────────────────────────────────────────


def collect_vpc_topology(region: str, vpc_id: str) -> dict[str, Any]:
    """Collect single VPC topology data from AWS.

    Returns a dict matching the schema consumed by
    InfraGraph.build_from_vpc_topology() (see engine.py docstring).
    """
    ec2 = _get_ec2_client(region)

    topo: dict[str, Any] = {
        "vpc_id": vpc_id,
        "vpc_cidr": "",
        "vpc_name": "",
        "region": region,
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
            topo["vpc_name"] = _get_name_tag(vpc)
    except Exception as e:
        logger.warning("Failed to describe VPC %s: %s", vpc_id, e)

    # Internet Gateways
    try:
        igws = ec2.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )["InternetGateways"]
        for igw in igws:
            topo["internet_gateways"].append({
                "igw_id": igw["InternetGatewayId"],
                "name": _get_name_tag(igw),
                "attachments": [
                    {"state": a.get("State", ""), "vpc_id": a.get("VpcId", "")}
                    for a in igw.get("Attachments", [])
                ],
            })
    except Exception as e:
        logger.warning("Failed to describe IGWs for %s: %s", vpc_id, e)

    # Subnets
    try:
        subnets = ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["Subnets"]
        for s in subnets:
            subnet_type = "public" if s.get("MapPublicIpOnLaunch", False) else "private"
            topo["subnets"].append({
                "subnet_id": s["SubnetId"],
                "name": _get_name_tag(s),
                "cidr": s.get("CidrBlock", ""),  # ⚠️ engine expects "cidr" not "cidr_block"
                "az": s.get("AvailabilityZone", ""),
                "available_ips": s.get("AvailableIpAddressCount", 0),
                "type": subnet_type,
            })
    except Exception as e:
        logger.warning("Failed to describe subnets for %s: %s", vpc_id, e)

    # Route Tables
    try:
        rtbs = ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["RouteTables"]
        for rtb in rtbs:
            rtb_id = rtb["RouteTableId"]
            # Aggregate associated subnet IDs
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
                "name": _get_name_tag(rtb),
                "associated_subnets": assoc_subnets,
                "routes": routes,
            })
    except Exception as e:
        logger.warning("Failed to describe route tables for %s: %s", vpc_id, e)

    # NAT Gateways
    try:
        nats = ec2.describe_nat_gateways(
            Filter=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["NatGateways"]
        for nat in nats:
            topo["nat_gateways"].append({
                "nat_gateway_id": nat["NatGatewayId"],  # engine expects nat_gateway_id
                "name": _get_name_tag(nat),
                "state": nat.get("State", ""),
                "subnet_id": nat.get("SubnetId", ""),
            })
    except Exception as e:
        logger.warning("Failed to describe NAT gateways for %s: %s", vpc_id, e)

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
        logger.warning("Failed to describe TGW attachments for %s: %s", vpc_id, e)

    # VPC Peering Connections (both requester and accepter sides)
    try:
        pcxs = ec2.describe_vpc_peering_connections(
            Filters=[{"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]}]
        )["VpcPeeringConnections"]
        pcxs_acc = ec2.describe_vpc_peering_connections(
            Filters=[{"Name": "accepter-vpc-info.vpc-id", "Values": [vpc_id]}]
        )["VpcPeeringConnections"]
        seen: set[str] = set()
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
        logger.warning("Failed to describe VPC peering for %s: %s", vpc_id, e)

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
        logger.warning("Failed to describe VPC endpoints for %s: %s", vpc_id, e)

    # Security Groups → dependency map
    try:
        sgs = ec2.describe_security_groups(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["SecurityGroups"]
        sg_map: dict[str, dict[str, Any]] = {}
        for sg in sgs:
            sg_id = sg["GroupId"]
            # Extract referenced SGs from ingress/egress rules
            refs: set[str] = set()
            for perm in sg.get("IpPermissions", []) + sg.get("IpPermissionsEgress", []):
                for pair in perm.get("UserIdGroupPairs", []):
                    ref_id = pair.get("GroupId", "")
                    if ref_id and ref_id != sg_id:
                        refs.add(ref_id)
            sg_map[sg_id] = {
                "name": sg.get("GroupName", sg_id),
                "references": sorted(refs),
            }
        topo["security_group_dependency_map"] = sg_map
    except Exception as e:
        logger.warning("Failed to describe security groups for %s: %s", vpc_id, e)

    return topo


# ── Region Topology ─────────────────────────────────────────────────


def collect_region_topology(region: str) -> dict[str, Any]:
    """Collect region-level multi-VPC topology data from AWS.

    Returns a dict matching the schema consumed by
    InfraGraph.build_from_region_topology().
    """
    ec2 = _get_ec2_client(region)

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
            topo["vpcs"].append({
                "vpc_id": vpc["VpcId"],
                "name": _get_name_tag(vpc),
                "cidr": vpc.get("CidrBlock", ""),
                "state": vpc.get("State", ""),
                "is_default": vpc.get("IsDefault", False),
            })
    except Exception as e:
        logger.warning("Failed to describe VPCs in %s: %s", region, e)

    # Transit Gateways + their attachments
    try:
        tgws = ec2.describe_transit_gateways()["TransitGateways"]
        for tgw in tgws:
            tgw_id = tgw["TransitGatewayId"]
            atts = ec2.describe_transit_gateway_attachments(
                Filters=[{"Name": "transit-gateway-id", "Values": [tgw_id]}]
            )["TransitGatewayAttachments"]
            topo["transit_gateways"].append({
                "transit_gateway_id": tgw_id,
                "name": _get_name_tag(tgw),
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
        logger.warning("Failed to describe TGWs in %s: %s", region, e)

    # Peering Connections
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
        logger.warning("Failed to describe peering in %s: %s", region, e)

    return topo


# ── Helpers ──────────────────────────────────────────────────────────


def _get_name_tag(resource: dict[str, Any]) -> str:
    """Extract Name tag from AWS resource, return '' if not found."""
    for tag in resource.get("Tags", []):
        if tag.get("Key") == "Name":
            return tag.get("Value", "")
    return ""
