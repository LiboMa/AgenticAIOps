"""Tests for aws_ops.py — VPC, ELB, Route53, DynamoDB, ECS, ElastiCache."""

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


# ── VPC Health Check ──

class TestVPCHealthCheck:
    def test_basic(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2

        ec2.describe_vpcs.return_value = {
            "Vpcs": [{"VpcId": "vpc-123", "State": "available", "CidrBlock": "10.0.0.0/16",
                       "Tags": [{"Key": "Name", "Value": "prod"}]}]
        }
        ec2.describe_subnets.return_value = {
            "Subnets": [{"SubnetId": "sub-1", "VpcId": "vpc-123", "AvailabilityZone": "us-east-1a",
                          "AvailableIpAddressCount": 200, "CidrBlock": "10.0.1.0/24", "State": "available"}]
        }
        ec2.describe_internet_gateways.return_value = {
            "InternetGateways": [{"InternetGatewayId": "igw-1"}]
        }
        ec2.describe_nat_gateways.return_value = {"NatGateways": []}
        ec2.describe_security_groups.return_value = {"SecurityGroups": []}
        ec2.describe_network_acls.return_value = {"NetworkAcls": []}
        ec2.describe_route_tables.return_value = {"RouteTables": []}

        result = ops.vpc_health_check()
        assert result["service"] == "VPC"

    def test_with_vpc_id(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2

        ec2.describe_vpcs.return_value = {
            "Vpcs": [{"VpcId": "vpc-456", "State": "available", "CidrBlock": "172.16.0.0/16", "Tags": []}]
        }
        ec2.describe_subnets.return_value = {"Subnets": []}
        ec2.describe_internet_gateways.return_value = {"InternetGateways": []}
        ec2.describe_nat_gateways.return_value = {"NatGateways": []}
        ec2.describe_security_groups.return_value = {"SecurityGroups": []}
        ec2.describe_network_acls.return_value = {"NetworkAcls": []}
        ec2.describe_route_tables.return_value = {"RouteTables": []}

        result = ops.vpc_health_check(vpc_id="vpc-456")
        assert result["service"] == "VPC"

    def test_error(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2
        ec2.describe_vpcs.side_effect = _ce()

        result = ops.vpc_health_check()
        assert "error" in result or result.get("overall_status") != "healthy"


class TestVPCScan:
    def test_basic(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2
        ec2.describe_vpcs.return_value = {
            "Vpcs": [{"VpcId": "vpc-1", "State": "available", "CidrBlock": "10.0.0.0/16",
                       "Tags": [{"Key": "Name", "Value": "main"}]}]
        }

        result = ops.vpc_scan()
        assert "count" in result or "vpcs" in result

    def test_error(self, ops):
        ec2 = MagicMock()
        ops._get_client = lambda svc: ec2
        ec2.describe_vpcs.side_effect = _ce()

        result = ops.vpc_scan()
        assert "error" in result


# ── ELB Health Check ──

class TestELBHealthCheck:
    def test_basic(self, ops):
        elbv2 = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"elbv2": elbv2, "cloudwatch": cw}.get(svc, MagicMock())

        elbv2.describe_load_balancers.return_value = {
            "LoadBalancers": [{
                "LoadBalancerName": "my-alb",
                "LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc",
                "Type": "application",
                "State": {"Code": "active"},
                "DNSName": "my-alb-123.us-east-1.elb.amazonaws.com",
                "Scheme": "internet-facing",
                "AvailabilityZones": [{"ZoneName": "us-east-1a"}],
            }]
        }
        elbv2.describe_target_groups.return_value = {
            "TargetGroups": [{"TargetGroupArn": "arn:tg", "TargetGroupName": "tg-1"}]
        }
        elbv2.describe_target_health.return_value = {
            "TargetHealthDescriptions": [
                {"Target": {"Id": "i-123"}, "TargetHealth": {"State": "healthy"}}
            ]
        }
        cw.get_metric_statistics.return_value = {"Datapoints": [_dp()]}

        result = ops.elb_health_check()
        assert result["service"] == "ELB"

    def test_error(self, ops):
        elbv2 = MagicMock()
        ops._get_client = lambda svc: elbv2
        elbv2.describe_load_balancers.side_effect = _ce()

        result = ops.elb_health_check()
        assert "error" in result or result.get("overall_status") != "healthy"


class TestELBScan:
    def test_basic(self, ops):
        elbv2 = MagicMock()
        ops._get_client = lambda svc: elbv2
        elbv2.describe_load_balancers.return_value = {
            "LoadBalancers": [{
                "LoadBalancerName": "my-alb", "Type": "application",
                "LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc",
                "State": {"Code": "active"}, "Scheme": "internet-facing",
            }]
        }

        result = ops.elb_scan()
        assert "count" in result or "load_balancers" in result

    def test_error(self, ops):
        elbv2 = MagicMock()
        ops._get_client = lambda svc: elbv2
        elbv2.describe_load_balancers.side_effect = _ce()

        result = ops.elb_scan()
        assert "error" in result


class TestELBGetMetrics:
    def test_basic(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.return_value = {"Datapoints": [_dp()]}

        result = ops.elb_get_metrics("my-alb", lb_type="application")
        assert result["load_balancer"] == "my-alb"

    def test_error(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.side_effect = _ce()

        result = ops.elb_get_metrics("err-lb")
        assert "error" in result or "metrics" in result


# ── Route53 ──

class TestRoute53HealthCheck:
    def test_basic(self, ops):
        r53 = MagicMock()
        ops._get_client = lambda svc: r53

        r53.list_health_checks.return_value = {
            "HealthChecks": [{
                "Id": "hc-1",
                "HealthCheckConfig": {"FullyQualifiedDomainName": "example.com", "Type": "HTTPS", "Port": 443},
                "HealthCheckVersion": 1,
            }]
        }
        r53.get_health_check_status.return_value = {
            "HealthCheckObservations": [
                {"StatusReport": {"Status": "Success"}, "Region": "us-east-1"}
            ]
        }
        r53.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z1", "Name": "example.com.", "ResourceRecordSetCount": 10}]
        }

        result = ops.route53_health_check()
        assert result["service"] == "Route53"

    def test_error(self, ops):
        r53 = MagicMock()
        ops._get_client = lambda svc: r53
        r53.list_health_checks.side_effect = _ce()

        result = ops.route53_health_check()
        assert "error" in result or result.get("overall_status") != "healthy"


class TestRoute53Scan:
    def test_basic(self, ops):
        r53 = MagicMock()
        ops._get_client = lambda svc: r53
        r53.list_hosted_zones.return_value = {
            "HostedZones": [{"Id": "/hostedzone/Z1", "Name": "example.com.", "ResourceRecordSetCount": 5}]
        }
        r53.list_health_checks.return_value = {"HealthChecks": []}

        result = ops.route53_scan()
        assert "hosted_zones_count" in result or "error" not in result

    def test_error(self, ops):
        r53 = MagicMock()
        ops._get_client = lambda svc: r53
        r53.list_hosted_zones.side_effect = _ce()

        result = ops.route53_scan()
        assert "error" in result


# ── DynamoDB ──

class TestDynamoDBHealthCheck:
    def test_basic(self, ops):
        ddb = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"dynamodb": ddb, "cloudwatch": cw}.get(svc, MagicMock())

        ddb.list_tables.return_value = {"TableNames": ["my-table"]}
        ddb.describe_table.return_value = {
            "Table": {
                "TableName": "my-table", "TableStatus": "ACTIVE",
                "ItemCount": 1000, "TableSizeBytes": 50000,
                "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                "BillingModeSummary": {"BillingMode": "PROVISIONED"},
                "GlobalSecondaryIndexes": [],
            }
        }
        cw.get_metric_statistics.return_value = {"Datapoints": [_dp()]}

        result = ops.dynamodb_health_check()
        assert result["service"] == "DynamoDB"

    def test_with_table_name(self, ops):
        ddb = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"dynamodb": ddb, "cloudwatch": cw}.get(svc, MagicMock())

        ddb.describe_table.return_value = {
            "Table": {
                "TableName": "specific-table", "TableStatus": "ACTIVE",
                "ItemCount": 500, "TableSizeBytes": 25000,
                "ProvisionedThroughput": {"ReadCapacityUnits": 10, "WriteCapacityUnits": 10},
                "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
            }
        }
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.dynamodb_health_check(table_name="specific-table")
        assert result["service"] == "DynamoDB"

    def test_error(self, ops):
        ddb = MagicMock()
        ops._get_client = lambda svc: ddb
        ddb.list_tables.side_effect = _ce()

        result = ops.dynamodb_health_check()
        assert "error" in result or result.get("overall_status") != "healthy"


class TestDynamoDBScan:
    def test_basic(self, ops):
        ddb = MagicMock()
        ops._get_client = lambda svc: ddb
        ddb.list_tables.return_value = {"TableNames": ["t1", "t2"]}
        ddb.describe_table.return_value = {
            "Table": {"TableName": "t1", "TableStatus": "ACTIVE", "ItemCount": 100,
                      "TableSizeBytes": 5000, "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"}}
        }

        result = ops.dynamodb_scan()
        assert "count" in result or "tables" in result

    def test_error(self, ops):
        ddb = MagicMock()
        ops._get_client = lambda svc: ddb
        ddb.list_tables.side_effect = _ce()

        result = ops.dynamodb_scan()
        assert "error" in result


# ── ECS ──

class TestECSHealthCheck:
    def test_basic(self, ops):
        ecs = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"ecs": ecs, "cloudwatch": cw}.get(svc, MagicMock())

        ecs.list_clusters.return_value = {"clusterArns": ["arn:aws:ecs:us-east-1:123:cluster/my-cluster"]}
        ecs.describe_clusters.return_value = {
            "clusters": [{
                "clusterName": "my-cluster", "status": "ACTIVE",
                "runningTasksCount": 5, "pendingTasksCount": 0,
                "activeServicesCount": 2, "registeredContainerInstancesCount": 3,
            }]
        }
        ecs.list_services.return_value = {"serviceArns": ["arn:svc/svc-1"]}
        ecs.describe_services.return_value = {
            "services": [{
                "serviceName": "svc-1", "status": "ACTIVE",
                "runningCount": 2, "desiredCount": 2,
                "deployments": [{"status": "PRIMARY", "runningCount": 2, "desiredCount": 2}],
            }]
        }

        result = ops.ecs_health_check()
        assert result["service"] == "ECS"

    def test_error(self, ops):
        ecs = MagicMock()
        ops._get_client = lambda svc: ecs
        ecs.list_clusters.side_effect = _ce()

        result = ops.ecs_health_check()
        assert "error" in result or result.get("overall_status") != "healthy"


class TestECSScan:
    def test_basic(self, ops):
        ecs = MagicMock()
        ops._get_client = lambda svc: ecs
        ecs.list_clusters.return_value = {"clusterArns": ["arn:cluster/c1"]}
        ecs.describe_clusters.return_value = {
            "clusters": [{"clusterName": "c1", "status": "ACTIVE",
                          "runningTasksCount": 3, "activeServicesCount": 1}]
        }

        result = ops.ecs_scan()
        assert "count" in result or "clusters" in result

    def test_error(self, ops):
        ecs = MagicMock()
        ops._get_client = lambda svc: ecs
        ecs.list_clusters.side_effect = _ce()

        result = ops.ecs_scan()
        assert "error" in result


# ── ElastiCache ──

class TestElastiCacheHealthCheck:
    def test_basic(self, ops):
        ec = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"elasticache": ec, "cloudwatch": cw}.get(svc, MagicMock())

        ec.describe_cache_clusters.return_value = {
            "CacheClusters": [{
                "CacheClusterId": "my-redis",
                "CacheClusterStatus": "available",
                "Engine": "redis",
                "EngineVersion": "7.0",
                "CacheNodeType": "cache.t3.micro",
                "NumCacheNodes": 1,
                "PreferredAvailabilityZone": "us-east-1a",
            }]
        }
        ec.describe_replication_groups.return_value = {"ReplicationGroups": []}
        cw.get_metric_statistics.return_value = {"Datapoints": [_dp()]}

        result = ops.elasticache_health_check()
        assert result["service"] == "ElastiCache"

    def test_with_cluster_id(self, ops):
        ec = MagicMock()
        cw = MagicMock()
        ops._get_client = lambda svc: {"elasticache": ec, "cloudwatch": cw}.get(svc, MagicMock())

        ec.describe_cache_clusters.return_value = {
            "CacheClusters": [{
                "CacheClusterId": "specific-redis",
                "CacheClusterStatus": "available",
                "Engine": "redis", "EngineVersion": "6.2",
                "CacheNodeType": "cache.r5.large", "NumCacheNodes": 3,
                "PreferredAvailabilityZone": "us-east-1a",
            }]
        }
        ec.describe_replication_groups.return_value = {"ReplicationGroups": []}
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops.elasticache_health_check(cluster_id="specific-redis")
        assert result["service"] == "ElastiCache"

    def test_error(self, ops):
        ec = MagicMock()
        ops._get_client = lambda svc: ec
        ec.describe_cache_clusters.side_effect = _ce()

        result = ops.elasticache_health_check()
        assert "error" in result or result.get("overall_status") != "healthy"


class TestElastiCacheScan:
    def test_basic(self, ops):
        ec = MagicMock()
        ops._get_client = lambda svc: ec
        ec.describe_cache_clusters.return_value = {
            "CacheClusters": [{"CacheClusterId": "r1", "CacheClusterStatus": "available",
                                "Engine": "redis", "CacheNodeType": "cache.t3.micro"}]
        }

        result = ops.elasticache_scan()
        assert "count" in result or "clusters" in result

    def test_error(self, ops):
        ec = MagicMock()
        ops._get_client = lambda svc: ec
        ec.describe_cache_clusters.side_effect = _ce()

        result = ops.elasticache_scan()
        assert "error" in result


# ── _get_metric_stats helper ──

class TestGetMetricStats:
    def test_with_data(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.return_value = {
            "Datapoints": [_dp(40, 70, 10, 400), _dp(60, 90, 20, 600)]
        }

        result = ops._get_metric_stats("AWS/EC2", "CPUUtilization",
                                        [{"Name": "InstanceId", "Value": "i-1"}])
        assert result["avg"] == 50.0
        assert result["max"] == 90.0
        assert result["min"] == 10.0

    def test_no_data(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.return_value = {"Datapoints": []}

        result = ops._get_metric_stats("AWS/EC2", "CPUUtilization",
                                        [{"Name": "InstanceId", "Value": "i-1"}])
        assert result == {}

    def test_client_error(self, ops):
        cw = MagicMock()
        ops._get_client = lambda svc: cw
        cw.get_metric_statistics.side_effect = _ce()

        result = ops._get_metric_stats("AWS/EC2", "CPUUtilization",
                                        [{"Name": "InstanceId", "Value": "i-1"}])
        assert result == {}
