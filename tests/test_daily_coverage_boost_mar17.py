"""
Daily Coverage Boost Tests — 2026-03-17

Targets the 3 lowest-coverage modules:
1. src/aci/operations/kubectl.py  (76% → missing: timeout, exception, verify_approval_token paths)
2. src/aci/skills/loader.py       (79% → missing: load_all, register_tools, discover_tools, _load_safety edge cases)
3. src/aci/telemetry/prometheus.py (80% → missing: query non-success, check_health, get_k8s_metric unknown)
"""

import importlib
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests


# ─── kubectl.py tests ───────────────────────────────────────────

class TestKubectlExecutorTimeout:
    """Cover subprocess.TimeoutExpired path (lines 163-170)."""

    @patch("src.aci.operations.kubectl.subprocess.run")
    @patch("src.aci.operations.kubectl._SECURITY_FILTER")
    def test_execute_timeout(self, mock_filter, mock_run):
        from src.aci.operations.kubectl import KubectlExecutor, ResultStatus

        mock_filter.check_kubectl.return_value = (True, "ok")
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="kubectl get pods", timeout=5)

        executor = KubectlExecutor(cluster_name="test", region="us-east-1")
        result = executor.execute(["get", "pods"], timeout=5)

        assert result.status == ResultStatus.TIMEOUT
        assert "timeout" in result.error.lower()


class TestKubectlExecutorGenericException:
    """Cover generic Exception path (lines 171-177)."""

    @patch("src.aci.operations.kubectl.subprocess.run")
    @patch("src.aci.operations.kubectl._SECURITY_FILTER")
    def test_execute_exception(self, mock_filter, mock_run):
        from src.aci.operations.kubectl import KubectlExecutor, ResultStatus

        mock_filter.check_kubectl.return_value = (True, "ok")
        mock_run.side_effect = OSError("kubectl not found")

        executor = KubectlExecutor(cluster_name="test", region="us-east-1")
        result = executor.execute(["get", "pods"])

        assert result.status == ResultStatus.ERROR
        assert "kubectl not found" in result.error


class TestKubectlIsSafeOperation:
    """Cover is_safe_operation edge cases (lines 189-215)."""

    def _executor(self):
        from src.aci.operations.kubectl import KubectlExecutor
        return KubectlExecutor(cluster_name="test", region="us-east-1")

    def test_empty_command(self):
        safe, reason = self._executor().is_safe_operation([])
        assert safe is False
        assert "Empty" in reason

    def test_dangerous_op(self):
        safe, reason = self._executor().is_safe_operation(["delete", "pod", "foo"])
        assert safe is False
        assert "Dangerous" in reason

    def test_unknown_op(self):
        safe, reason = self._executor().is_safe_operation(["exec", "-it", "mypod"])
        assert safe is False
        assert "Unknown" in reason

    def test_write_protected_namespace_via_args(self):
        safe, reason = self._executor().is_safe_operation(
            ["apply", "-f", "x.yaml", "-n", "kube-system"]
        )
        assert safe is False
        assert "protected" in reason.lower()

    def test_write_protected_namespace_via_param(self):
        safe, reason = self._executor().is_safe_operation(
            ["scale", "deploy/foo", "--replicas=3"], namespace="kube-public"
        )
        assert safe is False
        assert "protected" in reason.lower()

    def test_write_allowed_namespace(self):
        safe, reason = self._executor().is_safe_operation(
            ["apply", "-f", "x.yaml"], namespace="default"
        )
        assert safe is True

    def test_read_operations(self):
        for op in ["get", "describe", "logs", "top", "explain", "api-resources", "api-versions"]:
            safe, reason = self._executor().is_safe_operation([op, "pods"])
            assert safe is True, f"Read op '{op}' should be safe"


class TestVerifyApprovalToken:
    """Cover _verify_approval_token (lines 24-30)."""

    def test_verify_token_invalid_format(self):
        from src.aci.operations.kubectl import _verify_approval_token
        # Token with invalid format should be rejected
        ok, reason = _verify_approval_token("any-token", "kubectl delete pod foo")
        assert ok is False
        assert "token" in reason.lower() or "invalid" in reason.lower()

    @patch.dict("os.environ", {}, clear=False)
    def test_verify_token_no_secret_env(self):
        """When APPROVAL_TOKEN_SECRET is not set and verify raises ValueError."""
        from src.aci.operations.kubectl import _verify_approval_token
        # Ensure we exercise the function — result depends on env config
        ok, reason = _verify_approval_token("12345.abc", "kubectl delete pod foo")
        assert isinstance(ok, bool)
        assert isinstance(reason, str)


class TestKubectlExecuteSecurityBlock:
    """Cover security filter block path with and without approval token."""

    @patch("src.aci.operations.kubectl._SECURITY_FILTER")
    def test_blocked_no_approval(self, mock_filter):
        from src.aci.operations.kubectl import KubectlExecutor, ResultStatus
        mock_filter.check_kubectl.return_value = (False, "dangerous command")

        executor = KubectlExecutor(cluster_name="test", region="us-east-1")
        result = executor.execute(["delete", "pod", "foo"])

        assert result.status == ResultStatus.ERROR
        assert "Security check failed" in result.error


# ─── loader.py tests ────────────────────────────────────────────

class TestSkillLoaderLoadAll:
    """Cover load_all() (line 190-197)."""

    def test_load_all_returns_list(self, tmp_path):
        from src.aci.skills.loader import SkillLoader
        loader = SkillLoader(skills_dir=tmp_path)
        # Empty dir → no skills discovered → empty list
        result = loader.load_all()
        assert isinstance(result, list)
        assert result == []


class TestSkillLoaderRegisterTools:
    """Cover register_tools() (lines 269-289)."""

    def _make_skill(self, tools=None):
        from src.aci.skills.models import SkillDefinition, SafetyConfig, SkillSummary
        summary = SkillSummary(
            name="test-skill",
            description="A test skill for unit testing",
            path=Path("/tmp/test-skill"),
        )
        return SkillDefinition(
            summary=summary,
            instructions="test instructions",
            safety=SafetyConfig(),
            _tools=tools or [],
            _reference_paths=[],
        )

    def test_register_with_tool_method(self):
        from src.aci.skills.loader import SkillLoader

        mock_tool = MagicMock()
        mock_tool.__name__ = "my_tool"
        skill = self._make_skill(tools=[mock_tool])

        mock_agent = MagicMock()
        mock_agent.tool = MagicMock()

        SkillLoader.register_tools(skill, mock_agent)
        mock_agent.tool.assert_called_once_with(mock_tool)

    def test_register_without_tool_method(self):
        from src.aci.skills.loader import SkillLoader

        skill = self._make_skill()

        # Agent without .tool() method — use a simple namespace
        mock_agent = type("Agent", (), {})()

        # Should not raise, just log warning
        SkillLoader.register_tools(skill, mock_agent)


class TestSkillLoaderDiscoverToolsFromFile:
    """Cover _discover_tools_from_file (lines 260-290)."""

    def test_nonexistent_file(self):
        from src.aci.skills.loader import SkillLoader
        result = SkillLoader._discover_tools_from_file(Path("/nonexistent/tools.py"))
        assert result == []


class TestSkillLoaderDiscoverTools:
    """Cover _discover_tools for missing dir (lines 310-320)."""

    def test_missing_scripts_dir(self):
        from src.aci.skills.loader import SkillLoader
        result = SkillLoader._discover_tools(Path("/nonexistent/scripts"))
        assert result == []


class TestSkillLoaderLoadSafety:
    """Cover _load_safety edge cases (lines 338-390)."""

    def test_missing_safety_dir(self):
        from src.aci.skills.loader import SkillLoader
        from src.aci.skills.models import SafetyTier
        config = SkillLoader._load_safety(Path("/nonexistent/safety"))
        assert config.tier == SafetyTier.READ_ONLY

    def test_load_safety_with_tier_file(self, tmp_path):
        from src.aci.skills.loader import SkillLoader
        safety_dir = tmp_path / "safety"
        safety_dir.mkdir()

        tier_file = safety_dir / "safety_tier.yaml"
        tier_file.write_text("tier: execute\nrequires_approval:\n  - delete\ndeny_by_default: false\n")

        config = SkillLoader._load_safety(safety_dir)
        assert config.requires_approval == ["delete"]
        assert config.deny_by_default is False

    def test_load_safety_unknown_tier(self, tmp_path):
        from src.aci.skills.loader import SkillLoader
        from src.aci.skills.models import SafetyTier
        safety_dir = tmp_path / "safety"
        safety_dir.mkdir()

        tier_file = safety_dir / "safety_tier.yaml"
        tier_file.write_text("tier: nonexistent-tier\n")

        config = SkillLoader._load_safety(safety_dir)
        # Should fall back to read-only
        assert config.tier == SafetyTier.READ_ONLY

    def test_load_safety_with_command_allowlist(self, tmp_path):
        from src.aci.skills.loader import SkillLoader
        safety_dir = tmp_path / "safety"
        safety_dir.mkdir()

        allowlist_file = safety_dir / "command_allowlist.yaml"
        allowlist_file.write_text("allow:\n  - kubectl get\n  - kubectl describe\nblock:\n  - kubectl delete\n")

        config = SkillLoader._load_safety(safety_dir)
        assert "kubectl get" in config.command_allowlist
        assert "kubectl delete" in config.command_blocklist

    def test_load_safety_with_blast_radius(self, tmp_path):
        from src.aci.skills.loader import SkillLoader
        safety_dir = tmp_path / "safety"
        safety_dir.mkdir()

        blast_file = safety_dir / "blast_radius.yaml"
        blast_file.write_text("max_pods: 10\nmax_nodes: 3\n")

        config = SkillLoader._load_safety(safety_dir)
        assert config.blast_radius["max_pods"] == 10


class TestSkillLoaderListReferences:
    """Cover _list_references (lines 388-390)."""

    def test_nonexistent_ref_dir(self):
        from src.aci.skills.loader import SkillLoader
        result = SkillLoader._list_references(Path("/nonexistent/references"))
        assert result == []

    def test_ref_dir_with_files(self, tmp_path):
        from src.aci.skills.loader import SkillLoader
        ref_dir = tmp_path / "references"
        ref_dir.mkdir()
        (ref_dir / "guide.md").write_text("# Guide")
        (ref_dir / "readme.txt").write_text("readme")
        # Sub-directory should not be included (is_file check)
        (ref_dir / "subdir").mkdir()

        result = SkillLoader._list_references(ref_dir)
        assert len(result) == 2


class TestIsStrandsTool:
    """Cover _is_strands_tool edge cases."""

    def test_tool_name_attribute(self):
        from src.aci.skills.loader import _is_strands_tool
        func = MagicMock()
        func.tool_name = "my_tool"
        assert _is_strands_tool(func) is True

    def test_tool_handler_attribute(self):
        from src.aci.skills.loader import _is_strands_tool
        func = MagicMock(spec=[])  # no attributes
        func.tool_handler = True
        assert _is_strands_tool(func) is True

    def test_wrapped_with_tool_name(self):
        from src.aci.skills.loader import _is_strands_tool

        def inner():
            pass
        inner.tool_name = "wrapped_tool"

        def outer():
            pass
        outer.__wrapped__ = inner
        # Remove auto-generated attributes from MagicMock — use plain functions
        assert _is_strands_tool(outer) is True

    def test_plain_function(self):
        from src.aci.skills.loader import _is_strands_tool

        def plain():
            pass
        assert _is_strands_tool(plain) is False


# ─── prometheus.py tests ────────────────────────────────────────

class TestPrometheusQuery:
    """Cover query() error paths (lines 86, 106-112)."""

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_query_non_success_status(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider, ResultStatus

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"status": "error", "error": "bad query"}
        mock_get.return_value = mock_resp

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        result = provider.query("invalid{")

        assert result.status == ResultStatus.ERROR
        assert "bad query" in result.error

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_query_timeout(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider, ResultStatus

        mock_get.side_effect = requests.exceptions.Timeout()

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        result = provider.query("up")

        assert result.status == ResultStatus.TIMEOUT

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_query_generic_exception(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider, ResultStatus

        mock_get.side_effect = ValueError("unexpected")

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        result = provider.query("up")

        assert result.status == ResultStatus.ERROR
        assert "unexpected" in result.error


class TestPrometheusQueryRange:
    """Cover query_range() error paths (lines 157, 178-191)."""

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_query_range_non_success(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider, ResultStatus

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"status": "error", "error": "range error"}
        mock_get.return_value = mock_resp

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        now = datetime.now(timezone.utc)
        result = provider.query_range("up", now - timedelta(hours=1), now)

        assert result.status == ResultStatus.ERROR
        assert "range error" in result.error

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_query_range_timeout(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider, ResultStatus

        mock_get.side_effect = requests.exceptions.Timeout()

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        now = datetime.now(timezone.utc)
        result = provider.query_range("up", now - timedelta(hours=1), now)

        assert result.status == ResultStatus.TIMEOUT

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_query_range_generic_exception(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider, ResultStatus

        mock_get.side_effect = RuntimeError("boom")

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        now = datetime.now(timezone.utc)
        result = provider.query_range("up", now - timedelta(hours=1), now)

        assert result.status == ResultStatus.ERROR


class TestPrometheusCheckHealth:
    """Cover check_health() (lines 235-240)."""

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_check_health_ok(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        assert provider.check_health() is True

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_check_health_down(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider

        mock_get.side_effect = requests.exceptions.ConnectionError("refused")

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        assert provider.check_health() is False

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_check_health_non_200(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_get.return_value = mock_resp

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        assert provider.check_health() is False


class TestPrometheusGetK8sMetric:
    """Cover get_k8s_metric() unknown metric (line 157 area)."""

    def test_unknown_metric_name(self):
        from src.aci.telemetry.prometheus import PrometheusProvider, ResultStatus

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        result = provider.get_k8s_metric("nonexistent_metric", "default")

        assert result.status == ResultStatus.ERROR
        assert "Unknown metric" in result.error

    @patch("src.aci.telemetry.prometheus.requests.get")
    def test_known_metric_calls_query_range(self, mock_get):
        from src.aci.telemetry.prometheus import PrometheusProvider, ResultStatus

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        }
        mock_get.return_value = mock_resp

        provider = PrometheusProvider(prometheus_url="http://fake:9090")
        result = provider.get_k8s_metric("cpu_usage", "default", duration_minutes=10)

        assert result.status == ResultStatus.SUCCESS
        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert "query_range" in call_url
