"""
ACI Telemetry Logs — Unit Tests
Covers: LogsProvider get_logs, _get_pods, _get_pod_logs, _parse_log_line, _detect_log_level
Target: raise src/aci/telemetry/logs.py coverage from 34% → 80%+
"""

import subprocess
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.aci.telemetry.logs import LogsProvider
from src.aci.models import ResultStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    return LogsProvider(cluster_name="test-cluster", region="ap-southeast-1")


def _kubectl_ok(stdout=""):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _kubectl_fail(stderr="error"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# _detect_log_level
# ---------------------------------------------------------------------------

class TestDetectLogLevel:
    def test_error_keywords(self, provider):
        for msg in ["ERROR occurred", "NullPointerException", "fail to connect",
                     "FATAL crash", "CRITICAL issue"]:
            assert provider._detect_log_level(msg) == "error"

    def test_warning_keywords(self, provider):
        for msg in ["WARN: deprecated", "WARNING: disk 90%"]:
            assert provider._detect_log_level(msg) == "warning"

    def test_info_default(self, provider):
        assert provider._detect_log_level("All systems nominal") == "info"
        assert provider._detect_log_level("") == "info"


# ---------------------------------------------------------------------------
# _parse_log_line
# ---------------------------------------------------------------------------

class TestParseLogLine:
    def test_normal_line(self, provider):
        line = "2024-01-15T10:30:00.123456789Z GET /health 200"
        entry = provider._parse_log_line(line, "default", "pod-a", "main")
        assert entry is not None
        assert entry.message == "GET /health 200"
        assert entry.namespace == "default"
        assert entry.pod == "pod-a"
        assert entry.container == "main"
        assert entry.level == "info"
        assert entry.timestamp.year == 2024

    def test_error_message(self, provider):
        line = "2024-06-01T00:00:00.000Z ERROR something broke"
        entry = provider._parse_log_line(line, "ns", "pod", "c")
        assert entry.level == "error"

    def test_no_space_returns_none(self, provider):
        """Line without space separator → can't split → None."""
        entry = provider._parse_log_line("noseparator", "ns", "pod", "c")
        assert entry is None

    def test_malformed_timestamp(self, provider):
        entry = provider._parse_log_line("not-a-date some message", "ns", "pod", "c")
        # fromisoformat will fail → returns None
        assert entry is None


# ---------------------------------------------------------------------------
# _get_pods
# ---------------------------------------------------------------------------

class TestGetPods:
    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_normal(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("pod-a pod-b pod-c")
        pods = provider._get_pods("default")
        assert pods == ["pod-a", "pod-b", "pod-c"]

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_pattern_filter(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("nginx-abc nginx-xyz api-123")
        pods = provider._get_pods("default", "nginx*")
        assert pods == ["nginx-abc", "nginx-xyz"]

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_kubectl_fail(self, mock_run, provider):
        mock_run.return_value = _kubectl_fail("forbidden")
        pods = provider._get_pods("default")
        assert pods == []

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_timeout(self, mock_run, provider):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="kubectl", timeout=10)
        pods = provider._get_pods("default")
        assert pods == []

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_generic_exception(self, mock_run, provider):
        mock_run.side_effect = Exception("unexpected")
        pods = provider._get_pods("default")
        assert pods == []

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_empty_output(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("")
        pods = provider._get_pods("default")
        # "".strip().split() → []
        assert pods == []


# ---------------------------------------------------------------------------
# _get_pod_logs
# ---------------------------------------------------------------------------

class TestGetPodLogs:
    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_normal(self, mock_run, provider):
        stdout = (
            "2024-01-15T10:00:00.000Z line one\n"
            "2024-01-15T10:00:01.000Z line two\n"
        )
        mock_run.return_value = _kubectl_ok(stdout)
        logs = provider._get_pod_logs("default", "pod-a")
        assert len(logs) == 2
        assert logs[0].message == "line one"

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_with_container(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("2024-01-15T10:00:00.000Z hi\n")
        logs = provider._get_pod_logs("default", "pod-a", container="sidecar")
        # Verify container flag is passed
        call_args = mock_run.call_args
        assert "-c" in call_args[0][0]
        assert "sidecar" in call_args[0][0]

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_kubectl_fail(self, mock_run, provider):
        mock_run.return_value = _kubectl_fail("err")
        logs = provider._get_pod_logs("default", "pod-a")
        assert logs == []

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_timeout(self, mock_run, provider):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="kubectl", timeout=30)
        logs = provider._get_pod_logs("default", "pod-a")
        assert logs == []

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_generic_exception(self, mock_run, provider):
        mock_run.side_effect = Exception("disk full")
        logs = provider._get_pod_logs("default", "pod-a")
        assert logs == []

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_empty_lines_skipped(self, mock_run, provider):
        stdout = "2024-01-15T10:00:00.000Z ok\n\n\n"
        mock_run.return_value = _kubectl_ok(stdout)
        logs = provider._get_pod_logs("default", "pod-a")
        assert len(logs) == 1


# ---------------------------------------------------------------------------
# get_logs — integration of the above
# ---------------------------------------------------------------------------

class TestGetLogs:
    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_normal(self, mock_run, provider):
        # First call: _get_pods
        # Subsequent calls: _get_pod_logs
        mock_run.side_effect = [
            _kubectl_ok("pod-a"),
            _kubectl_ok("2024-01-15T10:00:00.000Z hello world\n"),
        ]
        result = provider.get_logs(namespace="default", pod_name="pod-a")
        assert result.status == ResultStatus.SUCCESS
        assert len(result.data) == 1

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_no_pods_found(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("")
        result = provider.get_logs(namespace="default", pod_name="nonexistent")
        assert result.status == ResultStatus.SUCCESS
        assert result.data == []
        assert "No pods found" in result.metadata["message"]

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_keyword_filter(self, mock_run, provider):
        mock_run.side_effect = [
            _kubectl_ok("pod-a"),
            _kubectl_ok(
                "2024-01-15T10:00:00.000Z ERROR db connection lost\n"
                "2024-01-15T10:00:01.000Z INFO request ok\n"
            ),
        ]
        result = provider.get_logs(namespace="default", pod_name="pod-a", keywords=["ERROR"])
        assert result.status == ResultStatus.SUCCESS
        assert len(result.data) == 1

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_severity_filter(self, mock_run, provider):
        mock_run.side_effect = [
            _kubectl_ok("pod-a"),
            _kubectl_ok(
                "2024-01-15T10:00:00.000Z ERROR something\n"
                "2024-01-15T10:00:01.000Z all good\n"
            ),
        ]
        result = provider.get_logs(namespace="default", pod_name="pod-a", severity="error")
        assert result.status == ResultStatus.SUCCESS
        assert len(result.data) == 1

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_exception_in_get_pods_returns_empty(self, mock_run, provider):
        """Exception in _get_pods is caught → returns empty pods → SUCCESS with no data."""
        mock_run.side_effect = Exception("catastrophe")
        result = provider.get_logs(namespace="default")
        assert result.status == ResultStatus.SUCCESS
        assert result.data == []

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_multiple_pods(self, mock_run, provider):
        mock_run.side_effect = [
            _kubectl_ok("pod-a pod-b"),
            _kubectl_ok("2024-01-15T10:00:00.000Z log from a\n"),
            _kubectl_ok("2024-01-15T10:00:01.000Z log from b\n"),
        ]
        result = provider.get_logs(namespace="default")
        assert result.status == ResultStatus.SUCCESS
        assert len(result.data) == 2
        assert "pods_queried" in result.metadata

    @patch("src.aci.telemetry.logs.subprocess.run")
    def test_limit_applied(self, mock_run, provider):
        lines = "\n".join(
            f"2024-01-15T10:00:{i:02d}.000Z line {i}" for i in range(20)
        )
        mock_run.side_effect = [
            _kubectl_ok("pod-a"),
            _kubectl_ok(lines),
        ]
        result = provider.get_logs(namespace="default", pod_name="pod-a", limit=5)
        assert len(result.data) <= 5
