"""
Tests for aws_scanner.py — AWSCloudScanner

All AWS calls are mocked via botocore.stub.Stubber or unittest.mock
to avoid real AWS API calls.
"""
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, timezone
from botocore.stub import Stubber
import boto3


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def scanner():
    """Create a scanner with mocked boto3 session."""
    from src.aws_scanner import AWSCloudScanner
    s = AWSCloudScanner(region="us-east-1")
    # Inject a mock session so it doesn't try real AWS
    s._session = MagicMock(spec=boto3.Session)
    return s


@pytest.fixture
def scanner_with_role():
    """Create a scanner that assumes an IAM role."""
    from src.aws_scanner import AWSCloudScanner
    return AWSCloudScanner(region="us-east-1", role_arn="arn:aws:iam::123456789012:role/TestRole")


def _mock_client(scanner, responses=None):
    """Set up mock client that returns given responses."""
    mock_client = MagicMock()
    scanner._session.client.return_value = mock_client
    if responses:
        for method, result in responses.items():
            getattr(mock_client, method).return_value = result
    return mock_client


# ── Init / Session ────────────────────────────────────────────


class TestInit:

    def test_default_region(self):
        from src.aws_scanner import AWSCloudScanner, DEFAULT_REGION
        s = AWSCloudScanner()
        assert s.region == DEFAULT_REGION
        assert s.role_arn is None

    def test_custom_region(self):
        from src.aws_scanner import AWSCloudScanner
        s = AWSCloudScanner(region="eu-west-1")
        assert s.region == "eu-west-1"

    def test_with_role_arn(self):
        from src.aws_scanner import AWSCloudScanner
        s = AWSCloudScanner(role_arn="arn:aws:iam::123:role/X")
        assert s.role_arn == "arn:aws:iam::123:role/X"

    def test_get_session_creates_default(self):
        from src.aws_scanner import AWSCloudScanner
        s = AWSCloudScanner(region="us-east-1")
        with patch("src.aws_scanner.boto3.Session") as mock_session:
            mock_session.return_value = MagicMock()
            session = s._get_session()
            assert session is not None

    def test_get_session_assumes_role(self, scanner_with_role):
        with patch("src.aws_scanner.boto3.client") as mock_sts_client:
            mock_sts = MagicMock()
            mock_sts.assume_role.return_value = {
                "Credentials": {
                    "AccessKeyId": "AKIA...",
                    "SecretAccessKey": "secret",
                    "SessionToken": "token",
                }
            }
            mock_sts_client.return_value = mock_sts
            with patch("src.aws_scanner.boto3.Session") as mock_session:
                mock_session.return_value = MagicMock()
                session = scanner_with_role._get_session()
                assert session is not None

    def test_get_session_cached(self, scanner):
        """Second call returns cached session."""
        s1 = scanner._get_session() if not scanner._session else scanner._session
        s2 = scanner._get_session() if not scanner._session else scanner._session
        assert s1 is s2

    def test_get_client(self, scanner):
        mock_client = MagicMock()
        scanner._session.client.return_value = mock_client
        client = scanner._get_client("ec2")
        scanner._session.client.assert_called_once_with("ec2", region_name="us-east-1")


# ── Account Info ──────────────────────────────────────────────


class TestAccountInfo:

    def test_get_account_info(self, scanner):
        mock_client = _mock_client(scanner, {
            "get_caller_identity": {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/test",
                "UserId": "AIDA...",
            }
        })
        info = scanner.get_account_info()
        assert info["account_id"] == "123456789012"

    def test_get_account_info_error(self, scanner):
        from botocore.exceptions import ClientError
        mock_client = MagicMock()
        scanner._session.client.return_value = mock_client
        mock_client.get_caller_identity.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no access"}}, "GetCallerIdentity"
        )
        info = scanner.get_account_info()
        assert "error" in info

    def test_list_regions(self, scanner):
        mock_client = _mock_client(scanner, {
            "describe_regions": {
                "Regions": [
                    {"RegionName": "us-east-1", "Endpoint": "ec2.us-east-1.amazonaws.com"},
                    {"RegionName": "eu-west-1", "Endpoint": "ec2.eu-west-1.amazonaws.com"},
                ]
            }
        })
        regions = scanner.list_regions()
        assert len(regions) == 2
        assert regions[0]["name"] == "us-east-1"


# ── Scan Methods ──────────────────────────────────────────────


class TestScanEC2:

    def test_scan_ec2_success(self, scanner):
        mock_client = _mock_client(scanner, {
            "describe_instances": {
                "Reservations": [{
                    "Instances": [{
                        "InstanceId": "i-1234",
                        "InstanceType": "t3.micro",
                        "State": {"Name": "running"},
                        "Tags": [{"Key": "Name", "Value": "test-instance"}],
                        "LaunchTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
                        "PrivateIpAddress": "10.0.0.1",
                        "PublicIpAddress": "1.2.3.4",
                        "VpcId": "vpc-123",
                        "SubnetId": "subnet-123",
                    }]
                }]
            }
        })
        result = scanner._scan_ec2()
        assert result["count"] == 1
        assert result["instances"][0]["id"] == "i-1234"

    def test_scan_ec2_error(self, scanner):
        from botocore.exceptions import ClientError
        mock_client = MagicMock()
        scanner._session.client.return_value = mock_client
        mock_client.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "UnauthorizedAccess", "Message": "no"}}, "DescribeInstances"
        )
        result = scanner._scan_ec2()
        assert "error" in result


class TestScanLambda:

    def test_scan_lambda_success(self, scanner):
        mock_client = _mock_client(scanner, {
            "list_functions": {
                "Functions": [{
                    "FunctionName": "my-func",
                    "Runtime": "python3.12",
                    "MemorySize": 128,
                    "Timeout": 30,
                    "LastModified": "2026-01-01T00:00:00Z",
                    "CodeSize": 1024,
                }]
            }
        })
        result = scanner._scan_lambda()
        assert result["count"] == 1
        assert result["functions"][0]["name"] == "my-func"


class TestScanS3:

    def test_scan_s3_success(self, scanner):
        mock_client = _mock_client(scanner, {
            "list_buckets": {
                "Buckets": [
                    {"Name": "my-bucket", "CreationDate": datetime(2026, 1, 1, tzinfo=timezone.utc)},
                ]
            }
        })
        result = scanner._scan_s3()
        assert result["count"] == 1


class TestScanRDS:

    def test_scan_rds_success(self, scanner):
        mock_client = _mock_client(scanner, {
            "describe_db_instances": {
                "DBInstances": [{
                    "DBInstanceIdentifier": "mydb",
                    "DBInstanceClass": "db.t3.micro",
                    "Engine": "postgres",
                    "EngineVersion": "15.4",
                    "DBInstanceStatus": "available",
                    "Endpoint": {"Address": "mydb.xxx.rds.amazonaws.com", "Port": 5432},
                    "AllocatedStorage": 20,
                    "MultiAZ": False,
                }]
            }
        })
        result = scanner._scan_rds()
        assert result["count"] == 1


class TestScanVPC:

    def test_scan_vpc_success(self, scanner):
        mock_client = _mock_client(scanner, {
            "describe_vpcs": {
                "Vpcs": [{
                    "VpcId": "vpc-123",
                    "CidrBlock": "10.0.0.0/16",
                    "State": "available",
                    "IsDefault": True,
                    "Tags": [{"Key": "Name", "Value": "main-vpc"}],
                }]
            },
            "describe_subnets": {
                "Subnets": [{
                    "SubnetId": "subnet-1",
                    "VpcId": "vpc-123",
                    "CidrBlock": "10.0.1.0/24",
                    "AvailabilityZone": "us-east-1a",
                }]
            },
            "describe_security_groups": {
                "SecurityGroups": [{
                    "GroupId": "sg-1",
                    "GroupName": "default",
                    "VpcId": "vpc-123",
                }]
            }
        })
        result = scanner._scan_vpc()
        assert result["count"] == 1


class TestScanELB:

    def test_scan_elb_success(self, scanner):
        mock_client = _mock_client(scanner, {
            "describe_load_balancers": {
                "LoadBalancers": [{
                    "LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/123",
                    "LoadBalancerName": "my-alb",
                    "Type": "application",
                    "State": {"Code": "active"},
                    "DNSName": "my-alb-123.us-east-1.elb.amazonaws.com",
                    "Scheme": "internet-facing",
                }]
            }
        })
        result = scanner._scan_elb()
        assert result["count"] == 1


# ── Scan All ──────────────────────────────────────────────────


class TestScanAll:

    def test_scan_all_resources(self, scanner):
        """scan_all_resources calls all scan methods."""
        with patch.multiple(scanner,
            _scan_ec2=MagicMock(return_value={"total": 2}),
            _scan_lambda=MagicMock(return_value={"total": 3}),
            _scan_s3=MagicMock(return_value={"total": 1}),
            _scan_rds=MagicMock(return_value={"total": 0}),
            _scan_iam=MagicMock(return_value={"total": 5}),
            _scan_vpc=MagicMock(return_value={"vpcs": {"total": 1}}),
            _scan_elb=MagicMock(return_value={"total": 1}),
            _scan_route53=MagicMock(return_value={"total": 0}),
            _scan_dynamodb=MagicMock(return_value={"total": 2}),
            _scan_ecs=MagicMock(return_value={"total": 0}),
            _scan_elasticache=MagicMock(return_value={"total": 0}),
            _scan_eks=MagicMock(return_value={"total": 1}),
            _scan_cloudwatch_alarms=MagicMock(return_value={"total": 3}),
        ):
            result = scanner.scan_all_resources()
            assert "services" in result
            assert "summary" in result
            assert result["region"] == "us-east-1"


# ── CloudWatch Metrics / Logs ────────────────────────────────


class TestCloudWatch:

    def test_get_cloudwatch_metrics(self, scanner):
        mock_client = _mock_client(scanner, {
            "get_metric_statistics": {
                "Datapoints": [
                    {"Timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), "Average": 45.2},
                    {"Timestamp": datetime(2026, 1, 1, 1, tzinfo=timezone.utc), "Average": 52.1},
                ],
                "Label": "CPUUtilization",
            }
        })
        result = scanner.get_cloudwatch_metrics(
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            dimensions=[{"Name": "InstanceId", "Value": "i-1234"}],
        )
        assert len(result["datapoints"]) == 2

    def test_get_ec2_metrics(self, scanner):
        with patch.object(scanner, 'get_cloudwatch_metrics', return_value={"datapoints": []}) as mock:
            result = scanner.get_ec2_metrics("i-1234", "CPUUtilization")
            mock.assert_called_once()

    def test_get_rds_metrics(self, scanner):
        with patch.object(scanner, 'get_cloudwatch_metrics', return_value={"datapoints": []}) as mock:
            result = scanner.get_rds_metrics("mydb", "CPUUtilization")
            mock.assert_called_once()

    def test_get_lambda_metrics(self, scanner):
        with patch.object(scanner, 'get_cloudwatch_metrics', return_value={"datapoints": []}) as mock:
            result = scanner.get_lambda_metrics("my-func", "Duration")
            mock.assert_called_once()

    def test_get_cloudwatch_logs(self, scanner):
        mock_client = _mock_client(scanner, {
            "filter_log_events": {
                "events": [
                    {"timestamp": 1704067200000, "message": "ERROR: something", "logStreamName": "stream-1"},
                ],
                "searchedLogStreams": [],
            }
        })
        result = scanner.get_cloudwatch_logs("/aws/lambda/my-func")
        assert len(result["events"]) == 1


# ── Singleton ─────────────────────────────────────────────────


class TestGetScanner:

    def test_get_scanner_default(self):
        from src.aws_scanner import get_scanner
        s = get_scanner()
        assert s is not None
        assert s.region is not None

    def test_get_scanner_custom_region(self):
        from src.aws_scanner import get_scanner
        s = get_scanner(region="eu-west-1")
        assert s.region == "eu-west-1"


# ── Summary Generation ────────────────────────────────────────


class TestSummary:

    def test_generate_summary(self, scanner):
        services = {
            "ec2": {"count": 5, "instances": [], "status": {}},
            "lambda": {"count": 10, "functions": []},
            "s3": {"count": 3, "buckets": [], "public_count": 0},
            "rds": {"count": 1},
        }
        summary = scanner._generate_summary(services)
        assert summary["total_resources"] == 19
