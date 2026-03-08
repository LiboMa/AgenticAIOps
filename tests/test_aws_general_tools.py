#!/usr/bin/env python3
"""
Tests for src/skills/aws_general/tools.py

Targets uncovered: _boto_call helper and all 16 tool functions.
Uses mocked boto3 to avoid real AWS calls.
"""

import pytest
import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.skills.aws_general.tools import (
    _boto_call,
    ec2_describe_instances,
    ec2_instance_status,
    rds_describe_instances,
    lambda_list_functions,
    s3_list_buckets,
    cloudwatch_get_alarms,
    ecs_list_clusters,
    eks_list_clusters,
    asg_describe_groups,
    iam_get_account_summary,
    asg_set_desired_capacity,
    lambda_update_concurrency,
    ec2_reboot_instance,
    rds_failover,
    ec2_terminate_instance,
    rds_delete_instance,
)
from src.skills._security import set_agent_context
from src.skills._models import SecurityTier


class TestBotoCall:
    """Test the _boto_call helper."""

    def test_boto_call_with_mock(self):
        """Test _boto_call with a fully mocked boto3."""
        mock_client = MagicMock()
        mock_client.list_buckets.return_value = {
            "Buckets": [{"Name": "test-bucket"}],
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = _boto_call("s3", "list_buckets")
            assert "Buckets" in result
            assert "ResponseMetadata" not in result  # stripped

    def test_boto_call_error(self):
        """Test _boto_call when boto3 call raises."""
        mock_boto3 = MagicMock()
        mock_boto3.client.side_effect = Exception("No credentials")

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = _boto_call("s3", "list_buckets")
            assert "error" in result
            assert "No credentials" in result["error"]


class TestT0ReadOnlyTools:
    """Test all T0 (read-only) tools with mocked boto3."""

    @pytest.fixture(autouse=True)
    def mock_boto(self):
        self.mock_client = MagicMock()
        self.mock_boto3 = MagicMock()
        self.mock_boto3.client.return_value = self.mock_client

    def _run_tool(self, tool_fn, *args, **kwargs):
        """Run a tool with mocked boto3."""
        with patch.dict("sys.modules", {"boto3": self.mock_boto3}):
            return tool_fn(*args, **kwargs)

    def test_ec2_describe_instances_no_filter(self):
        self.mock_client.describe_instances.return_value = {
            "Reservations": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(ec2_describe_instances)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_ec2_describe_instances_with_filter(self):
        self.mock_client.describe_instances.return_value = {
            "Reservations": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(ec2_describe_instances, filters="web")
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_ec2_instance_status(self):
        self.mock_client.describe_instance_status.return_value = {
            "InstanceStatuses": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(ec2_instance_status)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_ec2_instance_status_with_ids(self):
        self.mock_client.describe_instance_status.return_value = {
            "InstanceStatuses": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(ec2_instance_status, instance_ids="i-123,i-456")
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_rds_describe_instances(self):
        self.mock_client.describe_db_instances.return_value = {
            "DBInstances": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(rds_describe_instances)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_lambda_list_functions(self):
        self.mock_client.list_functions.return_value = {
            "Functions": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(lambda_list_functions)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_s3_list_buckets(self):
        self.mock_client.list_buckets.return_value = {
            "Buckets": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(s3_list_buckets)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_cloudwatch_get_alarms(self):
        self.mock_client.describe_alarms.return_value = {
            "MetricAlarms": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(cloudwatch_get_alarms)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_ecs_list_clusters(self):
        self.mock_client.list_clusters.return_value = {
            "clusterArns": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(ecs_list_clusters)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_eks_list_clusters(self):
        self.mock_client.list_clusters.return_value = {
            "clusters": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(eks_list_clusters)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_asg_describe_groups_no_name(self):
        self.mock_client.describe_auto_scaling_groups.return_value = {
            "AutoScalingGroups": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(asg_describe_groups)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_asg_describe_groups_with_name(self):
        self.mock_client.describe_auto_scaling_groups.return_value = {
            "AutoScalingGroups": [],
            "ResponseMetadata": {},
        }
        result = self._run_tool(asg_describe_groups, name="my-asg")
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_iam_get_account_summary(self):
        self.mock_client.get_account_summary.return_value = {
            "SummaryMap": {},
            "ResponseMetadata": {},
        }
        result = self._run_tool(iam_get_account_summary)
        parsed = json.loads(result)
        assert parsed["status"] == "success"


class TestT1LowRiskTools:
    """Test T1 (low-risk write) tools."""

    @pytest.fixture(autouse=True)
    def mock_boto(self):
        self.mock_client = MagicMock()
        self.mock_boto3 = MagicMock()
        self.mock_boto3.client.return_value = self.mock_client
        # Elevate agent tier to allow T1+ tools
        set_agent_context("test-agent", SecurityTier.T3_DESTRUCTIVE)
        yield
        set_agent_context("unknown", SecurityTier.T0_READONLY)

    def _run_tool(self, tool_fn, *args, **kwargs):
        with patch.dict("sys.modules", {"boto3": self.mock_boto3}):
            return tool_fn(*args, **kwargs)

    def test_asg_set_desired_capacity(self):
        self.mock_client.set_desired_capacity.return_value = {"ResponseMetadata": {}}
        result = self._run_tool(asg_set_desired_capacity, group_name="my-asg", desired=3)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_lambda_update_concurrency(self):
        self.mock_client.put_function_concurrency.return_value = {
            "ReservedConcurrentExecutions": 10,
            "ResponseMetadata": {},
        }
        result = self._run_tool(lambda_update_concurrency, function_name="my-fn", concurrency=10)
        parsed = json.loads(result)
        assert parsed["status"] == "success"


class TestT2HighRiskTools:
    """Test T2 (high-risk) tools."""

    @pytest.fixture(autouse=True)
    def mock_boto(self):
        self.mock_client = MagicMock()
        self.mock_boto3 = MagicMock()
        self.mock_boto3.client.return_value = self.mock_client
        set_agent_context("test-agent", SecurityTier.T3_DESTRUCTIVE)
        yield
        set_agent_context("unknown", SecurityTier.T0_READONLY)

    def _run_tool(self, tool_fn, *args, **kwargs):
        with patch.dict("sys.modules", {"boto3": self.mock_boto3}):
            return tool_fn(*args, **kwargs)

    def test_ec2_reboot_instance(self):
        """T2 tools require approval_token — verify blocked without it."""
        self.mock_client.reboot_instances.return_value = {"ResponseMetadata": {}}
        result = self._run_tool(ec2_reboot_instance, instance_id="i-123")
        parsed = json.loads(result)
        assert parsed["status"] == "blocked"
        assert "approval" in (parsed.get("reason", "") or parsed.get("error", "")).lower()

    def test_rds_failover(self):
        """T2 tools require approval_token — verify blocked without it."""
        self.mock_client.failover_db_cluster.return_value = {"ResponseMetadata": {}}
        result = self._run_tool(rds_failover, db_cluster_id="my-cluster")
        parsed = json.loads(result)
        assert parsed["status"] == "blocked"


class TestT3DestructiveTools:
    """Test T3 (destructive) tools."""

    @pytest.fixture(autouse=True)
    def mock_boto(self):
        self.mock_client = MagicMock()
        self.mock_boto3 = MagicMock()
        self.mock_boto3.client.return_value = self.mock_client
        set_agent_context("test-agent", SecurityTier.T3_DESTRUCTIVE)
        yield
        set_agent_context("unknown", SecurityTier.T0_READONLY)

    def _run_tool(self, tool_fn, *args, **kwargs):
        with patch.dict("sys.modules", {"boto3": self.mock_boto3}):
            return tool_fn(*args, **kwargs)

    def test_ec2_terminate_instance(self):
        """T3 tools require dual approval — verify blocked without it."""
        self.mock_client.terminate_instances.return_value = {"ResponseMetadata": {}}
        result = self._run_tool(ec2_terminate_instance, instance_id="i-123")
        parsed = json.loads(result)
        assert parsed["status"] == "blocked"
        assert "approval" in (parsed.get("reason", "") or parsed.get("error", "")).lower()

    def test_rds_delete_instance(self):
        """T3 tools require dual approval — verify blocked without it."""
        self.mock_client.delete_db_instance.return_value = {"ResponseMetadata": {}}
        result = self._run_tool(rds_delete_instance, db_instance_id="my-db")
        parsed = json.loads(result)
        assert parsed["status"] == "blocked"
