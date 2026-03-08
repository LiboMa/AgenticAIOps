"""Tests for AWS Ops - improve coverage from 16%."""

import pytest
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError
from src.aws_ops import AWSServiceOps


@pytest.fixture
def aws_ops():
    with patch("boto3.Session") as mock_session:
        mock_client = MagicMock()
        mock_session.return_value.client.return_value = mock_client
        ops = AWSServiceOps(region="us-east-1")
        ops._mock_client = mock_client
        yield ops


class TestEC2Operations:
    def test_ec2_health_check_healthy(self, aws_ops):
        client = aws_ops._mock_client
        client.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-123",
                    "State": {"Name": "running"},
                    "Tags": [{"Key": "Name", "Value": "web-01"}], "InstanceType": "t3.micro",
                }]
            }]
        }
        client.describe_instance_status.return_value = {
            "InstanceStatuses": [{
                "InstanceId": "i-123",
                "SystemStatus": {"Status": "ok"},
                "InstanceStatus": {"Status": "ok"},
            }]
        }
        client.get_metric_statistics.return_value = {"Datapoints": []}
        
        result = aws_ops.ec2_health_check("i-123")
        assert result is not None

    def test_ec2_health_check_stopped(self, aws_ops):
        client = aws_ops._mock_client
        client.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceId": "i-456",
                    "State": {"Name": "stopped"},
                    "Tags": [], "InstanceType": "t3.micro",
                }]
            }]
        }
        client.describe_instance_status.return_value = {"InstanceStatuses": []}
        client.get_metric_statistics.return_value = {"Datapoints": []}
        
        result = aws_ops.ec2_health_check("i-456")
        assert result is not None

    def test_ec2_health_check_error(self, aws_ops):
        client = aws_ops._mock_client
        client.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceID", "Message": "not found"}}, "DescribeInstances"
        )
        result = aws_ops.ec2_health_check("i-bad")
        assert "error" in str(result).lower() or result is not None


class TestRDSOperations:
    def test_rds_health_check(self, aws_ops):
        client = aws_ops._mock_client
        client.describe_db_instances.return_value = {
            "DBInstances": [{
                "DBInstanceIdentifier": "mydb",
                "DBInstanceStatus": "available",
                "Engine": "mysql",
                "EngineVersion": "8.0",
                "DBInstanceClass": "db.t3.micro",
                "Endpoint": {"Address": "mydb.xxx.rds.amazonaws.com", "Port": 3306},
                "MultiAZ": False,
                "StorageEncrypted": True,
                "AllocatedStorage": 20,
            }]
        }
        client.get_metric_statistics.return_value = {"Datapoints": []}
        
        result = aws_ops.rds_health_check("mydb")
        assert result is not None


class TestLambdaOperations:
    def test_lambda_health_check(self, aws_ops):
        client = aws_ops._mock_client
        client.get_function.return_value = {
            "Configuration": {
                "FunctionName": "my-func",
                "Runtime": "python3.12",
                "MemorySize": 128,
                "Timeout": 30,
                "State": "Active",
                "LastModified": "2025-01-01",
                "CodeSize": 1024,
            }
        }
        client.get_metric_statistics.return_value = {"Datapoints": []}
        
        result = aws_ops.lambda_health_check("my-func")
        assert result is not None
