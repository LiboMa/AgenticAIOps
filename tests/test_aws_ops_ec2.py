"""Tests for aws_ops.py — EC2 operations batch.

Coverage target: ec2_health_check, ec2_get_metrics, ec2_get_logs, ec2_operations.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from botocore.exceptions import ClientError

from src.aws_ops import AWSServiceOps, get_aws_ops


logger = __import__("logging").getLogger(__name__)


def _dp(avg=50.0, mx=80.0, mn=10.0, s=500.0, ts=None):
    """Build a CloudWatch datapoint dict with all required keys."""
    return {
        "Average": avg, "Maximum": mx, "Minimum": mn, "Sum": s,
        "Timestamp": ts or datetime.now(timezone.utc),
    }


@pytest.fixture
def ops():
    with patch("boto3.Session") as mock_session:
        svc = AWSServiceOps(region="us-east-1")
        yield svc


def _client_error(code="InvalidParameterValue", msg="test error"):
    return ClientError({"Error": {"Code": code, "Message": msg}}, "op")


# ── get_aws_ops factory ──

def test_get_aws_ops_returns_instance():
    with patch("boto3.Session"):
        obj = get_aws_ops("eu-west-1")
        assert isinstance(obj, AWSServiceOps)
        assert obj.region == "eu-west-1"


def test_get_aws_ops_default_region():
    with patch("boto3.Session"):
        obj = get_aws_ops()
        assert obj.region == "ap-southeast-1"


# ── EC2 Health Check ──

class TestEC2HealthCheck:
    def test_basic_healthy(self, ops):
        ec2 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: ec2 if svc == "ec2" else cw

        ec2.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-123",
                    "State": {"Name": "running"},
                    "InstanceType": "t3.micro",
                    "LaunchTime": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Tags": [{"Key": "Name", "Value": "web-1"}],
                    "Placement": {"AvailabilityZone": "us-east-1a"},
                }]
            }]
        }
        ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{
                "InstanceId": "i-123",
                "SystemStatus": {"Status": "ok"},
                "InstanceStatus": {"Status": "ok"},
            }]
        }
        cw.describe_alarms.return_value = {"MetricAlarms": []}
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.ec2_health_check()
        assert result["service"] == "EC2"
        assert result["overall_status"] == "healthy"
        assert len(result["instances"]) == 1
        assert result["instances"][0]["id"] == "i-123"

    def test_with_instance_id_filter(self, ops):
        ec2 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: ec2 if svc == "ec2" else cw

        ec2.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-456",
                    "State": {"Name": "running"},
                    "InstanceType": "t3.small",
                    "LaunchTime": datetime(2024, 6, 1, tzinfo=timezone.utc),
                    "Tags": [],
                    "Placement": {"AvailabilityZone": "us-east-1b"},
                }]
            }]
        }
        ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{
                "InstanceId": "i-456",
                "SystemStatus": {"Status": "ok"},
                "InstanceStatus": {"Status": "ok"},
            }]
        }
        cw.describe_alarms.return_value = {"MetricAlarms": []}
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.ec2_health_check(instance_id="i-456")
        assert result["instances"][0]["id"] == "i-456"

    def test_stopped_instance(self, ops):
        ec2 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: ec2 if svc == "ec2" else cw

        ec2.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-stopped",
                    "State": {"Name": "stopped"},
                    "InstanceType": "t3.large",
                    "LaunchTime": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Tags": [],
                    "Placement": {"AvailabilityZone": "us-east-1a"},
                }]
            }]
        }
        ec2.describe_instance_status.return_value = {"InstanceStatuses": []}
        cw.describe_alarms.return_value = {"MetricAlarms": []}
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.ec2_health_check()
        assert any("stopped" in str(i.get("state", "")).lower() or
                    "stopped" in str(i).lower()
                    for i in result["instances"])

    def test_with_alarms(self, ops):
        ec2 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: ec2 if svc == "ec2" else cw

        ec2.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-alarm",
                    "State": {"Name": "running"},
                    "InstanceType": "t3.micro",
                    "LaunchTime": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Tags": [],
                    "Placement": {"AvailabilityZone": "us-east-1a"},
                }]
            }]
        }
        ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{
                "InstanceId": "i-alarm",
                "SystemStatus": {"Status": "ok"},
                "InstanceStatus": {"Status": "impaired"},
            }]
        }
        cw.describe_alarms.return_value = {
            "MetricAlarms": [{
                "AlarmName": "HighCPU",
                "StateValue": "ALARM",
                "MetricName": "CPUUtilization",
            }]
        }
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.ec2_health_check()
        assert result["overall_status"] != "healthy" or len(result["issues"]) > 0

    def test_no_instances(self, ops):
        ec2 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: ec2 if svc == "ec2" else cw

        ec2.describe_instances.return_value = {"Reservations": []}
        ec2.describe_instance_status.return_value = {"InstanceStatuses": []}
        cw.describe_alarms.return_value = {"MetricAlarms": []}
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.ec2_health_check()
        assert result["service"] == "EC2"
        assert result["instances"] == []

    def test_client_error(self, ops):
        ec2 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: ec2 if svc == "ec2" else cw
        ec2.describe_instances.side_effect = _client_error()

        result = ops.ec2_health_check()
        assert "error" in result or result["overall_status"] != "healthy"

    def test_with_metric_datapoints(self, ops):
        ec2 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: ec2 if svc == "ec2" else cw

        ec2.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-metrics",
                    "State": {"Name": "running"},
                    "InstanceType": "m5.large",
                    "LaunchTime": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "Tags": [{"Key": "Name", "Value": "prod-web"}],
                    "Placement": {"AvailabilityZone": "us-east-1a"},
                }]
            }]
        }
        ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{
                "InstanceId": "i-metrics",
                "SystemStatus": {"Status": "ok"},
                "InstanceStatus": {"Status": "ok"},
            }]
        }
        cw.describe_alarms.return_value = {"MetricAlarms": []}
        cw.get_metric_statistics.return_value = {
            "Datapoints": [_dp(45.2, 80, 10, 450), _dp(55.1, 90, 20, 550)]
        }

        result = ops.ec2_health_check()
        assert result["service"] == "EC2"


# ── EC2 Get Metrics ──

class TestEC2GetMetrics:
    def test_basic(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw

        cw.get_metric_statistics.return_value = {
            "Datapoints": [_dp(30.5, 60, 5, 300)]
        }

        result = ops.ec2_get_metrics("i-123")
        assert result["instance_id"] == "i-123"
        assert "metrics" in result

    def test_custom_hours(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.ec2_get_metrics("i-123", hours=24)
        assert result["instance_id"] == "i-123"

    def test_error(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.side_effect = _client_error()

        result = ops.ec2_get_metrics("i-err")
        assert "error" in result or "metrics" in result


# ── EC2 Get Logs ──

class TestEC2GetLogs:
    def test_basic(self, ops):
        cw_logs = MagicMock()
        ops._get_client = lambda svc: cw_logs

        cw_logs.filter_log_events.return_value = {
            "events": [
                {"message": "test log line", "timestamp": 1700000000000},
            ]
        }

        result = ops.ec2_get_logs("i-123")
        assert result["instance_id"] == "i-123"

    def test_no_logs(self, ops):
        cw_logs = MagicMock()
        ops._get_client = lambda svc: cw_logs
        cw_logs.filter_log_events.return_value = {"events": []}

        result = ops.ec2_get_logs("i-nologs")
        assert result["instance_id"] == "i-nologs"

    def test_error(self, ops):
        cw_logs = MagicMock()
        ops._get_client = lambda svc: cw_logs
        cw_logs.filter_log_events.side_effect = _client_error("ResourceNotFoundException")

        result = ops.ec2_get_logs("i-err")
        assert "error" in result or "logs" in result


# ── EC2 Operations ──

class TestEC2Operations:
    def test_start(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2
        ec2.start_instances.return_value = {
            "StartingInstances": [{"InstanceId": "i-123", "CurrentState": {"Name": "pending"}}]
        }

        result = ops.ec2_operations("i-123", "start")
        assert result["action"] == "start"
        ec2.start_instances.assert_called_once()

    def test_stop(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2
        ec2.stop_instances.return_value = {
            "StoppingInstances": [{"InstanceId": "i-123", "CurrentState": {"Name": "stopping"}}]
        }

        result = ops.ec2_operations("i-123", "stop")
        assert result["action"] == "stop"

    def test_reboot(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2
        ec2.reboot_instances.return_value = {}

        result = ops.ec2_operations("i-123", "reboot")
        assert result["action"] == "reboot"

    def test_invalid_action(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2

        result = ops.ec2_operations("i-123", "destroy")
        assert "error" in result or "unsupported" in str(result).lower()

    def test_error(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2
        ec2.start_instances.side_effect = _client_error()

        result = ops.ec2_operations("i-123", "start")
        assert "error" in result
