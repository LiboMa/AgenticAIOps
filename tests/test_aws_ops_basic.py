"""Tests for src/aws_ops.py — 0% coverage, add unit tests with mocked boto3."""

import pytest
from unittest.mock import patch, MagicMock


class TestAWSServiceOpsInit:
    @patch("src.aws_ops.boto3.Session")
    def test_init_default_region(self, mock_session):
        from src.aws_ops import AWSServiceOps
        ops = AWSServiceOps()
        assert ops.region == "ap-southeast-1"
        mock_session.assert_called_once_with(region_name="ap-southeast-1")

    @patch("src.aws_ops.boto3.Session")
    def test_init_custom_region(self, mock_session):
        from src.aws_ops import AWSServiceOps
        ops = AWSServiceOps(region="us-east-1")
        assert ops.region == "us-east-1"

    @patch("src.aws_ops.boto3.Session")
    def test_get_client(self, mock_session):
        from src.aws_ops import AWSServiceOps
        ops = AWSServiceOps()
        client = ops._get_client("ec2")
        mock_session.return_value.client.assert_called_with("ec2", region_name="ap-southeast-1")


class TestEC2HealthCheck:
    @patch("src.aws_ops.boto3.Session")
    def test_ec2_health_check_no_instances(self, mock_session):
        from src.aws_ops import AWSServiceOps
        mock_ec2 = MagicMock()
        mock_cw = MagicMock()
        mock_ec2.describe_instances.return_value = {"Reservations": []}
        mock_session.return_value.client.side_effect = lambda svc, **kw: {
            "ec2": mock_ec2, "cloudwatch": mock_cw
        }.get(svc, MagicMock())

        ops = AWSServiceOps()
        result = ops.ec2_health_check()
        assert isinstance(result, dict)

    @patch("src.aws_ops.boto3.Session")
    def test_ec2_health_check_with_instance(self, mock_session):
        from src.aws_ops import AWSServiceOps
        mock_ec2 = MagicMock()
        mock_cw = MagicMock()
        mock_ec2.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-123",
                    "State": {"Name": "running"},
                    "InstanceType": "t3.micro",
                    "LaunchTime": "2024-01-01T00:00:00Z",
                }]
            }]
        }
        mock_ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{
                "InstanceId": "i-123", "SystemStatus": {"Status": "ok"},
                "InstanceStatus": {"Status": "ok"},
            }]
        }
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}
        mock_cw.describe_alarms_for_metric.return_value = {"MetricAlarms": []}

        mock_session.return_value.client.side_effect = lambda svc, **kw: {
            "ec2": mock_ec2, "cloudwatch": mock_cw
        }.get(svc, MagicMock())

        ops = AWSServiceOps()
        result = ops.ec2_health_check(instance_id="i-123")
        assert isinstance(result, dict)
