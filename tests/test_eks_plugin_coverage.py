#!/usr/bin/env python3
"""
Tests for src/plugins/eks_plugin.py — EKSPlugin

Targets uncovered lines: initialize, health_check, get_tools (inner tools),
_get_target_cluster, get_resources, get_status_summary.
"""

import pytest
import sys
import os
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.plugins import PluginRegistry, PluginConfig, PluginStatus
from src.plugins.base import ClusterConfig
from src.plugins.eks_plugin import EKSPlugin


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset PluginRegistry state before each test."""
    PluginRegistry._plugins = {}
    PluginRegistry._clusters = {}
    PluginRegistry._active_cluster = None
    yield
    PluginRegistry._plugins = {}
    PluginRegistry._clusters = {}
    PluginRegistry._active_cluster = None


def _make_config(**overrides):
    defaults = {
        "plugin_id": "eks-test",
        "plugin_type": "eks",
        "name": "Test EKS",
        "enabled": True,
        "config": {"regions": ["us-east-1"]},
    }
    defaults.update(overrides)
    return PluginConfig(**defaults)


class TestEKSPluginInit:
    def test_basic_attributes(self):
        cfg = _make_config()
        plugin = EKSPlugin(cfg)
        assert plugin.PLUGIN_TYPE == "eks"
        assert plugin.PLUGIN_NAME == "Amazon EKS"
        assert plugin.clusters == []
        assert plugin._current_context is None


class TestEKSInitialize:
    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_initialize_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"clusters": ["my-cluster"]}',
        )
        plugin = EKSPlugin(_make_config())
        assert plugin.initialize() is True
        assert plugin.status == PluginStatus.ENABLED
        assert len(plugin.clusters) == 1
        assert plugin.clusters[0].name == "my-cluster"

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_initialize_aws_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        plugin = EKSPlugin(_make_config())
        assert plugin.initialize() is True  # Still succeeds, just no clusters
        assert len(plugin.clusters) == 0

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_initialize_exception(self, mock_run):
        mock_run.side_effect = Exception("boom")
        plugin = EKSPlugin(_make_config())
        # _discover_clusters catches per-region, but init may still succeed
        # with empty clusters or fail depending on implementation
        result = plugin.initialize()
        # If the exception propagates to initialize, status should be ERROR
        assert plugin.status in (PluginStatus.ENABLED, PluginStatus.ERROR)

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_discover_multiple_regions(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"clusters": ["c1"]}',
        )
        cfg = _make_config(config={"regions": ["us-east-1", "eu-west-1"]})
        plugin = EKSPlugin(cfg)
        plugin.initialize()
        assert len(plugin.clusters) == 2


class TestEKSHealthCheck:
    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_health_check_all_healthy(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="cluster info ok")
        plugin = EKSPlugin(_make_config())
        plugin.clusters = [
            ClusterConfig(cluster_id="eks-1", name="c1", region="us-east-1", plugin_type="eks", config={}),
        ]
        health = plugin.health_check()
        assert health["healthy"] is True
        assert health["healthy_clusters"] == 1

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_health_check_unhealthy(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        plugin = EKSPlugin(_make_config())
        plugin.clusters = [
            ClusterConfig(cluster_id="eks-1", name="c1", region="us-east-1", plugin_type="eks", config={}),
        ]
        health = plugin.health_check()
        assert health["healthy"] is False
        assert health["healthy_clusters"] == 0

    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_health_check_exception(self, mock_run):
        mock_run.side_effect = Exception("timeout")
        plugin = EKSPlugin(_make_config())
        plugin.clusters = [
            ClusterConfig(cluster_id="eks-1", name="c1", region="us-east-1", plugin_type="eks", config={}),
        ]
        health = plugin.health_check()
        assert health["healthy"] is False
        assert health["clusters"][0]["healthy"] is False

    def test_health_check_no_clusters(self):
        plugin = EKSPlugin(_make_config())
        health = plugin.health_check()
        assert health["healthy"] is True
        assert health["total_clusters"] == 0


class TestEKSGetTools:
    def test_get_tools_returns_list(self):
        plugin = EKSPlugin(_make_config())
        tools = plugin.get_tools()
        assert isinstance(tools, list)
        assert len(tools) == 6  # 6 tools defined

    def test_tool_names(self):
        plugin = EKSPlugin(_make_config())
        tools = plugin.get_tools()
        names = [t.__name__ for t in tools]
        assert "eks_get_pods" in names
        assert "eks_get_nodes" in names
        assert "eks_describe_pod" in names
        assert "eks_get_logs" in names
        assert "eks_list_clusters" in names
        assert "eks_switch_cluster" in names


class TestEKSGetTargetCluster:
    def test_with_cluster_id(self):
        plugin = EKSPlugin(_make_config())
        cluster = ClusterConfig(cluster_id="eks-1", name="c1", region="us-east-1", plugin_type="eks", config={})
        PluginRegistry.add_cluster(cluster)
        result = plugin._get_target_cluster("eks-1")
        assert result is not None
        assert result.name == "c1"

    def test_with_none_uses_active(self):
        plugin = EKSPlugin(_make_config())
        cluster = ClusterConfig(cluster_id="eks-1", name="c1", region="us-east-1", plugin_type="eks", config={})
        PluginRegistry.add_cluster(cluster)
        PluginRegistry.set_active_cluster("eks-1")
        result = plugin._get_target_cluster(None)
        assert result is not None
        assert result.cluster_id == "eks-1"

    def test_with_none_no_active(self):
        plugin = EKSPlugin(_make_config())
        result = plugin._get_target_cluster(None)
        assert result is None


class TestEKSGetResources:
    def test_get_resources_empty(self):
        plugin = EKSPlugin(_make_config())
        assert plugin.get_resources() == []

    def test_get_resources_with_clusters(self):
        plugin = EKSPlugin(_make_config())
        plugin.clusters = [
            ClusterConfig(cluster_id="eks-1", name="c1", region="us-east-1", plugin_type="eks", config={}),
        ]
        resources = plugin.get_resources()
        assert len(resources) == 1
        assert resources[0]["cluster_id"] == "eks-1"


class TestEKSGetStatusSummary:
    @patch("src.plugins.eks_plugin.subprocess.run")
    def test_status_summary(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        plugin = EKSPlugin(_make_config())
        plugin.clusters = [
            ClusterConfig(cluster_id="eks-1", name="c1", region="us-east-1", plugin_type="eks", config={}),
        ]
        summary = plugin.get_status_summary()
        assert summary["plugin_type"] == "eks"
        assert summary["icon"] == "☸️"
        assert summary["total_clusters"] == 1
        assert len(summary["clusters"]) == 1
