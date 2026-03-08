"""Tests for CloudTrail Poller — topology delta integration.

Tests cover:
- Event mapping and resource ID extraction
- Path navigation (dot-path, array index)
- User identity extraction
- VPC ID extraction
- poll_cloudtrail_events (mocked boto3)
- poll_and_store (async, mocked)
- CloudTrailPollerLoop lifecycle
- Edge cases (empty events, parse errors, missing fields)
"""

import asyncio
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.aci.topology.cloudtrail_poller import (
    CloudTrailPollerLoop,
    _MUTATING_EVENTS,
    _extract_resource_id,
    _extract_user_identity,
    _extract_vpc_id,
    _navigate_path,
    cloudtrail_poller,
    poll_and_store,
    poll_cloudtrail_events,
)
from src.aci.topology.delta import DeltaStore, TopologyChange


# ── Helpers ──────────────────────────────────────────────────────────


def _make_cloudtrail_event(
    event_name: str,
    request_params: dict | None = None,
    response_elements: dict | None = None,
    user: str = "test-user",
    account_id: str = "123456789012",
    resources: list | None = None,
    event_time: datetime | None = None,
) -> dict:
    """Build a mock CloudTrail event dict."""
    detail = {
        "eventName": event_name,
        "requestParameters": request_params or {},
        "responseElements": response_elements or {},
        "userIdentity": {"userName": user, "principalId": f"AIDA{user.upper()}"},
        "recipientAccountId": account_id,
    }
    event = {
        "EventName": event_name,
        "EventTime": event_time or datetime.now(tz=timezone.utc),
        "CloudTrailEvent": json.dumps(detail),
        "Resources": resources or [],
    }
    return event


def _make_paginator(events: list[dict]) -> MagicMock:
    """Build a mock paginator that returns the given events in one page."""
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Events": events}]
    return paginator


# ── _navigate_path ───────────────────────────────────────────────────


class TestNavigatePath:
    def test_simple_key(self):
        assert _navigate_path({"a": 1}, "a") == 1

    def test_nested_key(self):
        assert _navigate_path({"a": {"b": {"c": 42}}}, "a.b.c") == 42

    def test_array_index(self):
        data = {"items": [{"id": "x"}, {"id": "y"}]}
        assert _navigate_path(data, "items[0].id") == "x"
        assert _navigate_path(data, "items[1].id") == "y"

    def test_missing_key_returns_none(self):
        assert _navigate_path({"a": 1}, "b") is None

    def test_missing_nested_returns_none(self):
        assert _navigate_path({"a": {"b": 1}}, "a.c.d") is None

    def test_array_out_of_bounds(self):
        assert _navigate_path({"items": [1]}, "items[5]") is None

    def test_none_data(self):
        assert _navigate_path(None, "a.b") is None

    def test_empty_path_segment(self):
        # "[0]" with empty key → treat current as list
        data = [{"id": "first"}]
        assert _navigate_path(data, "[0].id") == "first"

    def test_non_dict_at_path(self):
        assert _navigate_path({"a": "string"}, "a.b") is None


# ── _extract_resource_id ─────────────────────────────────────────────


class TestExtractResourceId:
    def test_response_key(self):
        detail = {"responseElements": {"natGateway": {"natGatewayId": "nat-abc"}}}
        mapping = {"response_key": "natGateway.natGatewayId"}
        assert _extract_resource_id(detail, mapping) == "nat-abc"

    def test_request_key(self):
        detail = {"requestParameters": {"natGatewayId": "nat-xyz"}}
        mapping = {"request_key": "natGatewayId"}
        assert _extract_resource_id(detail, mapping) == "nat-xyz"

    def test_response_key_preferred(self):
        detail = {
            "responseElements": {"natGateway": {"natGatewayId": "nat-resp"}},
            "requestParameters": {"natGatewayId": "nat-req"},
        }
        mapping = {
            "response_key": "natGateway.natGatewayId",
            "request_key": "natGatewayId",
        }
        assert _extract_resource_id(detail, mapping) == "nat-resp"

    def test_fallback_to_resources(self):
        detail = {
            "responseElements": {},
            "requestParameters": {},
            "resources": [{"ARN": "arn:aws:ec2:us-east-1:123:instance/i-abc"}],
        }
        mapping = {"response_key": "nonexistent"}
        assert "arn:aws:ec2" in _extract_resource_id(detail, mapping)

    def test_list_value_first_element(self):
        detail = {"requestParameters": {"vpcEndpointIds": ["vpce-1", "vpce-2"]}}
        mapping = {"request_key": "vpcEndpointIds"}
        assert _extract_resource_id(detail, mapping) == "vpce-1"

    def test_empty_returns_empty(self):
        detail = {}
        mapping = {"response_key": "nonexistent"}
        assert _extract_resource_id(detail, mapping) == ""

    def test_run_instances_nested_array(self):
        detail = {
            "responseElements": {
                "instancesSet": {"items": [{"instanceId": "i-12345"}]}
            }
        }
        mapping = {"response_key": "instancesSet.items[0].instanceId"}
        assert _extract_resource_id(detail, mapping) == "i-12345"


# ── _extract_user_identity ───────────────────────────────────────────


class TestExtractUserIdentity:
    def test_principal_id(self):
        detail = {"userIdentity": {"principalId": "AIDAEXAMPLE", "userName": "admin"}}
        assert _extract_user_identity(detail) == "AIDAEXAMPLE"

    def test_username_fallback(self):
        detail = {"userIdentity": {"userName": "admin"}}
        assert _extract_user_identity(detail) == "admin"

    def test_arn_fallback(self):
        detail = {"userIdentity": {"arn": "arn:aws:iam::role/test"}}
        assert _extract_user_identity(detail) == "arn:aws:iam::role/test"

    def test_unknown_fallback(self):
        detail = {"userIdentity": {}}
        assert _extract_user_identity(detail) == "unknown"

    def test_missing_identity(self):
        assert _extract_user_identity({}) == "unknown"


# ── _extract_vpc_id ──────────────────────────────────────────────────


class TestExtractVpcId:
    def test_direct_vpc_id(self):
        detail = {"requestParameters": {"vpcId": "vpc-abc123"}}
        assert _extract_vpc_id(detail) == "vpc-abc123"

    def test_nested_in_subnet(self):
        detail = {
            "responseElements": {"subnet": {"subnetId": "subnet-1", "vpcId": "vpc-nested"}}
        }
        assert _extract_vpc_id(detail) == "vpc-nested"

    def test_nested_in_nat_gateway(self):
        detail = {
            "responseElements": {
                "natGateway": {"natGatewayId": "nat-1", "vpcId": "vpc-nat"}
            }
        }
        assert _extract_vpc_id(detail) == "vpc-nat"

    def test_no_vpc_returns_empty(self):
        detail = {"requestParameters": {"groupId": "sg-123"}}
        assert _extract_vpc_id(detail) == ""


# ── poll_cloudtrail_events (mocked boto3) ────────────────────────────


class TestPollCloudtrailEvents:
    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_basic_polling(self, mock_boto3):
        events = [
            _make_cloudtrail_event(
                "CreateNatGateway",
                response_elements={
                    "natGateway": {"natGatewayId": "nat-test1", "vpcId": "vpc-1"}
                },
            ),
            _make_cloudtrail_event(
                "DeleteSubnet",
                request_params={"subnetId": "subnet-old"},
            ),
        ]
        mock_client = MagicMock()
        mock_client.get_paginator.return_value = _make_paginator(events)
        mock_boto3.client.return_value = mock_client

        changes = poll_cloudtrail_events(region="us-east-1", lookback_seconds=300)

        assert len(changes) == 2
        assert changes[0].entity_id == "nat-test1"
        assert changes[0].change_type == "node_added"
        assert changes[0].entity_type == "nat"
        assert changes[0].source == "cloudtrail"

        assert changes[1].entity_id == "subnet-old"
        assert changes[1].change_type == "node_removed"
        assert changes[1].entity_type == "subnet"

    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_filters_non_topology_events(self, mock_boto3):
        events = [
            _make_cloudtrail_event("DescribeInstances"),  # Read-only, not in map
            _make_cloudtrail_event(
                "CreateNatGateway",
                response_elements={
                    "natGateway": {"natGatewayId": "nat-1"}
                },
            ),
        ]
        mock_client = MagicMock()
        mock_client.get_paginator.return_value = _make_paginator(events)
        mock_boto3.client.return_value = mock_client

        changes = poll_cloudtrail_events()
        assert len(changes) == 1
        assert changes[0].entity_id == "nat-1"

    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_empty_events(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.get_paginator.return_value = _make_paginator([])
        mock_boto3.client.return_value = mock_client

        changes = poll_cloudtrail_events()
        assert changes == []

    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_boto3_error_returns_empty(self, mock_boto3):
        mock_boto3.client.side_effect = Exception("AWS credentials missing")
        changes = poll_cloudtrail_events()
        assert changes == []

    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_pagination_error_returns_partial(self, mock_boto3):
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        # Paginator raises on iteration
        mock_paginator.paginate.return_value = iter([Exception("throttled")])
        mock_client.get_paginator.return_value = mock_paginator
        mock_boto3.client.return_value = mock_client

        changes = poll_cloudtrail_events()
        # Should return empty, not crash
        assert changes == []

    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_malformed_cloudtrail_event_json(self, mock_boto3):
        event = {
            "EventName": "DeleteNatGateway",
            "EventTime": datetime.now(tz=timezone.utc),
            "CloudTrailEvent": "NOT-JSON{{{",
            "Resources": [{"ResourceName": "nat-fallback"}],
        }
        mock_client = MagicMock()
        mock_client.get_paginator.return_value = _make_paginator([event])
        mock_boto3.client.return_value = mock_client

        changes = poll_cloudtrail_events()
        assert len(changes) == 1
        assert changes[0].entity_id == "nat-fallback"

    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_security_group_events(self, mock_boto3):
        events = [
            _make_cloudtrail_event(
                "AuthorizeSecurityGroupIngress",
                request_params={"groupId": "sg-abc"},
            ),
            _make_cloudtrail_event(
                "RevokeSecurityGroupEgress",
                request_params={"groupId": "sg-xyz"},
            ),
        ]
        mock_client = MagicMock()
        mock_client.get_paginator.return_value = _make_paginator(events)
        mock_boto3.client.return_value = mock_client

        changes = poll_cloudtrail_events()
        assert len(changes) == 2
        assert all(c.change_type == "node_updated" for c in changes)
        assert all(c.entity_type == "sg" for c in changes)

    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_user_and_account_populated(self, mock_boto3):
        events = [
            _make_cloudtrail_event(
                "DeleteSubnet",
                request_params={"subnetId": "subnet-1"},
                user="cleanup-lambda",
                account_id="987654321012",
            ),
        ]
        mock_client = MagicMock()
        mock_client.get_paginator.return_value = _make_paginator(events)
        mock_boto3.client.return_value = mock_client

        changes = poll_cloudtrail_events()
        assert len(changes) == 1
        # principalId is preferred over userName in _extract_user_identity
        assert "CLEANUP-LAMBDA" in changes[0].source_detail.upper()
        assert changes[0].account_id == "987654321012"

    @patch("src.aci.topology.cloudtrail_poller.boto3")
    def test_vpc_peering_events(self, mock_boto3):
        events = [
            _make_cloudtrail_event(
                "CreateVpcPeeringConnection",
                response_elements={
                    "vpcPeeringConnection": {
                        "vpcPeeringConnectionId": "pcx-abc"
                    }
                },
            ),
        ]
        mock_client = MagicMock()
        mock_client.get_paginator.return_value = _make_paginator(events)
        mock_boto3.client.return_value = mock_client

        changes = poll_cloudtrail_events()
        assert len(changes) == 1
        assert changes[0].entity_id == "pcx-abc"
        assert changes[0].change_type == "edge_added"
        assert changes[0].entity_type == "PEERS_WITH"


# ── poll_and_store (async) ───────────────────────────────────────────


class TestPollAndStore:
    @pytest.mark.asyncio
    async def test_poll_and_store_persists(self):
        changes = [
            TopologyChange(
                change_type="node_added",
                entity_id="nat-async",
                entity_type="nat",
                source="cloudtrail",
                source_detail="CreateNatGateway",
                timestamp=datetime.now(tz=timezone.utc).isoformat(),
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_deltas.db")
            store = DeltaStore(db_path=db_path)

            with patch(
                "src.aci.topology.cloudtrail_poller.poll_cloudtrail_events",
                return_value=changes,
            ):
                count = await poll_and_store(store=store)

            assert count == 1
            recent = store.get_recent()
            assert len(recent) == 1
            assert recent[0].entity_id == "nat-async"

    @pytest.mark.asyncio
    async def test_poll_and_store_empty(self):
        with patch(
            "src.aci.topology.cloudtrail_poller.poll_cloudtrail_events",
            return_value=[],
        ):
            count = await poll_and_store()
        assert count == 0


# ── CloudTrailPollerLoop ─────────────────────────────────────────────


class TestCloudTrailPollerLoop:
    def test_init_defaults(self):
        poller = CloudTrailPollerLoop()
        assert not poller.is_running
        assert poller._interval > 0

    def test_status(self):
        poller = CloudTrailPollerLoop(poll_interval_s=60, region="us-west-2")
        status = poller.status()
        assert status["running"] is False
        assert status["interval_s"] == 60
        assert status["region"] == "us-west-2"

    @pytest.mark.asyncio
    async def test_start_stop(self):
        poller = CloudTrailPollerLoop(poll_interval_s=3600)

        with patch(
            "src.aci.topology.cloudtrail_poller.poll_and_store",
            new_callable=AsyncMock,
            return_value=0,
        ):
            poller.start()
            assert poller.is_running

            # Wait a bit for the initial delay to start
            await asyncio.sleep(0.1)

            poller.stop()
            assert not poller.is_running

    @pytest.mark.asyncio
    async def test_double_start_noop(self):
        poller = CloudTrailPollerLoop(poll_interval_s=3600)

        with patch(
            "src.aci.topology.cloudtrail_poller.poll_and_store",
            new_callable=AsyncMock,
            return_value=0,
        ):
            poller.start()
            task1 = poller._task
            poller.start()  # Should be no-op
            assert poller._task is task1
            poller.stop()


# ── Event mapping coverage ───────────────────────────────────────────


class TestEventMapping:
    def test_all_mappings_have_required_fields(self):
        for event_name, mapping in _MUTATING_EVENTS.items():
            assert "change_type" in mapping, f"{event_name} missing change_type"
            assert "entity_type" in mapping, f"{event_name} missing entity_type"
            assert (
                "response_key" in mapping or "request_key" in mapping
            ), f"{event_name} missing resource key"

    def test_mapping_count(self):
        # Ensure we have mappings for common AWS networking events
        assert len(_MUTATING_EVENTS) >= 20

    def test_change_types_valid(self):
        valid_types = {"node_added", "node_removed", "node_updated", "edge_added", "edge_removed"}
        for event_name, mapping in _MUTATING_EVENTS.items():
            assert mapping["change_type"] in valid_types, (
                f"{event_name} has invalid change_type: {mapping['change_type']}"
            )


# ── Module singleton ─────────────────────────────────────────────────


class TestModuleSingleton:
    def test_singleton_exists(self):
        assert cloudtrail_poller is not None
        assert isinstance(cloudtrail_poller, CloudTrailPollerLoop)

    def test_singleton_not_running_by_default(self):
        assert not cloudtrail_poller.is_running
