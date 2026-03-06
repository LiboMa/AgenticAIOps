"""
Daily coverage boost tests for src/skills/monitoring/tools.py (38% → targeting ~70%+).
Tests all 10 monitoring tools with mocked boto3 and requests.
"""

import pytest
import json
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def set_agent_tier():
    """Set agent tier high enough for all tools."""
    from src.skills._security import set_agent_context
    from src.skills._models import SecurityTier
    set_agent_context("test-agent", SecurityTier.T3_DESTRUCTIVE)
    yield
    set_agent_context("unknown", SecurityTier.T0_READONLY)


def _parse(result_json):
    """Parse ToolResult JSON and return dict."""
    return json.loads(result_json)


def _assert_success(result_json):
    r = _parse(result_json)
    assert r["status"] == "success", f"Expected success but got {r}"
    return r


def _assert_error(result_json):
    r = _parse(result_json)
    assert r["status"] in ("error", "blocked"), f"Expected error/blocked but got {r}"
    return r


# ── cw_get_alarms ──

class TestCWGetAlarms:
    @patch("src.skills.monitoring.tools._boto")
    def test_default_state(self, mock_boto):
        mock_boto.return_value = {"MetricAlarms": [{"AlarmName": "test-alarm"}]}
        from src.skills.monitoring.tools import cw_get_alarms
        _assert_success(cw_get_alarms(state="ALARM"))

    @patch("src.skills.monitoring.tools._boto")
    def test_ok_state(self, mock_boto):
        mock_boto.return_value = {"MetricAlarms": []}
        from src.skills.monitoring.tools import cw_get_alarms
        _assert_success(cw_get_alarms(state="OK"))


# ── cw_get_metric ──

class TestCWGetMetric:
    @patch("src.skills.monitoring.tools._boto")
    def test_basic(self, mock_boto):
        mock_boto.return_value = {"Datapoints": [{"Average": 42.0}]}
        from src.skills.monitoring.tools import cw_get_metric
        _assert_success(cw_get_metric(
            namespace="AWS/EC2", metric_name="CPUUtilization",
            dimensions="InstanceId=i-123", period=300, stat="Average", hours=1
        ))

    @patch("src.skills.monitoring.tools._boto")
    def test_no_dimensions(self, mock_boto):
        mock_boto.return_value = {"Datapoints": []}
        from src.skills.monitoring.tools import cw_get_metric
        _assert_success(cw_get_metric(
            namespace="AWS/RDS", metric_name="CPUUtilization",
            dimensions="", period=60, stat="Maximum", hours=2
        ))

    @patch("src.skills.monitoring.tools._boto")
    def test_hours_capped(self, mock_boto):
        mock_boto.return_value = {"Datapoints": []}
        from src.skills.monitoring.tools import cw_get_metric
        _assert_success(cw_get_metric(
            namespace="AWS/EC2", metric_name="CPUUtilization", hours=100
        ))


# ── cw_log_insights ──

class TestCWLogInsights:
    @patch("src.skills.monitoring.tools._boto")
    def test_basic(self, mock_boto):
        mock_boto.return_value = {"queryId": "abc-123"}
        from src.skills.monitoring.tools import cw_log_insights
        _assert_success(cw_log_insights(
            log_group="/aws/lambda/my-func",
            query="fields @timestamp | limit 10", hours=1
        ))


# ── cw_alarm_history ──

class TestCWAlarmHistory:
    @patch("src.skills.monitoring.tools._boto")
    def test_basic(self, mock_boto):
        mock_boto.return_value = {"AlarmHistoryItems": []}
        from src.skills.monitoring.tools import cw_alarm_history
        _assert_success(cw_alarm_history(alarm_name="test-alarm", days=7))

    @patch("src.skills.monitoring.tools._boto")
    def test_large_days_capped(self, mock_boto):
        mock_boto.return_value = {"AlarmHistoryItems": []}
        from src.skills.monitoring.tools import cw_alarm_history
        _assert_success(cw_alarm_history(alarm_name="test", days=60))


# ── prometheus_query ──

class TestPrometheusQuery:
    @patch("requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {"status": "success", "data": {"result": []}},
            status_code=200
        )
        from src.skills.monitoring.tools import prometheus_query
        _assert_success(prometheus_query(query="up", endpoint="http://localhost:9090"))

    @patch("requests.get")
    def test_connection_error(self, mock_get):
        mock_get.side_effect = ConnectionError("refused")
        from src.skills.monitoring.tools import prometheus_query
        _assert_error(prometheus_query(query="up"))


# ── prometheus_alerts ──

class TestPrometheusAlerts:
    @patch("requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = MagicMock(
            json=lambda: {"status": "success", "data": {"alerts": []}},
            status_code=200
        )
        from src.skills.monitoring.tools import prometheus_alerts
        _assert_success(prometheus_alerts(endpoint="http://localhost:9090"))

    @patch("requests.get")
    def test_failure(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        from src.skills.monitoring.tools import prometheus_alerts
        _assert_error(prometheus_alerts())


# ── cw_describe_log_groups ──

class TestCWDescribeLogGroups:
    @patch("src.skills.monitoring.tools._boto")
    def test_no_prefix(self, mock_boto):
        mock_boto.return_value = {"logGroups": [{"logGroupName": "/aws/lambda/test"}]}
        from src.skills.monitoring.tools import cw_describe_log_groups
        _assert_success(cw_describe_log_groups(prefix=""))

    @patch("src.skills.monitoring.tools._boto")
    def test_with_prefix(self, mock_boto):
        mock_boto.return_value = {"logGroups": []}
        from src.skills.monitoring.tools import cw_describe_log_groups
        _assert_success(cw_describe_log_groups(prefix="/aws/lambda"))


# ── health_check_summary ──

class TestHealthCheckSummary:
    @patch("src.skills.monitoring.tools._boto")
    def test_with_alarms(self, mock_boto):
        mock_boto.return_value = {"MetricAlarms": [{"AlarmName": "a1"}, {"AlarmName": "a2"}]}
        from src.skills.monitoring.tools import health_check_summary
        r = _assert_success(health_check_summary())
        assert r["data"]["cloudwatch_alarms"] == 2

    @patch("src.skills.monitoring.tools._boto")
    def test_error_response(self, mock_boto):
        mock_boto.return_value = {"error": "access denied"}
        from src.skills.monitoring.tools import health_check_summary
        r = _assert_success(health_check_summary())
        assert r["data"]["cloudwatch_alarms"] == 0


# ── cw_set_alarm_state (T1) ──

class TestCWSetAlarmState:
    @patch("src.skills.monitoring.tools._boto")
    def test_reset_to_ok(self, mock_boto):
        mock_boto.return_value = {}
        from src.skills.monitoring.tools import cw_set_alarm_state
        _assert_success(cw_set_alarm_state(alarm_name="test", state="OK", reason="reset"))


# ── cw_enable_alarm (T1) ──

class TestCWEnableAlarm:
    @patch("src.skills.monitoring.tools._boto")
    def test_enable(self, mock_boto):
        mock_boto.return_value = {}
        from src.skills.monitoring.tools import cw_enable_alarm
        _assert_success(cw_enable_alarm(alarm_name="test", enable=True))

    @patch("src.skills.monitoring.tools._boto")
    def test_disable(self, mock_boto):
        mock_boto.return_value = {}
        from src.skills.monitoring.tools import cw_enable_alarm
        _assert_success(cw_enable_alarm(alarm_name="test", enable=False))


# ── _boto helper ──

class TestBotoHelper:
    @patch("boto3.client")
    def test_success(self, mock_client):
        mock_svc = MagicMock()
        mock_svc.describe_alarms.return_value = {"ResponseMetadata": {}, "MetricAlarms": []}
        mock_client.return_value = mock_svc
        from src.skills.monitoring.tools import _boto
        result = _boto("cloudwatch", "describe_alarms", StateValue="ALARM")
        assert "ResponseMetadata" not in result
        assert "MetricAlarms" in result

    @patch("boto3.client")
    def test_error(self, mock_client):
        mock_client.side_effect = Exception("no credentials")
        from src.skills.monitoring.tools import _boto
        result = _boto("cloudwatch", "describe_alarms")
        assert "error" in result
