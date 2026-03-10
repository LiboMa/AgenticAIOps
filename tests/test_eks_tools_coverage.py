#!/usr/bin/env python3
"""
Tests for EKSPlugin inner tool functions (eks_get_pods, eks_get_nodes,
eks_describe_pod, eks_get_logs, eks_list_clusters, eks_switch_cluster).

Covers previously-uncovered lines 36-39, 115-126, 138-148, 162-172,
187-197, 206-217, 229-232 in src/plugins/eks_plugin.py.
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.plugins import PluginRegistry, PluginConfig, PluginStatus
from src.plugins.base import ClusterConfig
from src.plugins.eks_plugin import EKSPlugin


@pytest.fixture(autouse=True)
def reset_registry():
    PluginRegistry._plugins = {}
    PluginRegistry._clusters = {}
    PluginRegistry._active_cluster = None
    yield
    PluginRegistry._plugins = {}
    PluginRegistry._clusters = {}
    PluginRegistry._active_cluster = None


def _make_plugin_with_cluster():
    """Create an EKSPlugin with one cluster registered and active."""
    cfg = PluginConfig(
        plugin_id="eks-test",
        plugin_type="eks",
        name="Test EKS",
        enabled=True,
        config={"regions": ["us-east-1"]},
    )
    plugin = EKSPlugin(cfg)
    cluster = ClusterConfig(
        cluster_id="eks-us-east-1-test",
        name="test-cluster",
        region="us-east-1",
        plugin_type="eks",
        config={"cluster_name": "test-cluster"},
    )
    plugin.clusters = [cluster]
    PluginRegistry.add_cluster(cluster)
    PluginRegistry.set_active_cluster("eks-us-east-1-test")
    return plugin


def _get_tool(plugin, name):
    tools = plugin.get_tools()
    for t in tools:
        if t.__name__ == name:
            return t
    raise ValueError(f"Tool {name} not found")


# ---------- _discover_clusters edge cases ----------

class TestDiscoverClusters:
    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_discover_clusters_subprocess_timeout(self, mock_run):
        """Cover the per-region exception branch in _discover_clusters."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="aws", timeout=30)
        cfg = PluginConfig(
            plugin_id="eks-test", plugin_type="eks", name="Test",
            enabled=True, config={"regions": ["us-east-1"]},
        )
        plugin = EKSPlugin(cfg)
        plugin._discover_clusters()
        assert len(plugin.clusters) == 0

    def test_initialize_error_branch(self):
        """Cover lines 36-39: initialize() except branch."""
        cfg = PluginConfig(
            plugin_id="eks-test", plugin_type="eks", name="Test",
            enabled=True, config={"regions": ["us-east-1"]},
        )
        plugin = EKSPlugin(cfg)
        # Make _discover_clusters raise to trigger initialize's except
        with patch.object(plugin, "_discover_clusters", side_effect=RuntimeError("fatal")):
            result = plugin.initialize()
        assert result is False
        assert plugin.status == PluginStatus.ERROR


import subprocess


# ---------- eks_get_pods ----------

class TestEksGetPods:
    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_pods_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="NAME  READY  STATUS\npod1  1/1  Running\n")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_pods")
        result = fn(namespace="default")
        assert "pod1" in result

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_pods_all_namespaces(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="pods across all ns")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_pods")
        result = fn(namespace="all")
        assert "pods across all ns" in result
        # Verify -A flag was used
        call_cmd = mock_run.call_args[0][0]
        assert "-A" in call_cmd

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_pods_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="connection refused")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_pods")
        result = fn(namespace="default")
        assert "Error" in result

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_pods_exception(self, mock_run):
        mock_run.side_effect = Exception("network error")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_pods")
        result = fn(namespace="default")
        assert "Error" in result

    def test_get_pods_no_cluster(self):
        cfg = PluginConfig(
            plugin_id="eks-test", plugin_type="eks", name="Test",
            enabled=True, config={"regions": ["us-east-1"]},
        )
        plugin = EKSPlugin(cfg)
        fn = _get_tool(plugin, "eks_get_pods")
        result = fn(namespace="default")
        assert "No cluster" in result


# ---------- eks_get_nodes ----------

class TestEksGetNodes:
    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_nodes_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="NAME  STATUS\nnode1  Ready\n")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_nodes")
        result = fn()
        assert "node1" in result

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_nodes_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="unauthorized")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_nodes")
        result = fn()
        assert "Error" in result

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_nodes_exception(self, mock_run):
        mock_run.side_effect = Exception("timeout")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_nodes")
        result = fn()
        assert "Error" in result

    def test_get_nodes_no_cluster(self):
        cfg = PluginConfig(
            plugin_id="eks-test", plugin_type="eks", name="Test",
            enabled=True, config={"regions": ["us-east-1"]},
        )
        plugin = EKSPlugin(cfg)
        fn = _get_tool(plugin, "eks_get_nodes")
        result = fn()
        assert "No cluster" in result


# ---------- eks_describe_pod ----------

class TestEksDescribePod:
    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_describe_pod_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Name: my-pod\nStatus: Running")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_describe_pod")
        result = fn(pod_name="my-pod", namespace="kube-system")
        assert "my-pod" in result

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_describe_pod_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_describe_pod")
        result = fn(pod_name="missing-pod")
        assert "Error" in result

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_describe_pod_exception(self, mock_run):
        mock_run.side_effect = Exception("fail")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_describe_pod")
        result = fn(pod_name="pod1")
        assert "Error" in result

    def test_describe_pod_no_cluster(self):
        cfg = PluginConfig(
            plugin_id="eks-test", plugin_type="eks", name="Test",
            enabled=True, config={"regions": ["us-east-1"]},
        )
        plugin = EKSPlugin(cfg)
        fn = _get_tool(plugin, "eks_describe_pod")
        result = fn(pod_name="pod1")
        assert "No cluster" in result


# ---------- eks_get_logs ----------

class TestEksGetLogs:
    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_logs_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="log line 1\nlog line 2\n")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_logs")
        result = fn(pod_name="my-pod", tail=50)
        assert "log line" in result

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_logs_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="container not found")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_logs")
        result = fn(pod_name="bad-pod")
        assert "Error" in result

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_get_logs_exception(self, mock_run):
        mock_run.side_effect = Exception("timeout")
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_get_logs")
        result = fn(pod_name="pod1")
        assert "Error" in result

    def test_get_logs_no_cluster(self):
        cfg = PluginConfig(
            plugin_id="eks-test", plugin_type="eks", name="Test",
            enabled=True, config={"regions": ["us-east-1"]},
        )
        plugin = EKSPlugin(cfg)
        fn = _get_tool(plugin, "eks_get_logs")
        result = fn(pod_name="pod1")
        assert "No cluster" in result


# ---------- eks_list_clusters ----------

class TestEksListClusters:
    def test_list_clusters_empty(self):
        cfg = PluginConfig(
            plugin_id="eks-test", plugin_type="eks", name="Test",
            enabled=True, config={"regions": ["us-east-1"]},
        )
        plugin = EKSPlugin(cfg)
        fn = _get_tool(plugin, "eks_list_clusters")
        result = fn()
        assert "No EKS clusters" in result

    def test_list_clusters_with_active(self):
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_list_clusters")
        result = fn()
        assert "test-cluster" in result
        assert "ACTIVE" in result

    def test_list_clusters_no_active(self):
        plugin = _make_plugin_with_cluster()
        PluginRegistry._active_cluster = None
        fn = _get_tool(plugin, "eks_list_clusters")
        result = fn()
        assert "test-cluster" in result
        assert "ACTIVE" not in result


# ---------- eks_switch_cluster ----------

class TestEksSwitchCluster:
    def test_switch_success(self):
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_switch_cluster")
        result = fn(cluster_id="eks-us-east-1-test")
        assert "Switched to cluster" in result
        assert "test-cluster" in result

    def test_switch_not_found(self):
        plugin = _make_plugin_with_cluster()
        fn = _get_tool(plugin, "eks_switch_cluster")
        result = fn(cluster_id="nonexistent")
        assert "Error" in result
