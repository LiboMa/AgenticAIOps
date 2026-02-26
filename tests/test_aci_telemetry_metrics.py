"""
ACI Telemetry Metrics — Unit Tests
Covers: MetricsProvider get_metrics, _get_cloudwatch_metric, _parse_cpu, _parse_memory
Target: raise src/aci/telemetry/metrics.py coverage from 42% → 80%+
"""

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from src.aci.telemetry.metrics import MetricsProvider, PREDEFINED_METRICS
from src.aci.models import ResultStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    return MetricsProvider(cluster_name="test-cluster", region="ap-southeast-1")


def _kubectl_ok(stdout=""):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _kubectl_fail(stderr="error"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# _parse_cpu
# ---------------------------------------------------------------------------

class TestParseCpu:
    def test_millicores(self, provider):
        assert provider._parse_cpu("10m") == 10.0

    def test_millicores_large(self, provider):
        assert provider._parse_cpu("500m") == 500.0

    def test_whole_cores(self, provider):
        assert provider._parse_cpu("1") == 1000.0

    def test_fractional_cores(self, provider):
        assert provider._parse_cpu("0.5") == 500.0

    def test_invalid(self, provider):
        assert provider._parse_cpu("abc") == 0.0

    def test_empty(self, provider):
        assert provider._parse_cpu("") == 0.0


# ---------------------------------------------------------------------------
# _parse_memory
# ---------------------------------------------------------------------------

class TestParseMemory:
    def test_mi(self, provider):
        assert provider._parse_memory("50Mi") == 50 * 1024 * 1024

    def test_gi(self, provider):
        assert provider._parse_memory("1Gi") == 1024 * 1024 * 1024

    def test_ki(self, provider):
        assert provider._parse_memory("100Ki") == 100 * 1024

    def test_plain_number(self, provider):
        assert provider._parse_memory("12345") == 12345.0

    def test_invalid(self, provider):
        assert provider._parse_memory("badvalue") == 0.0

    def test_empty(self, provider):
        assert provider._parse_memory("") == 0.0

    def test_gi_fractional(self, provider):
        assert provider._parse_memory("0.5Gi") == 0.5 * 1024 * 1024 * 1024


# ---------------------------------------------------------------------------
# _get_cloudwatch_metric
# ---------------------------------------------------------------------------

class TestGetCloudwatchMetric:
    METRIC_DEF = PREDEFINED_METRICS["cpu_usage"]["cloudwatch"]

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_normal(self, mock_run, provider):
        stdout = "pod-a   100m   50Mi\npod-b   200m   1Gi\n"
        mock_run.return_value = _kubectl_ok(stdout)
        metrics = provider._get_cloudwatch_metric("default", self.METRIC_DEF, 5)
        # 2 pods × 2 metrics (cpu + memory) = 4
        assert len(metrics) == 4
        cpu_metrics = [m for m in metrics if m["metric_name"] == "cpu_usage"]
        mem_metrics = [m for m in metrics if m["metric_name"] == "memory_usage"]
        assert len(cpu_metrics) == 2
        assert len(mem_metrics) == 2
        assert cpu_metrics[0]["value"] == 100.0
        assert cpu_metrics[1]["value"] == 200.0

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_kubectl_fail(self, mock_run, provider):
        mock_run.return_value = _kubectl_fail("metrics API not available")
        metrics = provider._get_cloudwatch_metric("default", self.METRIC_DEF, 5)
        assert metrics == []

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_timeout(self, mock_run, provider):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="kubectl", timeout=30)
        metrics = provider._get_cloudwatch_metric("default", self.METRIC_DEF, 5)
        assert metrics == []

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_generic_exception(self, mock_run, provider):
        mock_run.side_effect = Exception("boom")
        metrics = provider._get_cloudwatch_metric("default", self.METRIC_DEF, 5)
        assert metrics == []

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_empty_output(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("")
        metrics = provider._get_cloudwatch_metric("default", self.METRIC_DEF, 5)
        assert metrics == []

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_short_line_skipped(self, mock_run, provider):
        stdout = "pod-a   100m\n"  # only 2 parts, needs >= 3
        mock_run.return_value = _kubectl_ok(stdout)
        metrics = provider._get_cloudwatch_metric("default", self.METRIC_DEF, 5)
        assert metrics == []

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_labels_present(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("pod-x   10m   20Mi\n")
        metrics = provider._get_cloudwatch_metric("myns", self.METRIC_DEF, 5)
        for m in metrics:
            assert m["labels"]["pod"] == "pod-x"
            assert m["labels"]["namespace"] == "myns"
            assert "timestamp" in m


# ---------------------------------------------------------------------------
# get_metrics
# ---------------------------------------------------------------------------

class TestGetMetrics:
    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_default_metrics(self, mock_run, provider):
        """No metric_names → defaults to cpu_usage + memory_usage."""
        mock_run.return_value = _kubectl_ok("pod-a   10m   50Mi\n")
        result = provider.get_metrics(namespace="default")
        assert result.status == ResultStatus.SUCCESS
        # Default calls _get_cloudwatch_metric twice (cpu, memory) but both
        # use the same kubectl top, so 2 calls × (1 cpu + 1 mem) = 4 points
        assert len(result.data) == 4
        assert result.metadata["metrics_queried"] == ["cpu_usage", "memory_usage"]

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_specific_metrics(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("pod-a   10m   50Mi\n")
        result = provider.get_metrics(namespace="default", metric_names=["cpu_usage"])
        assert result.status == ResultStatus.SUCCESS
        assert result.metadata["metrics_queried"] == ["cpu_usage"]

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_unknown_metric_ignored(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("pod-a   10m   50Mi\n")
        result = provider.get_metrics(namespace="default", metric_names=["nonexistent"])
        assert result.status == ResultStatus.SUCCESS
        assert result.data == []

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_mixed_known_unknown(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("pod-a   10m   50Mi\n")
        result = provider.get_metrics(namespace="default", metric_names=["cpu_usage", "bogus"])
        assert result.status == ResultStatus.SUCCESS
        assert len(result.data) > 0

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_exception_in_cloudwatch_returns_empty_success(self, mock_run, provider):
        """Exception in _get_cloudwatch_metric is caught → empty metrics → SUCCESS."""
        mock_run.side_effect = Exception("fatal")
        result = provider.get_metrics(namespace="default")
        assert result.status == ResultStatus.SUCCESS
        assert result.data == []

    @patch("src.aci.telemetry.metrics.subprocess.run")
    def test_metadata_fields(self, mock_run, provider):
        mock_run.return_value = _kubectl_ok("pod-a   10m   50Mi\n")
        result = provider.get_metrics(namespace="ns1", duration_minutes=10)
        assert result.metadata["namespace"] == "ns1"
        assert result.metadata["duration_minutes"] == 10
        assert "data_points" in result.metadata


# ---------------------------------------------------------------------------
# PREDEFINED_METRICS sanity
# ---------------------------------------------------------------------------

class TestPredefinedMetrics:
    def test_all_expected_keys(self):
        expected = {"cpu_usage", "memory_usage", "network_rx", "network_tx", "restarts"}
        assert expected.issubset(set(PREDEFINED_METRICS.keys()))

    def test_structure(self):
        for name, defn in PREDEFINED_METRICS.items():
            assert "cloudwatch" in defn
            assert "prometheus" in defn
            assert "namespace" in defn["cloudwatch"]
            assert "metric_name" in defn["cloudwatch"]
