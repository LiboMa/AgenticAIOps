"""Tests for routers/chat_intents/resources.py — keyword routing + private helpers."""

import pytest
from unittest.mock import patch, MagicMock


def _make_scanner():
    """Build a mock scanner with stub return values for all _scan_* methods."""
    s = MagicMock()
    s.scan_all_resources.return_value = {
        "account": {"account_id": "123456789"},
        "region": "ap-southeast-1",
        "services": {
            "ec2": {"count": 3, "status": {"running": 2}},
            "s3": {"count": 5, "public_count": 1},
        },
        "summary": {"issues_found": [
            {"severity": "high", "service": "s3", "type": "public_bucket"},
        ]},
    }
    s.get_account_info.return_value = {
        "account_id": "123456789",
        "arn": "arn:aws:iam::123:user/admin",
    }
    s._scan_ec2.return_value = {
        "count": 2,
        "status": {"running": 1, "stopped": 1},
        "instances": [
            {"name": "web", "id": "i-1", "type": "t3.micro",
             "state": "running", "private_ip": "10.0.0.1"},
        ],
    }
    s._scan_lambda.return_value = {
        "count": 1,
        "functions": [
            {"name": "fn1", "runtime": "python3.12", "memory": 128, "timeout": 30},
        ],
    }
    s._scan_s3.return_value = {
        "count": 2,
        "public_count": 0,
        "buckets": [{"name": "data-bucket", "public": False}],
    }
    s._scan_rds.return_value = {
        "count": 1,
        "instances": [
            {"id": "mydb", "engine": "postgres", "class": "db.t3.medium",
             "status": "available", "public": False},
        ],
    }
    s._scan_dynamodb.return_value = {
        "count": 1,
        "tables": [
            {"name": "Users", "status": "ACTIVE", "billing_mode": "PAY",
             "read_capacity": 5, "write_capacity": 5, "item_count": 50},
        ],
    }
    s._scan_ecs.return_value = {
        "count": 1,
        "clusters": [
            {"name": "prod", "status": "ACTIVE", "running_tasks": 3,
             "pending_tasks": 0, "active_services": 2},
        ],
    }
    s._scan_elasticache.return_value = {
        "count": 1,
        "clusters": [
            {"id": "redis-1", "engine": "redis", "engine_version": "7.0",
             "status": "available", "node_type": "cache.t3.micro", "num_nodes": 1},
        ],
    }
    s._scan_vpc.return_value = {
        "count": 1,
        "vpcs": [
            {"name": "main", "id": "vpc-1", "cidr": "10.0.0.0/16",
             "state": "available", "is_default": True},
        ],
    }
    s._scan_elb.return_value = {
        "count": 1,
        "status": {"active": 1},
        "load_balancers": [
            {"name": "my-lb", "type": "ALB", "scheme": "internet-facing",
             "state": "active", "dns_name": "my-lb-123456.elb.amazonaws.com"},
        ],
    }
    return s


@pytest.fixture(autouse=True)
def _patch_scanner():
    scanner = _make_scanner()
    with patch("routers.chat_intents.resources.get_scanner", return_value=scanner):
        yield scanner


# ---------------------------------------------------------------------------
# handle() routing tests
# ---------------------------------------------------------------------------

class TestResourcesHandle:

    @pytest.mark.asyncio
    async def test_no_match(self):
        from routers.chat_intents.resources import handle
        assert await handle("random text", "random text") is None

    @pytest.mark.parametrize("msg", ["help", "commands", "帮助", "命令"])
    @pytest.mark.asyncio
    async def test_help(self, msg):
        from routers.chat_intents.resources import handle
        result = await handle(msg, msg.lower())
        assert "AgenticAIOps" in result or "Command" in result.lower() or "命令" in result

    @pytest.mark.parametrize("msg", ["scan", "扫描", "all resources", "所有资源"])
    @pytest.mark.asyncio
    async def test_scan(self, msg):
        from routers.chat_intents.resources import handle
        result = await handle(msg, msg.lower())
        assert "资源扫描" in result or "scan" in result.lower()

    @pytest.mark.asyncio
    async def test_region_switch(self):
        from routers.chat_intents.resources import handle
        result = await handle("region us-east-1", "region us-east-1")
        assert "us-east-1" in result
        assert "切换" in result

    @pytest.mark.parametrize("msg", ["account", "账号", "账户", "who am i"])
    @pytest.mark.asyncio
    async def test_account_info(self, msg):
        from routers.chat_intents.resources import handle
        result = await handle(msg, msg.lower())
        assert "123456789" in result

    @pytest.mark.asyncio
    async def test_ec2_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("show ec2 instances", "show ec2 instances")
        assert "EC2" in result
        assert "web" in result

    @pytest.mark.asyncio
    async def test_ec2_skips_health(self):
        """'ec2 health' should NOT match the resources handler."""
        from routers.chat_intents.resources import handle
        assert await handle("ec2 health", "ec2 health") is None

    @pytest.mark.asyncio
    async def test_ec2_skips_metrics(self):
        from routers.chat_intents.resources import handle
        assert await handle("ec2 metrics i-abc", "ec2 metrics i-abc") is None

    @pytest.mark.asyncio
    async def test_lambda_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("show lambda", "show lambda")
        assert "Lambda" in result

    @pytest.mark.asyncio
    async def test_lambda_skips_invoke(self):
        from routers.chat_intents.resources import handle
        assert await handle("lambda invoke fn1", "lambda invoke fn1") is None

    @pytest.mark.asyncio
    async def test_s3_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("list s3", "list s3")
        assert "S3" in result

    @pytest.mark.asyncio
    async def test_rds_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("show rds", "show rds")
        assert "RDS" in result

    @pytest.mark.asyncio
    async def test_dynamodb_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("dynamodb tables", "dynamodb tables")
        assert "DynamoDB" in result

    @pytest.mark.asyncio
    async def test_ecs_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("list ecs", "list ecs")
        assert "ECS" in result

    @pytest.mark.asyncio
    async def test_elasticache_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("show redis", "show redis")
        assert "ElastiCache" in result

    @pytest.mark.asyncio
    async def test_vpc_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("list vpc", "list vpc")
        assert "VPC" in result

    @pytest.mark.asyncio
    async def test_elb_list(self):
        from routers.chat_intents.resources import handle
        result = await handle("show elb", "show elb")
        assert "Load Balancer" in result


# ---------------------------------------------------------------------------
# Private helpers — edge cases
# ---------------------------------------------------------------------------

class TestResourceHelpers:

    def test_scan_all_exception(self, _patch_scanner):
        _patch_scanner.scan_all_resources.side_effect = RuntimeError("boom")
        from routers.chat_intents.resources import _scan_all
        result = _scan_all(_patch_scanner)
        assert "扫描失败" in result

    def test_list_ec2_exception(self, _patch_scanner):
        _patch_scanner._scan_ec2.side_effect = RuntimeError("boom")
        from routers.chat_intents.resources import _list_ec2
        result = _list_ec2(_patch_scanner)
        assert "失败" in result

    def test_list_ec2_overflow(self, _patch_scanner):
        """More than 10 instances triggers the '...还有' overflow message."""
        _patch_scanner._scan_ec2.return_value = {
            "count": 15,
            "status": {"running": 15, "stopped": 0},
            "instances": [
                {"name": f"inst-{i}", "id": f"i-{i}", "type": "t3.micro",
                 "state": "running", "private_ip": "10.0.0.1"}
                for i in range(15)
            ],
        }
        from routers.chat_intents.resources import _list_ec2
        result = _list_ec2(_patch_scanner)
        assert "还有" in result

    def test_dynamodb_error_response(self, _patch_scanner):
        _patch_scanner._scan_dynamodb.return_value = {"error": "Access Denied", "count": 0}
        from routers.chat_intents.resources import _list_dynamodb
        result = _list_dynamodb(_patch_scanner)
        assert "访问受限" in result

    def test_ecs_error_response(self, _patch_scanner):
        _patch_scanner._scan_ecs.return_value = {"error": "Access Denied", "count": 0}
        from routers.chat_intents.resources import _list_ecs
        result = _list_ecs(_patch_scanner)
        assert "访问受限" in result

    def test_elasticache_error_response(self, _patch_scanner):
        _patch_scanner._scan_elasticache.return_value = {"error": "Access Denied", "count": 0}
        from routers.chat_intents.resources import _list_elasticache
        result = _list_elasticache(_patch_scanner)
        assert "访问受限" in result

    def test_account_info_exception(self, _patch_scanner):
        _patch_scanner.get_account_info.side_effect = RuntimeError("boom")
        from routers.chat_intents.resources import _account_info
        result = _account_info(_patch_scanner)
        assert "失败" in result
