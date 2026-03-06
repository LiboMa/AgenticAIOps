"""
Daily coverage boost tests for src/skills/kubernetes/tools.py (38% → targeting ~70%+).
Tests all 15 kubernetes tools with mocked KubectlExec.
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from dataclasses import dataclass


@dataclass
class FakeExecResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""


@pytest.fixture(autouse=True)
def set_agent_tier():
    """Set agent tier high enough for all tools."""
    from src.skills._security import set_agent_context
    from src.skills._models import SecurityTier
    set_agent_context("test-agent", SecurityTier.T3_DESTRUCTIVE)
    yield
    set_agent_context("unknown", SecurityTier.T0_READONLY)


@pytest.fixture(autouse=True)
def mock_kubectl():
    """Mock the module-level _kubectl instance."""
    with patch("src.skills.kubernetes.tools._kubectl") as mk:
        yield mk


def _parse(result_json):
    return json.loads(result_json)


def _assert_success(result_json):
    r = _parse(result_json)
    assert r["status"] == "success", f"Expected success but got {r}"
    return r


def _assert_error(result_json):
    r = _parse(result_json)
    assert r["status"] in ("error", "blocked"), f"Expected error/blocked but got {r}"
    return r


# ── T0 Read-Only ──

class TestK8sGetPods:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='{"items": []}')
        from src.skills.kubernetes.tools import k8s_get_pods
        _assert_success(k8s_get_pods(namespace="default", label_selector=""))

    def test_with_label_selector(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='{"items": [{"name": "nginx"}]}')
        from src.skills.kubernetes.tools import k8s_get_pods
        _assert_success(k8s_get_pods(namespace="kube-system", label_selector="app=nginx"))
        args = mock_kubectl.execute.call_args[0][0]
        assert "-l" in args
        assert "app=nginx" in args

    def test_failure(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=False, stderr="connection refused")
        from src.skills.kubernetes.tools import k8s_get_pods
        _assert_error(k8s_get_pods())


class TestK8sDescribeResource:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="Name: my-pod\nStatus: Running")
        from src.skills.kubernetes.tools import k8s_describe_resource
        _assert_success(k8s_describe_resource("pod", "my-pod", namespace="default"))

    def test_not_found(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=False, stderr="not found")
        from src.skills.kubernetes.tools import k8s_describe_resource
        _assert_error(k8s_describe_resource("deployment", "missing"))


class TestK8sGetLogs:
    def test_basic(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="log line 1\nlog line 2")
        from src.skills.kubernetes.tools import k8s_get_logs
        _assert_success(k8s_get_logs("my-pod", namespace="default"))

    def test_with_container(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="container log")
        from src.skills.kubernetes.tools import k8s_get_logs
        _assert_success(k8s_get_logs("my-pod", container="sidecar"))
        args = mock_kubectl.execute.call_args[0][0]
        assert "-c" in args
        assert "sidecar" in args

    def test_previous_container(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="previous log")
        from src.skills.kubernetes.tools import k8s_get_logs
        _assert_success(k8s_get_logs("my-pod", previous=True))
        args = mock_kubectl.execute.call_args[0][0]
        assert "--previous" in args

    def test_tail_lines_capped(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="log")
        from src.skills.kubernetes.tools import k8s_get_logs
        k8s_get_logs("my-pod", tail_lines=1000)
        args = mock_kubectl.execute.call_args[0][0]
        assert "--tail=500" in args

    def test_failure(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=False, stderr="pod not found")
        from src.skills.kubernetes.tools import k8s_get_logs
        _assert_error(k8s_get_logs("missing-pod"))


class TestK8sGetEvents:
    def test_basic(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='{"items": []}')
        from src.skills.kubernetes.tools import k8s_get_events
        _assert_success(k8s_get_events(namespace="default"))

    def test_with_field_selector(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='{"items": []}')
        from src.skills.kubernetes.tools import k8s_get_events
        _assert_success(k8s_get_events(field_selector="involvedObject.name=my-pod"))
        args = mock_kubectl.execute.call_args[0][0]
        assert "--field-selector" in args


class TestK8sGetNodes:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.side_effect = [
            FakeExecResult(ok=True, stdout="node1  Ready"),
            FakeExecResult(ok=True, stdout="node1  100m  20%"),
        ]
        from src.skills.kubernetes.tools import k8s_get_nodes
        r = _assert_success(k8s_get_nodes())
        assert "resource_usage" in r["data"]

    def test_top_unavailable(self, mock_kubectl):
        mock_kubectl.execute.side_effect = [
            FakeExecResult(ok=True, stdout="node1  Ready"),
            FakeExecResult(ok=False, stderr="metrics not available"),
        ]
        from src.skills.kubernetes.tools import k8s_get_nodes
        r = _assert_success(k8s_get_nodes())
        assert r["data"]["resource_usage"] == "unavailable"


class TestK8sGetDeployments:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='{"items": []}')
        from src.skills.kubernetes.tools import k8s_get_deployments
        _assert_success(k8s_get_deployments(namespace="default"))


class TestK8sGetServices:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='{"items": []}')
        from src.skills.kubernetes.tools import k8s_get_services
        _assert_success(k8s_get_services(namespace="default"))


class TestK8sClusterInfo:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.side_effect = [
            FakeExecResult(ok=True, stdout="Kubernetes control plane is running"),
            FakeExecResult(ok=True, stdout="etcd-0  Healthy"),
        ]
        from src.skills.kubernetes.tools import k8s_cluster_info
        _assert_success(k8s_cluster_info())

    def test_partial_failure(self, mock_kubectl):
        mock_kubectl.execute.side_effect = [
            FakeExecResult(ok=False, stderr="conn refused"),
            FakeExecResult(ok=False, stderr="unavailable"),
        ]
        from src.skills.kubernetes.tools import k8s_cluster_info
        _assert_success(k8s_cluster_info())


class TestK8sGetResource:
    def test_basic(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='{"items": []}')
        from src.skills.kubernetes.tools import k8s_get_resource
        _assert_success(k8s_get_resource("configmap", namespace="default"))

    def test_with_name_and_label(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='{"data": {}}')
        from src.skills.kubernetes.tools import k8s_get_resource
        _assert_success(k8s_get_resource("secret", name="my-secret", label_selector="env=prod"))
        args = mock_kubectl.execute.call_args[0][0]
        assert "my-secret" in args
        assert "-l" in args


class TestK8sTopPods:
    def test_sort_cpu(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="pod1 100m 50Mi")
        from src.skills.kubernetes.tools import k8s_top_pods
        _assert_success(k8s_top_pods(namespace="default", sort_by="cpu"))

    def test_sort_memory(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="pod1 100m 500Mi")
        from src.skills.kubernetes.tools import k8s_top_pods
        _assert_success(k8s_top_pods(sort_by="memory"))
        args = mock_kubectl.execute.call_args[0][0]
        assert "--sort-by=memory" in args


# ── T1 Low-Risk Write ──

class TestK8sScaleDeployment:
    def test_scale_up(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="deployment.apps/nginx scaled")
        from src.skills.kubernetes.tools import k8s_scale_deployment
        r = _assert_success(k8s_scale_deployment("nginx", replicas=3, namespace="default"))
        assert r["data"]["replicas"] == 3

    def test_scale_capped_at_50(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="scaled")
        from src.skills.kubernetes.tools import k8s_scale_deployment
        r = _assert_success(k8s_scale_deployment("nginx", replicas=100))
        assert r["data"]["replicas"] == 50

    def test_scale_min_zero(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="scaled")
        from src.skills.kubernetes.tools import k8s_scale_deployment
        r = _assert_success(k8s_scale_deployment("nginx", replicas=-5))
        assert r["data"]["replicas"] == 0

    def test_failure(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=False, stderr="not found")
        from src.skills.kubernetes.tools import k8s_scale_deployment
        _assert_error(k8s_scale_deployment("missing", replicas=2))


class TestK8sRolloutStatus:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="deployment successfully rolled out")
        from src.skills.kubernetes.tools import k8s_rollout_status
        _assert_success(k8s_rollout_status("nginx", namespace="default"))

    def test_timeout(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=False, stderr="timed out")
        from src.skills.kubernetes.tools import k8s_rollout_status
        _assert_error(k8s_rollout_status("slow-deploy"))


class TestK8sRolloutRestart:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="deployment.apps/nginx restarted")
        from src.skills.kubernetes.tools import k8s_rollout_restart
        r = _assert_success(k8s_rollout_restart("nginx"))
        assert r["data"]["action"] == "restart"


# ── T2 High-Risk ──

class TestK8sDeleteResource:
    def test_blocked_without_approval(self, mock_kubectl):
        """T2 tools require approval_token — should be blocked without it."""
        from src.skills.kubernetes.tools import k8s_delete_resource
        r = _parse(k8s_delete_resource("pod", "test", namespace="default"))
        assert r["status"] == "blocked"
        assert "approval_token" in r["error"]

    @patch("src.skills._security._check_approval")
    def test_delete_with_approval(self, mock_approval, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout='pod "test" deleted')
        from src.skills.kubernetes.tools import k8s_delete_resource
        _assert_success(k8s_delete_resource("pod", "test", namespace="default"))

    @patch("src.skills._security._check_approval")
    def test_dry_run(self, mock_approval, mock_kubectl):
        from src.skills.kubernetes.tools import k8s_delete_resource
        r = _parse(k8s_delete_resource("pod", "test", dry_run=True))
        assert r["status"] == "dry_run"


# ── T3 Destructive ──

class TestK8sDrainNode:
    def test_blocked_without_dual_approval(self, mock_kubectl):
        """T3 tools require dual approval_token — should be blocked without it."""
        from src.skills.kubernetes.tools import k8s_drain_node
        r = _parse(k8s_drain_node("node-1"))
        assert r["status"] == "blocked"
        assert "dual" in r["error"] or "approval_token" in r["error"]

    @patch("src.skills._security._check_approval")
    def test_drain_with_approval(self, mock_approval, mock_kubectl):
        mock_kubectl.execute.return_value = FakeExecResult(ok=True, stdout="node drained")
        from src.skills.kubernetes.tools import k8s_drain_node
        r = _assert_success(k8s_drain_node("node-1"))
        assert r["data"]["action"] == "drain"

    @patch("src.skills._security._check_approval")
    def test_dry_run(self, mock_approval, mock_kubectl):
        from src.skills.kubernetes.tools import k8s_drain_node
        r = _parse(k8s_drain_node("node-1", dry_run=True))
        assert r["status"] == "dry_run"

    def test_failure_without_approval(self, mock_kubectl):
        from src.skills.kubernetes.tools import k8s_drain_node
        _assert_error(k8s_drain_node("node-1"))
