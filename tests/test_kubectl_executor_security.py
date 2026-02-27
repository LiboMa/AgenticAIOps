"""
Tests for KubectlExecutor security gate (P0 fix).

Verifies that SecurityFilter.check_kubectl() is enforced at the execute() entry
point, blocking dangerous commands unless an approval_token is provided.
"""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src.aci.operations.kubectl import KubectlExecutor
from src.aci.models import ResultStatus


@pytest.fixture
def executor():
    return KubectlExecutor(cluster_name="test-cluster", region="us-east-1")


class TestSecurityGateBlocking:
    """Dangerous commands must be blocked without approval_token."""

    def test_delete_namespace_kube_system_blocked(self, executor):
        result = executor.execute(["delete", "namespace", "kube-system"])
        assert result.status == ResultStatus.ERROR
        assert "Security check failed" in result.error or "not allowed" in result.error

    def test_delete_all_all_namespaces_blocked(self, executor):
        result = executor.execute(["delete", "--all", "--all-namespaces"])
        assert result.status == ResultStatus.ERROR

    def test_delete_nodes_blocked(self, executor):
        result = executor.execute(["delete", "nodes"])
        assert result.status == ResultStatus.ERROR

    def test_delete_clusterrole_blocked(self, executor):
        result = executor.execute(["delete", "clusterrole", "admin"])
        assert result.status == ResultStatus.ERROR

    def test_delete_pods_all_flag_blocked(self, executor):
        """Local is_safe_operation also blocks delete --all."""
        result = executor.execute(["delete", "pods", "--all"], namespace="default")
        assert result.status == ResultStatus.ERROR

    def test_dangerous_op_drain_blocked(self, executor):
        """Dangerous operations (drain) blocked by local check."""
        result = executor.execute(["drain", "node-1"])
        assert result.status == ResultStatus.ERROR

    def test_dangerous_op_cordon_blocked(self, executor):
        result = executor.execute(["cordon", "node-1"])
        assert result.status == ResultStatus.ERROR


class TestSecurityGateApproval:
    """Dangerous commands pass with a valid approval_token."""

    @patch("subprocess.run")
    def test_delete_with_approval_token_proceeds(self, mock_run, executor):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"deleted": true}', stderr=""
        )
        result = executor.execute(
            ["delete", "pod", "my-pod"],
            namespace="staging",
            approval_token="tok-abc123xyz",
        )
        # Should NOT be blocked — it's a single pod delete (not in DANGEROUS_KUBECTL)
        # and approval_token overrides local check
        assert result.status == ResultStatus.SUCCESS
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_dangerous_kubectl_with_approval_passes(self, mock_run, executor):
        """Even SecurityFilter-flagged commands pass with approval_token."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="node drained", stderr=""
        )
        result = executor.execute(
            ["drain", "node-1", "--ignore-daemonsets"],
            approval_token="tok-emergency-001",
        )
        assert result.status == ResultStatus.SUCCESS


class TestSafeCommandsUnaffected:
    """Read and normal write operations should still work fine."""

    @patch("subprocess.run")
    def test_get_pods_passes(self, mock_run, executor):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"items": []}', stderr=""
        )
        result = executor.execute(["get", "pods"], namespace="default")
        assert result.status == ResultStatus.SUCCESS

    @patch("subprocess.run")
    def test_describe_node_passes(self, mock_run, executor):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Name: node-1", stderr=""
        )
        result = executor.execute(["describe", "node", "node-1"])
        assert result.status == ResultStatus.SUCCESS

    @patch("subprocess.run")
    def test_scale_deployment_passes(self, mock_run, executor):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="scaled", stderr=""
        )
        result = executor.execute(
            ["scale", "deployment/web", "--replicas=3"], namespace="app"
        )
        assert result.status == ResultStatus.SUCCESS

    @patch("subprocess.run")
    def test_write_to_protected_ns_blocked(self, mock_run, executor):
        """Write op to kube-system blocked without approval."""
        result = executor.execute(
            ["scale", "deployment/coredns", "--replicas=1"],
            namespace="kube-system",
        )
        assert result.status == ResultStatus.ERROR
        assert "protected namespace" in result.error.lower() or "not allowed" in result.error.lower()
        mock_run.assert_not_called()


class TestNoSubprocessOnBlock:
    """Verify subprocess.run is never called when a command is blocked."""

    @patch("subprocess.run")
    def test_subprocess_not_called_for_blocked_cmd(self, mock_run, executor):
        executor.execute(["delete", "namespace", "kube-system"])
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_subprocess_not_called_for_dangerous_op(self, mock_run, executor):
        executor.execute(["drain", "node-1"])
        mock_run.assert_not_called()
