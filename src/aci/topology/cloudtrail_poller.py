"""CloudTrail Poller — polls infrastructure-mutating API calls and records topology deltas.

Periodically queries CloudTrail ``LookupEvents`` for networking and
compute changes that affect the topology graph.  Discovered events
are converted to :class:`TopologyChange` records and stored via
:class:`DeltaStore`.

Design ref: docs/designs/GRAPH_FAULT_PROPAGATION_DESIGN.md §3.3, §5.4
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

from .delta import DeltaStore, TopologyChange, get_delta_store

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

_DEFAULT_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1")
_POLL_INTERVAL_S = int(os.environ.get("CLOUDTRAIL_POLL_INTERVAL_S", "300"))  # 5 min
_LOOKBACK_S = int(os.environ.get("CLOUDTRAIL_LOOKBACK_S", "600"))  # 10 min overlap
_MAX_PAGES = int(os.environ.get("CLOUDTRAIL_MAX_PAGES", "5"))

# ── Event mapping ────────────────────────────────────────────────────
# CloudTrail event names that mutate infrastructure relevant to the topology graph.
# Maps event_name → (change_type, entity_type, resource_id_key)
#
# resource_id_key is a dot-path into responseElements / requestParameters
# for extracting the affected resource ID.

_MUTATING_EVENTS: dict[str, dict[str, str]] = {
    # NAT Gateways
    "CreateNatGateway": {
        "change_type": "node_added",
        "entity_type": "nat",
        "response_key": "natGateway.natGatewayId",
    },
    "DeleteNatGateway": {
        "change_type": "node_removed",
        "entity_type": "nat",
        "request_key": "natGatewayId",
    },
    # Internet Gateways
    "CreateInternetGateway": {
        "change_type": "node_added",
        "entity_type": "igw",
        "response_key": "internetGateway.internetGatewayId",
    },
    "DeleteInternetGateway": {
        "change_type": "node_removed",
        "entity_type": "igw",
        "request_key": "internetGatewayId",
    },
    "AttachInternetGateway": {
        "change_type": "edge_added",
        "entity_type": "ROUTES_THROUGH",
        "request_key": "internetGatewayId",
    },
    "DetachInternetGateway": {
        "change_type": "edge_removed",
        "entity_type": "ROUTES_THROUGH",
        "request_key": "internetGatewayId",
    },
    # Subnets
    "CreateSubnet": {
        "change_type": "node_added",
        "entity_type": "subnet",
        "response_key": "subnet.subnetId",
    },
    "DeleteSubnet": {
        "change_type": "node_removed",
        "entity_type": "subnet",
        "request_key": "subnetId",
    },
    # Route Tables
    "CreateRouteTable": {
        "change_type": "node_added",
        "entity_type": "rtb",
        "response_key": "routeTable.routeTableId",
    },
    "DeleteRouteTable": {
        "change_type": "node_removed",
        "entity_type": "rtb",
        "request_key": "routeTableId",
    },
    "CreateRoute": {
        "change_type": "edge_added",
        "entity_type": "ROUTES_THROUGH",
        "request_key": "routeTableId",
    },
    "DeleteRoute": {
        "change_type": "edge_removed",
        "entity_type": "ROUTES_THROUGH",
        "request_key": "routeTableId",
    },
    "ReplaceRoute": {
        "change_type": "node_updated",
        "entity_type": "rtb",
        "request_key": "routeTableId",
    },
    # Security Groups
    "CreateSecurityGroup": {
        "change_type": "node_added",
        "entity_type": "sg",
        "response_key": "groupId",
    },
    "DeleteSecurityGroup": {
        "change_type": "node_removed",
        "entity_type": "sg",
        "request_key": "groupId",
    },
    "AuthorizeSecurityGroupIngress": {
        "change_type": "node_updated",
        "entity_type": "sg",
        "request_key": "groupId",
    },
    "RevokeSecurityGroupIngress": {
        "change_type": "node_updated",
        "entity_type": "sg",
        "request_key": "groupId",
    },
    "AuthorizeSecurityGroupEgress": {
        "change_type": "node_updated",
        "entity_type": "sg",
        "request_key": "groupId",
    },
    "RevokeSecurityGroupEgress": {
        "change_type": "node_updated",
        "entity_type": "sg",
        "request_key": "groupId",
    },
    # VPC Endpoints
    "CreateVpcEndpoint": {
        "change_type": "node_added",
        "entity_type": "vpce",
        "response_key": "vpcEndpoint.vpcEndpointId",
    },
    "DeleteVpcEndpoints": {
        "change_type": "node_removed",
        "entity_type": "vpce",
        "request_key": "vpcEndpointIds",
    },
    # EC2 Instances (topology-relevant)
    "RunInstances": {
        "change_type": "node_added",
        "entity_type": "ec2",
        "response_key": "instancesSet.items[0].instanceId",
    },
    "TerminateInstances": {
        "change_type": "node_removed",
        "entity_type": "ec2",
        "request_key": "instancesSet.items[0].instanceId",
    },
    # Elastic Load Balancers
    "CreateLoadBalancer": {
        "change_type": "node_added",
        "entity_type": "elb",
        "response_key": "loadBalancers[0].loadBalancerArn",
    },
    "DeleteLoadBalancer": {
        "change_type": "node_removed",
        "entity_type": "elb",
        "request_key": "loadBalancerArn",
    },
    # VPC Peering
    "CreateVpcPeeringConnection": {
        "change_type": "edge_added",
        "entity_type": "PEERS_WITH",
        "response_key": "vpcPeeringConnection.vpcPeeringConnectionId",
    },
    "DeleteVpcPeeringConnection": {
        "change_type": "edge_removed",
        "entity_type": "PEERS_WITH",
        "request_key": "vpcPeeringConnectionId",
    },
    # ENI (Elastic Network Interface)
    "CreateNetworkInterface": {
        "change_type": "node_added",
        "entity_type": "eni",
        "response_key": "networkInterface.networkInterfaceId",
    },
    "DeleteNetworkInterface": {
        "change_type": "node_removed",
        "entity_type": "eni",
        "request_key": "networkInterfaceId",
    },
}


# ── Helpers ──────────────────────────────────────────────────────────


def _extract_resource_id(
    event_detail: dict[str, Any],
    mapping: dict[str, str],
) -> str:
    """Extract the resource ID from CloudTrail event using the mapping config.

    Supports dot-path navigation (``a.b.c``) and simple array indexing
    (``items[0].id``).
    """
    for key_type in ("response_key", "request_key"):
        path = mapping.get(key_type)
        if not path:
            continue

        # Choose the right top-level dict
        if key_type == "response_key":
            root = event_detail.get("responseElements") or {}
        else:
            root = event_detail.get("requestParameters") or {}

        value = _navigate_path(root, path)
        if value:
            # Handle list values (e.g. DeleteVpcEndpoints → vpcEndpointIds)
            if isinstance(value, list):
                return str(value[0]) if value else ""
            return str(value)

    # Fallback: try resources array
    resources = event_detail.get("resources", [])
    if resources:
        return resources[0].get("ARN", "") or resources[0].get("resourceName", "")

    return ""


def _navigate_path(data: dict[str, Any] | Any, path: str) -> Any:
    """Navigate a dot-separated path with optional [index] notation."""
    current = data
    for part in path.split("."):
        if current is None:
            return None

        # Handle array index: "items[0]"
        if "[" in part and "]" in part:
            key, idx_str = part.split("[", 1)
            idx = int(idx_str.rstrip("]"))
            if key:
                current = current.get(key) if isinstance(current, dict) else None
            if isinstance(current, list) and len(current) > idx:
                current = current[idx]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None

    return current


def _extract_user_identity(event_detail: dict[str, Any]) -> str:
    """Extract user/role from CloudTrail event's userIdentity."""
    ui = event_detail.get("userIdentity", {})
    # Prefer principalId, then userName, then ARN
    return (
        ui.get("principalId", "")
        or ui.get("userName", "")
        or ui.get("arn", "")
        or "unknown"
    )


def _extract_vpc_id(event_detail: dict[str, Any]) -> str:
    """Best-effort VPC ID extraction from request/response params."""
    for section in ("requestParameters", "responseElements"):
        params = event_detail.get(section) or {}
        if isinstance(params, dict):
            # Direct vpcId field
            vpc_id = params.get("vpcId", "")
            if vpc_id:
                return vpc_id
            # Nested in subnet/natGateway/etc
            for nested_key in ("subnet", "natGateway", "routeTable", "networkInterface"):
                nested = params.get(nested_key, {})
                if isinstance(nested, dict) and nested.get("vpcId"):
                    return nested["vpcId"]
    return ""


# ── Core polling function ────────────────────────────────────────────


def poll_cloudtrail_events(
    region: str | None = None,
    lookback_seconds: int | None = None,
    max_pages: int | None = None,
) -> list[TopologyChange]:
    """Poll CloudTrail for topology-mutating events.

    Args:
        region: AWS region to poll (default from env).
        lookback_seconds: How far back to query (default 600s).
        max_pages: Max pagination pages (default 5).

    Returns:
        List of :class:`TopologyChange` records ready for DeltaStore.
    """
    region = region or _DEFAULT_REGION
    lookback = lookback_seconds or _LOOKBACK_S
    pages = max_pages or _MAX_PAGES

    end_time = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(seconds=lookback)

    try:
        ct_client = boto3.client("cloudtrail", region_name=region)
    except Exception as e:
        logger.error("Failed to create CloudTrail client: %s", e)
        return []

    changes: list[TopologyChange] = []
    event_names = list(_MUTATING_EVENTS.keys())

    # CloudTrail LookupEvents only supports one AttributeKey per call,
    # and EventName lookup is not directly supported as a filter.
    # We query by time range and filter client-side.
    try:
        paginator = ct_client.get_paginator("lookup_events")
        page_iter = paginator.paginate(
            StartTime=start_time,
            EndTime=end_time,
            PaginationConfig={"MaxItems": pages * 50, "PageSize": 50},
        )

        for page in page_iter:
            for event in page.get("Events", []):
                event_name = event.get("EventName", "")
                if event_name not in _MUTATING_EVENTS:
                    continue

                mapping = _MUTATING_EVENTS[event_name]

                # Parse the full event detail
                detail: dict[str, Any] = {}
                raw = event.get("CloudTrailEvent", "")
                if raw:
                    try:
                        detail = json.loads(raw)
                    except (ValueError, TypeError):
                        pass

                resource_id = _extract_resource_id(detail, mapping)
                if not resource_id:
                    # Try event-level resources
                    resources = event.get("Resources", [])
                    if resources:
                        resource_id = (
                            resources[0].get("ResourceName", "")
                            or resources[0].get("ResourceType", "")
                        )
                    if not resource_id:
                        resource_id = f"unknown-{event_name}"

                user = _extract_user_identity(detail)
                vpc_id = _extract_vpc_id(detail)
                event_time = event.get("EventTime")
                ts = (
                    event_time.isoformat()
                    if hasattr(event_time, "isoformat")
                    else str(event_time or "")
                )

                changes.append(TopologyChange(
                    change_type=mapping["change_type"],
                    entity_id=resource_id,
                    entity_type=mapping["entity_type"],
                    old_value=None,
                    new_value={"event_name": event_name, "user": user, "vpc_id": vpc_id},
                    source="cloudtrail",
                    source_detail=f"{event_name} by {user}",
                    region=region,
                    account_id=detail.get("recipientAccountId", ""),
                    timestamp=ts,
                ))

    except Exception as e:
        logger.warning("CloudTrail polling failed (non-fatal): %s", e)

    if changes:
        logger.info(
            "CloudTrail poll: %d topology-relevant events in last %ds",
            len(changes),
            lookback,
        )

    return changes


# ── Async poll + store helper ────────────────────────────────────────


async def poll_and_store(
    region: str | None = None,
    store: DeltaStore | None = None,
    lookback_seconds: int | None = None,
) -> int:
    """Poll CloudTrail and persist results to DeltaStore.

    Runs the synchronous boto3 call in an executor to avoid blocking.

    Returns:
        Number of changes stored.
    """
    loop = asyncio.get_running_loop()
    changes = await loop.run_in_executor(
        None,
        lambda: poll_cloudtrail_events(
            region=region,
            lookback_seconds=lookback_seconds,
        ),
    )

    if not changes:
        return 0

    ds = store or get_delta_store()
    return ds.store(changes)


# ── Background polling loop ─────────────────────────────────────────


class CloudTrailPollerLoop:
    """Background async loop that periodically polls CloudTrail.

    Integrates with the GraphCache lifecycle — start/stop alongside
    the cache refresh loop.

    Usage::

        from src.aci.topology.cloudtrail_poller import cloudtrail_poller

        # In api_server lifespan:
        cloudtrail_poller.start()
        ...
        cloudtrail_poller.stop()
    """

    def __init__(
        self,
        poll_interval_s: int | None = None,
        region: str | None = None,
    ) -> None:
        self._interval = poll_interval_s or _POLL_INTERVAL_S
        self._region = region or _DEFAULT_REGION
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the background polling task."""
        if self.is_running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._loop(),
            name="cloudtrail-poller",
        )
        logger.info(
            "CloudTrail poller started (interval=%ds, region=%s)",
            self._interval,
            self._region,
        )

    def stop(self) -> None:
        """Stop the background polling task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            logger.info("CloudTrail poller stopped")

    async def _loop(self) -> None:
        """Periodic poll loop with jitter-free interval."""
        # Initial delay — let cache build first
        await asyncio.sleep(10)

        while self._running:
            try:
                count = await poll_and_store(region=self._region)
                if count:
                    logger.info("CloudTrail poller stored %d changes", count)

                # Also purge old deltas on each cycle
                try:
                    ds = get_delta_store()
                    ds.purge_old()
                except Exception:
                    logger.exception("Delta purge failed (non-fatal)")

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("CloudTrail poller cycle failed (non-fatal)")

            await asyncio.sleep(self._interval)

    def status(self) -> dict[str, Any]:
        """Return poller status for health/debug endpoints."""
        return {
            "running": self.is_running,
            "interval_s": self._interval,
            "region": self._region,
        }


# ── Module-level singleton ───────────────────────────────────────────

cloudtrail_poller = CloudTrailPollerLoop()
