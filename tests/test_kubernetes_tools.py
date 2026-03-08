"""Tests for src/skills/kubernetes/tools.py."""

import json
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def mock_kubectl():
    with patch("src.skills.kubernetes.tools._kubectl") as m:
        yield m


class TestK8sGetPods:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.return_value = MagicMock(ok=True, stdout='{"items":[]}', stderr="")
        from src.skills.kubernetes.tools import k8s_get_pods
        result = json.loads(k8s_get_pods.__wrapped__(namespace="default"))
        assert result["status"] == "success"

    def test_failure(self, mock_kubectl):
        mock_kubectl.execute.return_value = MagicMock(ok=False, stdout="", stderr="not found")
        from src.skills.kubernetes.tools import k8s_get_pods
        result = json.loads(k8s_get_pods.__wrapped__(namespace="default"))
        assert result["status"] == "error"

    def test_with_label_selector(self, mock_kubectl):
        mock_kubectl.execute.return_value = MagicMock(ok=True, stdout='{}', stderr="")
        from src.skills.kubernetes.tools import k8s_get_pods
        k8s_get_pods.__wrapped__(namespace="default", label_selector="app=nginx")
        args = mock_kubectl.execute.call_args[0][0]
        assert "-l" in args
        assert "app=nginx" in args


class TestK8sDescribeResource:
    def test_success(self, mock_kubectl):
        mock_kubectl.execute.return_value = MagicMock(ok=True, stdout="Name: nginx\n", stderr="")
        from src.skills.kubernetes.tools import k8s_describe_resource
        result = json.loads(k8s_describe_resource.__wrapped__(resource_type="pod", name="nginx"))
        assert result["status"] == "success"

    def test_failure(self, mock_kubectl):
        mock_kubectl.execute.return_value = MagicMock(ok=False, stdout="", stderr="not found")
        from src.skills.kubernetes.tools import k8s_describe_resource
        result = json.loads(k8s_describe_resource.__wrapped__(resource_type="pod", name="missing"))
        assert result["status"] == "error"
