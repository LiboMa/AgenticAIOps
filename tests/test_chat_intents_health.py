"""Tests for routers/chat_intents/health.py — keyword routing + private helpers."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Keyword routing — every branch in handle()
# ---------------------------------------------------------------------------

class TestHealthHandle:
    """Verify that handle() dispatches to the correct helper for each keyword set."""

    @pytest.fixture(autouse=True)
    def _patch_ops(self):
        """Stub _get_ops so helpers don't hit real AWS."""
        with patch("routers.chat_intents.health._get_ops", return_value=None):
            yield

    @pytest.mark.asyncio
    async def test_no_match(self):
        from routers.chat_intents.health import handle
        assert await handle("hello world", "hello world") is None

    # --- EC2 Health ---
    @pytest.mark.parametrize("msg", [
        "ec2 health", "ec2 健康", "check ec2", "检查 ec2", "ec2 status",
    ])
    @pytest.mark.asyncio
    async def test_ec2_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None
        # ops is None → returns unavailable message
        assert "AWS Ops" in result or "EC2" in result

    # --- RDS Health ---
    @pytest.mark.parametrize("msg", [
        "rds health", "rds 健康", "check rds", "检查 rds", "database health", "数据库健康",
    ])
    @pytest.mark.asyncio
    async def test_rds_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- Lambda Health ---
    @pytest.mark.parametrize("msg", [
        "lambda health", "lambda 健康", "check lambda", "检查 lambda", "function health",
    ])
    @pytest.mark.asyncio
    async def test_lambda_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- S3 Health ---
    @pytest.mark.parametrize("msg", [
        "s3 health", "s3 健康", "check s3", "检查 s3", "bucket health", "s3 security",
    ])
    @pytest.mark.asyncio
    async def test_s3_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- VPC Health ---
    @pytest.mark.parametrize("msg", ["vpc health", "vpc 健康", "check vpc"])
    @pytest.mark.asyncio
    async def test_vpc_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- ELB Health ---
    @pytest.mark.parametrize("msg", ["elb health", "lb health", "load balancer health"])
    @pytest.mark.asyncio
    async def test_elb_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- Route53 Health ---
    @pytest.mark.parametrize("msg", ["route53 health", "dns health", "route 53"])
    @pytest.mark.asyncio
    async def test_route53_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- DynamoDB Health ---
    @pytest.mark.parametrize("msg", ["dynamodb health", "ddb health", "dynamo health"])
    @pytest.mark.asyncio
    async def test_dynamodb_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- ECS Health ---
    @pytest.mark.parametrize("msg", ["ecs health", "container health"])
    @pytest.mark.asyncio
    async def test_ecs_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- ElastiCache Health ---
    @pytest.mark.parametrize("msg", [
        "elasticache health", "cache health", "redis health", "memcached health",
    ])
    @pytest.mark.asyncio
    async def test_elasticache_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # --- Anomaly ---
    @pytest.mark.parametrize("msg", ["anomaly", "异常", "detect", "检测问题", "发现问题"])
    @pytest.mark.asyncio
    async def test_anomaly_keywords(self, msg):
        from routers.chat_intents.health import handle
        with patch("routers.chat_intents.health._anomaly", new_callable=AsyncMock, return_value="anomaly result"):
            result = await handle(msg, msg.lower())
            assert result is not None

    # --- General Health ---
    @pytest.mark.parametrize("msg", ["health", "健康", "状态检查", "status check", "诊断", "diagnose"])
    @pytest.mark.asyncio
    async def test_general_health_keywords(self, msg):
        from routers.chat_intents.health import handle
        result = await handle(msg, msg.lower())
        assert result is not None


# ---------------------------------------------------------------------------
# Private helpers — happy paths with mocked AWS ops
# ---------------------------------------------------------------------------

class TestHealthHelpers:
    """Test each _xxx_health() helper with a realistic mock ops object."""

    def _make_ops(self):
        ops = MagicMock()
        ops.ec2_health_check.return_value = {
            "overall_status": "healthy",
            "instances": [
                {"name": "web-1", "id": "i-abc", "state": "running",
                 "health": "healthy", "cpu_avg": 12.5, "issues": []},
            ],
            "issues": [],
        }
        ops.rds_health_check.return_value = {
            "overall_status": "warning",
            "databases": [
                {"id": "mydb", "engine": "mysql", "status": "available",
                 "health": "warning", "cpu_avg": 85, "connections": 42,
                 "issues": ["High CPU"]},
            ],
            "issues": [{"resource": "mydb", "issue": "High CPU"}],
        }
        ops.lambda_health_check.return_value = {
            "overall_status": "healthy",
            "functions": [
                {"name": "fn1", "health": "healthy", "invocations": 100,
                 "errors": 0, "error_rate": 0, "throttles": 0},
            ],
            "issues": [],
        }
        ops.s3_health_check.return_value = {
            "overall_status": "healthy",
            "public_buckets": 0,
            "buckets": [
                {"name": "my-bucket", "public": False, "encryption": "AES256",
                 "versioning": "Enabled", "issues": []},
            ],
            "issues": [],
        }
        ops.vpc_health_check.return_value = {
            "overall_status": "healthy",
            "vpcs": [
                {"name": "main", "id": "vpc-1", "state": "available",
                 "has_igw": True, "subnets_available": 3, "subnets_count": 3,
                 "nat_gateways": 1, "issues": []},
            ],
        }
        ops.elb_health_check.return_value = {
            "overall_status": "healthy",
            "load_balancers": [
                {"name": "my-lb", "type": "ALB", "state": "active",
                 "total_targets": 2, "unhealthy_targets": 0, "issues": []},
            ],
        }
        ops.route53_health_check.return_value = {
            "overall_status": "healthy",
            "hosted_zones": [
                {"name": "example.com", "id": "Z1", "private": False, "record_count": 10},
            ],
            "health_checks": [{"status": "healthy"}],
        }
        ops.dynamodb_health_check.return_value = {
            "overall_status": "healthy",
            "tables": [
                {"name": "Users", "status": "ACTIVE", "billing_mode": "PAY_PER_REQUEST",
                 "read_capacity": 0, "write_capacity": 0, "item_count": 100, "issues": []},
            ],
        }
        ops.ecs_health_check.return_value = {
            "overall_status": "healthy",
            "clusters": [
                {"name": "prod", "status": "ACTIVE", "running_tasks": 5,
                 "pending_tasks": 0, "active_services": 3, "issues": []},
            ],
        }
        ops.elasticache_health_check.return_value = {
            "overall_status": "healthy",
            "clusters": [
                {"id": "redis-1", "engine": "redis", "status": "available",
                 "num_nodes": 1, "hit_ratio": "99", "issues": []},
            ],
        }
        ops.detect_anomalies.return_value = {"anomalies": []}
        return ops

    @pytest.fixture(autouse=True)
    def _patch(self):
        self.ops = self._make_ops()
        with patch("routers.chat_intents.health._get_ops", return_value=self.ops):
            yield

    def test_ec2_health_happy(self):
        from routers.chat_intents.health import _ec2_health
        result = _ec2_health()
        assert "EC2 健康检查" in result
        assert "Healthy" in result
        assert "web-1" in result

    def test_ec2_health_with_issues(self):
        self.ops.ec2_health_check.return_value["overall_status"] = "warning"
        self.ops.ec2_health_check.return_value["issues"] = [
            {"resource": "i-abc", "issue": "High CPU"},
        ]
        from routers.chat_intents.health import _ec2_health
        result = _ec2_health()
        assert "发现问题" in result

    def test_ec2_health_exception(self):
        self.ops.ec2_health_check.side_effect = RuntimeError("boom")
        from routers.chat_intents.health import _ec2_health
        result = _ec2_health()
        assert "失败" in result

    def test_rds_health_happy(self):
        from routers.chat_intents.health import _rds_health
        result = _rds_health()
        assert "RDS 健康检查" in result
        assert "mydb" in result
        assert "发现问题" in result

    def test_lambda_health_happy(self):
        from routers.chat_intents.health import _lambda_health
        result = _lambda_health()
        assert "Lambda 健康检查" in result

    def test_s3_health_happy(self):
        from routers.chat_intents.health import _s3_health
        result = _s3_health()
        assert "S3 健康检查" in result

    def test_s3_health_public_bucket(self):
        self.ops.s3_health_check.return_value["public_buckets"] = 2
        from routers.chat_intents.health import _s3_health
        result = _s3_health()
        assert "2" in result

    def test_vpc_health_happy(self):
        from routers.chat_intents.health import _vpc_health
        result = _vpc_health()
        assert "VPC 健康检查" in result

    def test_elb_health_happy(self):
        from routers.chat_intents.health import _elb_health
        result = _elb_health()
        assert "ELB 健康检查" in result

    def test_route53_health_happy(self):
        from routers.chat_intents.health import _route53_health
        result = _route53_health()
        assert "Route 53" in result

    def test_route53_unhealthy_hc(self):
        self.ops.route53_health_check.return_value["health_checks"] = [
            {"status": "unhealthy"},
        ]
        from routers.chat_intents.health import _route53_health
        result = _route53_health()
        assert "unhealthy" in result

    def test_dynamodb_health_happy(self):
        from routers.chat_intents.health import _dynamodb_health
        result = _dynamodb_health()
        assert "DynamoDB 健康检查" in result

    def test_ecs_health_happy(self):
        from routers.chat_intents.health import _ecs_health
        result = _ecs_health()
        assert "ECS 健康检查" in result

    def test_elasticache_health_happy(self):
        from routers.chat_intents.health import _elasticache_health
        result = _elasticache_health()
        assert "ElastiCache 健康检查" in result

    def test_elasticache_health_error(self):
        self.ops.elasticache_health_check.return_value = {
            "error": "Access Denied",
        }
        from routers.chat_intents.health import _elasticache_health
        result = _elasticache_health()
        assert "访问受限" in result

    def test_general_health_no_issues(self):
        # Override rds mock to also be healthy (parent fixture has issues)
        self.ops.rds_health_check.return_value = {
            "overall_status": "healthy",
            "databases": [],
            "issues": [],
        }
        from routers.chat_intents.health import _general_health
        result = _general_health()
        assert "AWS 服务健康状态" in result
        assert "所有服务运行正常" in result

    def test_general_health_with_issues(self):
        self.ops.ec2_health_check.return_value["issues"] = [
            {"resource": "i-abc", "issue": "High CPU"},
        ]
        from routers.chat_intents.health import _general_health
        result = _general_health()
        assert "发现" in result and "问题" in result


# ---------------------------------------------------------------------------
# Anomaly helper
# ---------------------------------------------------------------------------

class TestAnomaly:

    @pytest.mark.asyncio
    async def test_anomaly_via_correlator_success(self):
        mock_event = MagicMock()
        mock_event.summary.return_value = "All clear"
        mock_correlator = MagicMock()
        mock_correlator.collect = AsyncMock(return_value=mock_event)

        with patch.dict("sys.modules", {"src.event_correlator": MagicMock(get_correlator=MagicMock(return_value=mock_correlator))}):
            from routers.chat_intents.health import _anomaly
            result = await _anomaly("anomaly ec2")
            assert result == "All clear"

    @pytest.mark.asyncio
    async def test_anomaly_correlator_fails_fallback_no_ops(self):
        """When correlator import raises → fallback to ops.  ops=None → unavailable."""
        # Make the import inside _anomaly raise
        bad_mod = MagicMock()
        bad_mod.get_correlator.side_effect = RuntimeError("no creds")
        with patch.dict("sys.modules", {"src.event_correlator": bad_mod}):
            with patch("routers.chat_intents.health._get_ops", return_value=None):
                from routers.chat_intents.health import _anomaly
                result = await _anomaly("detect issues")
                assert "AWS Ops" in result

    @pytest.mark.asyncio
    async def test_anomaly_fallback_no_anomalies(self):
        """Correlator fails, ops fallback finds no anomalies."""
        ops = MagicMock()
        ops.detect_anomalies.return_value = {"anomalies": []}
        bad_mod = MagicMock()
        bad_mod.get_correlator.side_effect = RuntimeError("fail")

        with patch.dict("sys.modules", {"src.event_correlator": bad_mod}):
            with patch("routers.chat_intents.health._get_ops", return_value=ops):
                from routers.chat_intents.health import _anomaly
                result = await _anomaly("anomaly")
                assert "未发现异常" in result

    @pytest.mark.asyncio
    async def test_anomaly_fallback_with_anomalies(self):
        """Correlator fails, ops fallback finds anomalies."""
        ops = MagicMock()
        ops.detect_anomalies.return_value = {
            "anomalies": [
                {"resource": "i-abc", "type": "ec2_high_cpu",
                 "value": "95%", "severity": "critical"},
            ],
        }
        bad_mod = MagicMock()
        bad_mod.get_correlator.side_effect = RuntimeError("fail")

        with patch.dict("sys.modules", {"src.event_correlator": bad_mod}):
            with patch("routers.chat_intents.health._get_ops", return_value=ops):
                from routers.chat_intents.health import _anomaly
                result = await _anomaly("异常")
                assert "发现" in result and "异常" in result


# ---------------------------------------------------------------------------
# _get_ops returns None
# ---------------------------------------------------------------------------

class TestOpsUnavailable:
    """Every helper must gracefully handle ops=None."""

    @pytest.fixture(autouse=True)
    def _no_ops(self):
        with patch("routers.chat_intents.health._get_ops", return_value=None):
            yield

    @pytest.mark.parametrize("func_name", [
        "_ec2_health", "_rds_health", "_lambda_health", "_s3_health",
        "_vpc_health", "_elb_health", "_route53_health", "_dynamodb_health",
        "_ecs_health", "_elasticache_health", "_general_health",
    ])
    def test_ops_none_returns_error(self, func_name):
        import routers.chat_intents.health as mod
        fn = getattr(mod, func_name)
        result = fn()
        assert "AWS Ops" in result or "not available" in result
