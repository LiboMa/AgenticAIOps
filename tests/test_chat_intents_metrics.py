"""Tests for routers/chat_intents/metrics.py — keyword routing + helpers."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _patch_ops():
    with patch("routers.chat_intents.metrics._get_ops", return_value=None):
        yield


class TestMetricsHandle:

    @pytest.mark.asyncio
    async def test_no_match(self):
        from routers.chat_intents.metrics import handle
        assert await handle("hello", "hello") is None

    @pytest.mark.parametrize("msg", ["ec2 metrics i-abc", "ec2 指标 i-abc", "ec2 监控 i-abc"])
    @pytest.mark.asyncio
    async def test_ec2_metrics(self, msg):
        from routers.chat_intents.metrics import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    @pytest.mark.parametrize("msg", ["rds metrics mydb", "rds 指标 mydb", "rds 监控 mydb", "database metrics mydb"])
    @pytest.mark.asyncio
    async def test_rds_metrics(self, msg):
        from routers.chat_intents.metrics import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    @pytest.mark.parametrize("msg", ["lambda logs fn1", "lambda 日志 fn1", "function logs fn1"])
    @pytest.mark.asyncio
    async def test_lambda_logs(self, msg):
        from routers.chat_intents.metrics import handle
        result = await handle(msg, msg.lower())
        assert result is not None


class TestMetricsHelpers:

    def test_ec2_metrics_no_instance_id(self):
        ops = MagicMock()
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _ec2_metrics
            result = _ec2_metrics("ec2 metrics please")
            assert "请指定实例 ID" in result

    def test_ec2_metrics_success(self):
        ops = MagicMock()
        ops.ec2_get_metrics.return_value = {
            "metrics": {
                "CPUUtilization": {"avg": 25.0, "max": 80.0, "min": 5.0},
            },
        }
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _ec2_metrics
            result = _ec2_metrics("ec2 metrics i-abc123")
            assert "EC2 Metrics" in result
            assert "CPUUtilization" in result

    def test_ec2_metrics_exception(self):
        ops = MagicMock()
        ops.ec2_get_metrics.side_effect = RuntimeError("boom")
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _ec2_metrics
            result = _ec2_metrics("ec2 metrics i-abc")
            assert "失败" in result

    def test_rds_metrics_with_db_id(self):
        ops = MagicMock()
        ops.rds_get_metrics.return_value = {
            "metrics": {
                "CPUUtilization": {"avg": 40.0, "max": 90.0},
                "FreeStorageSpace": {"avg": 5368709120, "max": 5368709120},
            },
        }
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _rds_metrics
            result = _rds_metrics("rds metrics mydb")
            assert "RDS Metrics" in result

    def test_rds_metrics_no_db_id(self):
        """No specific DB ID → shows summary from rds_health_check."""
        ops = MagicMock()
        ops.rds_health_check.return_value = {
            "databases": [
                {"id": "mydb", "cpu_avg": 30, "cpu_max": 70, "connections": 10},
            ],
        }
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _rds_metrics
            result = _rds_metrics("rds metrics")
            assert "RDS Metrics Summary" in result

    def test_lambda_logs_with_name(self):
        ops = MagicMock()
        ops.lambda_get_logs.return_value = {
            "events": [
                {"timestamp": "2026-01-01T00:00:00", "message": "START RequestId"},
            ],
        }
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _lambda_logs
            result = _lambda_logs("lambda logs my-function", "lambda logs my-function")
            assert "Lambda Logs" in result
            assert "START" in result

    def test_lambda_logs_no_name(self):
        ops = MagicMock()
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _lambda_logs
            result = _lambda_logs("lambda logs", "lambda logs")
            assert "请指定函数名" in result

    def test_lambda_logs_empty(self):
        ops = MagicMock()
        ops.lambda_get_logs.return_value = {"events": []}
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _lambda_logs
            result = _lambda_logs("lambda logs fn1", "lambda logs fn1")
            assert "没有找到日志" in result

    def test_lambda_error_filter(self):
        ops = MagicMock()
        ops.lambda_get_logs.return_value = {"events": []}
        with patch("routers.chat_intents.metrics._get_ops", return_value=ops):
            from routers.chat_intents.metrics import _lambda_logs
            result = _lambda_logs("lambda error logs fn1", "lambda error logs fn1")
            ops.lambda_get_logs.assert_called_once_with("fn1", hours=1, filter_errors=True)
