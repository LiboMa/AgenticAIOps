"""Tests for src/skills/kubernetes/security.py — 0% coverage target ~90%."""

import pytest
from src.skills.kubernetes.security import (
    check,
    ALLOWED_READ_OPS,
    ALLOWED_WRITE_OPS,
    DANGEROUS_OPS,
    PROTECTED_NAMESPACES,
)


class TestCheckReadOps:
    @pytest.mark.parametrize("op", list(ALLOWED_READ_OPS))
    def test_read_ops_allowed(self, op):
        ok, msg = check("k8s_run", {"command": f"kubectl {op} pods"})
        assert ok
        assert "Read" in msg

    def test_read_op_via_args(self):
        ok, msg = check("k8s_run", {"args": ["get", "pods"]})
        assert ok


class TestCheckWriteOps:
    @pytest.mark.parametrize("op", list(ALLOWED_WRITE_OPS))
    def test_write_ops_allowed(self, op):
        ok, msg = check("k8s_run", {"command": f"kubectl {op} deployment/nginx"})
        assert ok


class TestCheckDangerousOps:
    @pytest.mark.parametrize("op", list(DANGEROUS_OPS))
    def test_dangerous_ops_allowed_with_gate(self, op):
        ok, msg = check("k8s_run", {"command": f"kubectl {op} pod/test"})
        assert ok
        assert "Dangerous" in msg or "approval" in msg.lower()


class TestProtectedNamespaces:
    @pytest.mark.parametrize("ns", list(PROTECTED_NAMESPACES))
    def test_write_blocked_in_protected_ns(self, ns):
        ok, msg = check("k8s_run", {"command": "kubectl apply -f x.yaml", "namespace": ns})
        assert not ok
        assert "protected" in msg.lower()

    @pytest.mark.parametrize("ns", list(PROTECTED_NAMESPACES))
    def test_read_allowed_in_protected_ns(self, ns):
        ok, msg = check("k8s_run", {"command": "kubectl get pods", "namespace": ns})
        assert ok

    def test_protected_ns_from_args_flag(self):
        ok, msg = check("k8s_run", {"command": "kubectl apply -n kube-system -f x.yaml"})
        assert not ok


class TestEdgeCases:
    def test_empty_command(self):
        ok, msg = check("k8s_run", {"command": "kubectl"})
        assert not ok
        assert "Empty" in msg

    def test_unknown_op(self):
        ok, msg = check("k8s_run", {"command": "kubectl foobar"})
        assert not ok
        assert "Unknown" in msg

    def test_no_command_no_args(self):
        ok, msg = check("k8s_run", {})
        assert ok

    def test_command_without_kubectl_prefix(self):
        ok, msg = check("k8s_run", {"command": "get pods"})
        assert ok
