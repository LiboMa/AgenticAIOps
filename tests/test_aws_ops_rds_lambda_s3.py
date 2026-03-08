"""Tests for aws_ops.py — RDS, Lambda, S3 operations."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from botocore.exceptions import ClientError

from src.aws_ops import AWSServiceOps


def _ce(code="TestError", msg="test"):
    return ClientError({"Error": {"Code": code, "Message": msg}}, "op")


def _dp(avg=50.0, mx=80.0, mn=10.0, s=500.0):
    return {"Average": avg, "Maximum": mx, "Minimum": mn, "Sum": s,
            "Timestamp": datetime.now(timezone.utc)}


@pytest.fixture
def ops():
    with patch("boto3.Session"):
        yield AWSServiceOps(region="us-east-1")


# ── RDS Health Check ──

class TestRDSHealthCheck:
    def _mock_clients(self, ops):
        rds = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"rds": rds, "cloudwatch": cw}.get(svc, MagicMock())
        return rds, cw

    def test_basic_healthy(self, ops):
        rds, cw = self._mock_clients(ops)
        rds.describe_db_instances.return_value = {
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
                "AvailabilityZone": "us-east-1a",
                "PubliclyAccessible": False,
            }]
        }
        cw.describe_alarms.return_value = {"MetricAlarms": []}
        cw.get_metric_statistics.return_value = {"Datapoints": [_dp()]}

        result = ops.rds_health_check()
        assert result["service"] == "RDS"
        assert len(result["databases"]) == 1

    def test_with_db_id(self, ops):
        rds, cw = self._mock_clients(ops)
        rds.describe_db_instances.return_value = {
            "DBInstances": [{
                "DBInstanceIdentifier": "prod-db",
                "DBInstanceStatus": "available",
                "Engine": "postgres",
                "EngineVersion": "15",
                "DBInstanceClass": "db.r5.large",
                "Endpoint": {"Address": "prod.xxx.rds.amazonaws.com", "Port": 5432},
                "MultiAZ": True,
                "StorageEncrypted": True,
                "AllocatedStorage": 100,
                "AvailabilityZone": "us-east-1a",
                "PubliclyAccessible": False,
            }]
        }
        cw.describe_alarms.return_value = {"MetricAlarms": []}
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.rds_health_check(db_id="prod-db")
        assert result["service"] == "RDS"

    def test_no_instances(self, ops):
        rds, cw = self._mock_clients(ops)
        rds.describe_db_instances.return_value = {"DBInstances": []}
        cw.describe_alarms.return_value = {"MetricAlarms": []}

        result = ops.rds_health_check()
        assert result["databases"] == []

    def test_error(self, ops):
        rds, _ = self._mock_clients(ops)
        rds.describe_db_instances.side_effect = _ce()

        result = ops.rds_health_check()
        assert "error" in result or result["overall_status"] != "healthy"


# ── RDS Get Metrics ──

class TestRDSGetMetrics:
    def test_basic(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.return_value = {"Datapoints": [_dp()]}

        result = ops.rds_get_metrics("mydb")
        assert result["db_id"] == "mydb"

    def test_error(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.side_effect = _ce()

        result = ops.rds_get_metrics("err-db")
        assert "error" in result or "metrics" in result


# ── RDS Get Logs ──

class TestRDSGetLogs:
    def test_basic(self, ops):
        rds = MagicMock()
        ops._get_client = lambda svc: rds
        rds.describe_db_log_files.return_value = {
            "DescribeDBLogFiles": [{"LogFileName": "error/mysql-error.log", "Size": 1024}]
        }
        rds.download_db_log_file_portion.return_value = {
            "LogFileData": "2024-01-01 ERROR test\n", "AdditionalDataPending": False
        }

        result = ops.rds_get_logs("mydb", log_type="error")
        assert result["db_id"] == "mydb"

    def test_error(self, ops):
        rds = MagicMock()
        ops._get_client = lambda svc: rds
        rds.describe_db_log_files.side_effect = _ce()

        result = ops.rds_get_logs("err-db")
        assert "error" in result or "logs" in result


# ── RDS Operations ──

class TestRDSOperations:
    def test_reboot(self, ops):
        rds = MagicMock()
        ops._get_client = lambda svc: rds
        rds.reboot_db_instance.return_value = {
            "DBInstance": {"DBInstanceIdentifier": "mydb", "DBInstanceStatus": "rebooting"}
        }

        result = ops.rds_operations("mydb", "reboot")
        assert result["action"] == "reboot"
        assert result["success"] is True

    def test_failover(self, ops):
        rds = MagicMock()
        ops._get_client = lambda svc: rds
        rds.reboot_db_instance.return_value = {
            "DBInstance": {"DBInstanceIdentifier": "mydb", "DBInstanceStatus": "rebooting"}
        }

        result = ops.rds_operations("mydb", "failover", force=True)
        assert result["action"] == "failover"
        assert result["success"] is True

    def test_unknown_action(self, ops):
        rds = MagicMock()
        ops._get_client = lambda svc: rds

        result = ops.rds_operations("mydb", "destroy")
        assert result["success"] is False

    def test_error(self, ops):
        rds = MagicMock()
        ops._get_client = lambda svc: rds
        rds.reboot_db_instance.side_effect = _ce()

        result = ops.rds_operations("mydb", "reboot")
        assert result["success"] is False
        assert "error" in result


# ── Lambda Health Check ──

class TestLambdaHealthCheck:
    def test_basic(self, ops):
        lam = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"lambda": lam, "cloudwatch": cw}.get(svc, MagicMock())

        lam.list_functions.return_value = {
            "Functions": [{
                "FunctionName": "my-func",
                "Runtime": "python3.11",
                "MemorySize": 128,
                "Timeout": 30,
                "CodeSize": 5000,
                "LastModified": "2024-01-01T00:00:00Z",
                "State": "Active",
            }],
            "NextMarker": None,
        }
        cw.get_metric_statistics.return_value = {"Datapoints": [_dp(5, 10, 1, 50)]}

        result = ops.lambda_health_check()
        assert result["service"] == "Lambda"
        assert len(result["functions"]) == 1

    def test_with_function_name(self, ops):
        lam = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"lambda": lam, "cloudwatch": cw}.get(svc, MagicMock())

        lam.get_function.return_value = {
            "Configuration": {
                "FunctionName": "specific-func",
                "Runtime": "nodejs18.x",
                "MemorySize": 256,
                "Timeout": 60,
                "CodeSize": 10000,
                "LastModified": "2024-06-01T00:00:00Z",
                "State": "Active",
            }
        }
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.lambda_health_check(function_name="specific-func")
        assert result["service"] == "Lambda"

    def test_no_functions(self, ops):
        lam = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"lambda": lam, "cloudwatch": cw}.get(svc, MagicMock())
        lam.list_functions.return_value = {"Functions": []}

        result = ops.lambda_health_check()
        assert result["functions"] == []

    def test_error(self, ops):
        lam = MagicMock()
        ops._get_client = lambda svc: lam
        lam.list_functions.side_effect = _ce()

        result = ops.lambda_health_check()
        assert "error" in result or result.get("overall_status") != "healthy"


# ── Lambda Get Logs ──

class TestLambdaGetLogs:
    def test_basic(self, ops):
        cw_logs = MagicMock()
        ops._get_client = lambda svc: cw_logs
        cw_logs.filter_log_events.return_value = {
            "events": [{"message": "START RequestId", "timestamp": 1700000000000}]
        }

        result = ops.lambda_get_logs("my-func")
        assert result["function_name"] == "my-func"

    def test_filter_errors(self, ops):
        cw_logs = MagicMock()
        ops._get_client = lambda svc: cw_logs
        cw_logs.filter_log_events.return_value = {"events": []}

        result = ops.lambda_get_logs("my-func", filter_errors=True)
        assert result["function_name"] == "my-func"

    def test_error(self, ops):
        cw_logs = MagicMock()
        ops._get_client = lambda svc: cw_logs
        cw_logs.filter_log_events.side_effect = _ce("ResourceNotFoundException")

        result = ops.lambda_get_logs("missing-func")
        assert "error" in result or "logs" in result


# ── Lambda Invoke ──

class TestLambdaInvoke:
    def test_sync(self, ops):
        lam = MagicMock()
        ops._get_client = lambda svc: lam
        lam.invoke.return_value = {
            "StatusCode": 200,
            "Payload": MagicMock(read=lambda: b'{"result": "ok"}'),
            "FunctionError": None,
        }

        result = ops.lambda_invoke("my-func", payload={"key": "val"})
        assert result["function_name"] == "my-func"
        assert result["status_code"] == 200

    def test_async(self, ops):
        lam = MagicMock()
        ops._get_client = lambda svc: lam
        lam.invoke.return_value = {
            "StatusCode": 202,
            "Payload": MagicMock(read=lambda: b''),
            "FunctionError": None,
        }

        result = ops.lambda_invoke("my-func", async_invoke=True)
        assert result["status_code"] == 202

    def test_error(self, ops):
        lam = MagicMock()
        ops._get_client = lambda svc: lam
        lam.invoke.side_effect = _ce()

        result = ops.lambda_invoke("err-func")
        assert "error" in result


# ── S3 Health Check ──

class TestS3HealthCheck:
    def test_basic(self, ops):
        s3 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"s3": s3, "cloudwatch": cw}.get(svc, MagicMock())

        s3.list_buckets.return_value = {
            "Buckets": [{"Name": "my-bucket", "CreationDate": datetime(2024, 1, 1, tzinfo=timezone.utc)}]
        }
        s3.get_bucket_versioning.return_value = {"Status": "Enabled"}
        s3.get_bucket_encryption.return_value = {
            "ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}
        }
        s3.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }
        }
        cw.get_metric_statistics.return_value = {"Datapoints": [_dp()]}

        result = ops.s3_health_check()
        assert result["service"] == "S3"

    def test_with_bucket_name(self, ops):
        s3 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"s3": s3, "cloudwatch": cw}.get(svc, MagicMock())

        s3.head_bucket.return_value = {}
        s3.get_bucket_versioning.return_value = {}
        s3.get_bucket_encryption.side_effect = _ce("ServerSideEncryptionConfigurationNotFoundError")
        s3.get_public_access_block.side_effect = _ce("NoSuchPublicAccessBlockConfiguration")
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.s3_health_check(bucket_name="specific-bucket")
        assert result["service"] == "S3"

    def test_error(self, ops):
        s3 = MagicMock()
        ops._get_client = lambda svc: s3
        s3.list_buckets.side_effect = _ce()

        result = ops.s3_health_check()
        assert "error" in result or result.get("overall_status") != "healthy"


# ── Detect Anomalies ──

class TestDetectAnomalies:
    def test_ec2_high_cpu(self, ops):
        ops.ec2_health_check = MagicMock(return_value={
            "instances": [{"id": "i-123", "cpu_max": 95, "health": "healthy", "issues": []}],
        })
        result = ops.detect_anomalies("ec2")
        assert result["service"] == "ec2"
        assert len(result["anomalies"]) == 1
        assert result["anomalies"][0]["type"] == "high_cpu"

    def test_ec2_unhealthy(self, ops):
        ops.ec2_health_check = MagicMock(return_value={
            "instances": [{"id": "i-bad", "cpu_max": 50, "health": "unhealthy", "issues": ["status failed"]}],
        })
        result = ops.detect_anomalies("ec2")
        assert any(a["type"] == "health_check_failed" for a in result["anomalies"])

    def test_ec2_no_anomalies(self, ops):
        ops.ec2_health_check = MagicMock(return_value={
            "instances": [{"id": "i-ok", "cpu_max": 30, "health": "healthy", "issues": []}],
        })
        result = ops.detect_anomalies("ec2")
        assert result["anomalies"] == []

    def test_rds_high_cpu(self, ops):
        ops.rds_health_check = MagicMock(return_value={
            "databases": [{"id": "db-1", "cpu_max": 85, "free_storage_gb": 50}],
        })
        result = ops.detect_anomalies("rds")
        assert any(a["type"] == "high_cpu" for a in result["anomalies"])

    def test_rds_low_storage(self, ops):
        ops.rds_health_check = MagicMock(return_value={
            "databases": [{"id": "db-1", "cpu_max": 30, "free_storage_gb": 5}],
        })
        result = ops.detect_anomalies("rds")
        assert any(a["type"] == "low_storage" for a in result["anomalies"])

    def test_lambda_errors(self, ops):
        ops.lambda_health_check = MagicMock(return_value={
            "functions": [{"name": "fn-1", "error_rate": 25, "throttles": 3}],
        })
        result = ops.detect_anomalies("lambda")
        assert any(a["type"] == "high_error_rate" for a in result["anomalies"])
        assert any(a["type"] == "throttling" for a in result["anomalies"])

    def test_unsupported_service(self, ops):
        result = ops.detect_anomalies("unknown-service")
        assert result["service"] == "unknown-service"
        assert result["anomalies"] == []
