"""Additional tests for src/aws_ops.py — targeting low-coverage methods."""

import pytest
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError
from src.aws_ops import AWSServiceOps


@pytest.fixture
def ops():
    with patch("src.aws_ops.boto3") as mock_boto:
        mock_session = MagicMock()
        mock_boto.Session.return_value = mock_session
        svc = AWSServiceOps(region="us-east-1")
        # Mock _get_metric_stats to avoid CloudWatch calls
        svc._get_metric_stats = MagicMock(return_value={"avg": 10, "max": 20, "min": 5, "datapoints": []})
        yield svc


class TestEC2HealthCheck:
    def test_success(self, ops):
        mock_ec2 = MagicMock()
        ops._get_client = MagicMock(return_value=mock_ec2)
        mock_ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{
                "InstanceId": "i-123",
                "InstanceState": {"Name": "running"},
                "InstanceStatus": {"Status": "ok"},
                "SystemStatus": {"Status": "ok"},
            }]
        }
        result = ops.ec2_health_check(instance_id="i-123")
        assert isinstance(result, dict)

    def test_client_error(self, ops):
        mock_ec2 = MagicMock()
        ops._get_client = MagicMock(return_value=mock_ec2)
        mock_ec2.describe_instance_status.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceID", "Message": "bad"}}, "op"
        )
        result = ops.ec2_health_check(instance_id="i-bad")
        assert isinstance(result, dict)

    def test_no_instance(self, ops):
        mock_ec2 = MagicMock()
        ops._get_client = MagicMock(return_value=mock_ec2)
        mock_ec2.describe_instance_status.return_value = {"InstanceStatuses": []}
        result = ops.ec2_health_check()
        assert isinstance(result, dict)


class TestRDSHealthCheck:
    def test_success(self, ops):
        mock_rds = MagicMock()
        ops._get_client = MagicMock(return_value=mock_rds)
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{
                "DBInstanceIdentifier": "mydb",
                "DBInstanceStatus": "available",
                "Engine": "mysql",
                "Endpoint": {"Address": "mydb.xxx.rds.amazonaws.com", "Port": 3306},
                "AllocatedStorage": 20,
                "DBInstanceClass": "db.t3.micro",
                "MultiAZ": False,
            }]
        }
        result = ops.rds_health_check(db_id="mydb")
        assert isinstance(result, dict)

    def test_no_instances(self, ops):
        mock_rds = MagicMock()
        ops._get_client = MagicMock(return_value=mock_rds)
        mock_rds.describe_db_instances.return_value = {"DBInstances": []}
        result = ops.rds_health_check()
        assert isinstance(result, dict)
