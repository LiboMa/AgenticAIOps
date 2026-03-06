"""Tests for src/aci/interface.py — AgentCloudInterface."""

import pytest
from unittest.mock import patch
from src.aci.interface import AgentCloudInterface
from src.aci.models import TelemetryResult, OperationResult, ResultStatus


@pytest.fixture
def aci():
    with patch("src.aci.interface.KubectlExecutor"), \
         patch("src.aci.interface.ShellExecutor"), \
         patch("src.aci.interface.SecurityFilter"), \
         patch("src.aci.interface.AuditLogger"), \
         patch("src.aci.interface.LogsProvider"), \
         patch("src.aci.interface.EventsProvider"), \
         patch("src.aci.interface.MetricsProvider"):
        yield AgentCloudInterface()


class TestInit:
    def test_defaults(self, aci):
        assert aci.cluster_name == "testing-cluster"
        assert aci.safe_mode is True


class TestGetLogs:
    def test_success(self, aci):
        aci._logs_provider.get_logs.return_value = TelemetryResult(status=ResultStatus.SUCCESS, data=["l1"])
        r = aci.get_logs(namespace="default", pod_name="nginx")
        assert r.status == ResultStatus.SUCCESS
        assert r.query_time_ms >= 0

    def test_error(self, aci):
        aci._logs_provider.get_logs.side_effect = RuntimeError("fail")
        r = aci.get_logs(namespace="default")
        assert r.status == ResultStatus.ERROR
        assert "fail" in r.error


class TestGetEvents:
    def test_success(self, aci):
        aci._events_provider.get_events.return_value = TelemetryResult(status=ResultStatus.SUCCESS, data=[])
        r = aci.get_events(namespace="all", event_type="Warning")
        assert r.status == ResultStatus.SUCCESS

    def test_error(self, aci):
        aci._events_provider.get_events.side_effect = Exception("timeout")
        r = aci.get_events(namespace="default")
        assert r.status == ResultStatus.ERROR


class TestGetMetrics:
    def test_success(self, aci):
        aci._metrics_provider.get_metrics.return_value = TelemetryResult(status=ResultStatus.SUCCESS, data=[])
        r = aci.get_metrics(namespace="default", metric_names=["cpu_usage"])
        assert r.status == ResultStatus.SUCCESS

    def test_error(self, aci):
        aci._metrics_provider.get_metrics.side_effect = Exception("no data")
        r = aci.get_metrics(namespace="default")
        assert r.status == ResultStatus.ERROR


class TestKubectl:
    def test_blocked(self, aci):
        aci._security.check_kubectl.return_value = (False, "dangerous")
        r = aci.kubectl(["delete", "ns", "kube-system"])
        assert r.status == ResultStatus.ERROR
        assert "Security blocked" in r.error

    def test_success(self, aci):
        aci._security.check_kubectl.return_value = (True, "")
        aci._kubectl.execute.return_value = OperationResult(
            status=ResultStatus.SUCCESS, command="kubectl get pods", stdout="{}")
        r = aci.kubectl(["get", "pods"])
        assert r.status == ResultStatus.SUCCESS


class TestExecShell:
    def test_blocked(self, aci):
        aci._security.check_shell.return_value = (False, "rm not allowed")
        r = aci.exec_shell("rm -rf /")
        assert r.status == ResultStatus.ERROR

    def test_success(self, aci):
        aci._security.check_shell.return_value = (True, "")
        aci._shell.execute.return_value = OperationResult(
            status=ResultStatus.SUCCESS, command="ls", stdout="file.txt")
        r = aci.exec_shell("ls")
        assert r.status == ResultStatus.SUCCESS
