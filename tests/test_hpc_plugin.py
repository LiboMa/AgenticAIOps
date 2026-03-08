"""
HPC Plugin — Unit Tests
Covers: HPCPlugin init, health_check, get_tools, get_resources, get_status_summary, _discover_clusters
Target: raise src/plugins/hpc_plugin.py coverage from 22% → 70%+
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.plugins.base import PluginConfig, PluginStatus
from src.plugins.hpc_plugin import HPCPlugin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hpc_config():
    return PluginConfig(
        plugin_id="hpc-test",
        plugin_type="hpc",
        name="Test HPC",
        enabled=True,
        config={
            "regions": ["us-east-1"],
            "head_node_ssh": {
                "my-cluster": {"ip": "10.0.0.1", "user": "ec2-user", "key_file": "/tmp/key.pem"}
            },
        },
    )


@pytest.fixture
def plugin(hpc_config):
    """Create plugin WITHOUT calling initialize (skip real pcluster)."""
    return HPCPlugin(hpc_config)


def _pcluster_list_result(clusters):
    return MagicMock(
        returncode=0,
        stdout=json.dumps({"clusters": clusters}),
        stderr="",
    )


def _cf_fallback_result(stacks_json_lines):
    return MagicMock(
        returncode=0,
        stdout="\n".join(stacks_json_lines),
        stderr="",
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestHPCPluginInit:

    def test_default_regions(self):
        cfg = PluginConfig(plugin_id="x", plugin_type="hpc", name="X", config={})
        p = HPCPlugin(cfg)
        assert p.regions == ["ap-southeast-1"]

    def test_custom_regions(self, hpc_config):
        p = HPCPlugin(hpc_config)
        assert p.regions == ["us-east-1"]

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_initialize_success(self, mock_run, hpc_config):
        mock_run.return_value = _pcluster_list_result([
            {"clusterName": "c1", "clusterStatus": "CREATE_COMPLETE", "version": "3.8"}
        ])
        p = HPCPlugin(hpc_config)
        assert p.initialize() is True
        assert p.status == PluginStatus.ENABLED
        assert len(p.clusters) == 1

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_initialize_with_discovery_exception(self, mock_run, hpc_config):
        """_discover_clusters catches per-region exceptions, so initialize still succeeds with 0 clusters."""
        mock_run.side_effect = Exception("boom")
        p = HPCPlugin(hpc_config)
        # Exception inside _discover_clusters is per-region, not propagated
        assert p.initialize() is True
        assert p.status == PluginStatus.ENABLED
        assert len(p.clusters) == 0

    @patch.object(HPCPlugin, "_discover_clusters", side_effect=Exception("catastrophic"))
    def test_initialize_failure(self, mock_discover, hpc_config):
        """If _discover_clusters itself raises, initialize returns False."""
        p = HPCPlugin(hpc_config)
        assert p.initialize() is False
        assert p.status == PluginStatus.ERROR


# ---------------------------------------------------------------------------
# _discover_clusters
# ---------------------------------------------------------------------------

class TestDiscoverClusters:

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_pcluster_cli_path(self, mock_run, plugin):
        """Happy path: pcluster CLI returns clusters."""
        mock_run.return_value = _pcluster_list_result([
            {"clusterName": "alpha", "clusterStatus": "CREATE_COMPLETE", "version": "3.8"},
            {"clusterName": "beta", "clusterStatus": "DELETE_IN_PROGRESS", "version": "3.7"},
        ])

        plugin._discover_clusters()

        assert len(plugin.clusters) == 2
        assert plugin.clusters[0]["cluster_name"] == "alpha"
        assert plugin.clusters[1]["status"] == "DELETE_IN_PROGRESS"

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_cloudformation_fallback(self, mock_run, plugin):
        """When pcluster CLI fails, falls back to CloudFormation."""
        fail = MagicMock(returncode=1, stdout="", stderr="not found")
        cf_json = json.dumps({"StackName": "hpc-stack", "StackStatus": "CREATE_COMPLETE"})
        success = _cf_fallback_result([cf_json])

        mock_run.side_effect = [fail, success]

        plugin._discover_clusters()

        assert len(plugin.clusters) == 1
        assert plugin.clusters[0]["cluster_name"] == "hpc-stack"
        assert plugin.clusters[0]["version"] == "unknown"

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_cloudformation_fallback_empty(self, mock_run, plugin):
        """Fallback with empty CF output means no clusters."""
        fail = MagicMock(returncode=1, stdout="", stderr="err")
        cf_empty = MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = [fail, cf_empty]

        plugin._discover_clusters()

        assert len(plugin.clusters) == 0

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_cloudformation_fallback_bad_json(self, mock_run, plugin):
        """Malformed CF JSON lines are skipped silently."""
        fail = MagicMock(returncode=1, stdout="", stderr="err")
        bad = MagicMock(returncode=0, stdout="not-json\n{bad", stderr="")

        mock_run.side_effect = [fail, bad]

        plugin._discover_clusters()

        assert len(plugin.clusters) == 0

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_discover_exception_per_region(self, mock_run, plugin):
        """Exception during discovery for one region is caught."""
        mock_run.side_effect = Exception("timeout")

        plugin._discover_clusters()

        assert plugin.clusters == []

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_multi_region(self, mock_run):
        """Discovery across multiple regions."""
        cfg = PluginConfig(
            plugin_id="mr", plugin_type="hpc", name="MR",
            config={"regions": ["us-east-1", "eu-west-1"]},
        )
        p = HPCPlugin(cfg)

        r1 = _pcluster_list_result([{"clusterName": "c1", "clusterStatus": "CREATE_COMPLETE", "version": "3.8"}])
        r2 = _pcluster_list_result([{"clusterName": "c2", "clusterStatus": "CREATE_COMPLETE", "version": "3.9"}])
        mock_run.side_effect = [r1, r2]

        p._discover_clusters()

        assert len(p.clusters) == 2
        assert {c["region"] for c in p.clusters} == {"us-east-1", "eu-west-1"}


# ---------------------------------------------------------------------------
# health_check / get_resources / get_status_summary
# ---------------------------------------------------------------------------

class TestHPCPluginMethods:

    def test_health_check_empty(self, plugin):
        h = plugin.health_check()
        assert h["healthy"] is True
        assert h["total_clusters"] == 0
        assert h["active_clusters"] == 0

    def test_health_check_with_clusters(self, plugin):
        plugin.clusters = [
            {"cluster_name": "c1", "status": "CREATE_COMPLETE", "region": "us-east-1", "version": "3.8"},
            {"cluster_name": "c2", "status": "DELETE_IN_PROGRESS", "region": "us-east-1", "version": "3.7"},
            {"cluster_name": "c3", "status": "UPDATE_COMPLETE", "region": "us-east-1", "version": "3.8"},
        ]
        h = plugin.health_check()
        assert h["total_clusters"] == 3
        assert h["active_clusters"] == 2  # CREATE_COMPLETE + UPDATE_COMPLETE

    def test_get_resources(self, plugin):
        plugin.clusters = [{"x": 1}]
        assert plugin.get_resources() == [{"x": 1}]

    def test_get_status_summary(self, plugin):
        plugin.clusters = [
            {"cluster_name": "c1", "status": "CREATE_COMPLETE", "region": "us-east-1", "version": "3.8"},
        ]
        s = plugin.get_status_summary()
        assert s["plugin_type"] == "hpc"
        assert s["icon"] == "🖧"
        assert s["total_clusters"] == 1
        assert s["active_clusters"] == 1


# ---------------------------------------------------------------------------
# get_tools (tool functions)
# ---------------------------------------------------------------------------

class TestHPCPluginTools:

    def test_tools_returned(self, plugin):
        tools = plugin.get_tools()
        names = [t.__name__ for t in tools]
        assert "hpc_list_clusters" in names
        assert "hpc_get_cluster_info" in names
        assert "hpc_get_queue_status" in names
        assert "hpc_get_node_status" in names
        assert "hpc_get_job_history" in names

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_list_clusters_tool(self, mock_run, plugin):
        """The hpc_list_clusters tool refreshes and returns formatted text."""
        mock_run.return_value = _pcluster_list_result([
            {"clusterName": "demo", "clusterStatus": "CREATE_COMPLETE", "version": "3.8"},
        ])
        tools = plugin.get_tools()
        list_fn = next(t for t in tools if t.__name__ == "hpc_list_clusters")

        result = list_fn(region=None)

        assert "demo" in result
        assert "CREATE_COMPLETE" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_list_clusters_empty(self, mock_run, plugin):
        mock_run.return_value = _pcluster_list_result([])
        tools = plugin.get_tools()
        list_fn = next(t for t in tools if t.__name__ == "hpc_list_clusters")

        result = list_fn()

        assert "No HPC clusters found" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_cluster_info_pcluster(self, mock_run, plugin):
        """Cluster info via pcluster describe-cluster."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "clusterStatus": "CREATE_COMPLETE",
                "version": "3.8",
                "region": "us-east-1",
                "scheduler": {"type": "slurm"},
                "computeFleetStatus": "RUNNING",
                "headNode": {
                    "instanceType": "m5.xlarge",
                    "state": "running",
                    "publicIpAddress": "1.2.3.4",
                },
            }),
            stderr="",
        )
        tools = plugin.get_tools()
        info_fn = next(t for t in tools if t.__name__ == "hpc_get_cluster_info")

        result = info_fn(cluster_name="demo", region="us-east-1")

        assert "CREATE_COMPLETE" in result
        assert "slurm" in result.lower()
        assert "1.2.3.4" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_cluster_info_cf_fallback(self, mock_run, plugin):
        """Cluster info falls back to CloudFormation."""
        pcluster_fail = MagicMock(returncode=1, stdout="", stderr="err")
        cf_success = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "Stacks": [{
                    "StackStatus": "CREATE_COMPLETE",
                    "CreationTime": "2026-02-20T00:00:00Z",
                    "Outputs": [
                        {"OutputKey": "HeadNodeIP", "OutputValue": "10.0.0.1"},
                    ],
                }]
            }),
            stderr="",
        )
        mock_run.side_effect = [pcluster_fail, cf_success]

        tools = plugin.get_tools()
        info_fn = next(t for t in tools if t.__name__ == "hpc_get_cluster_info")

        result = info_fn(cluster_name="demo", region="us-east-1")

        assert "CloudFormation" in result
        assert "HeadNodeIP" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_cluster_info_both_fail(self, mock_run, plugin):
        """Both pcluster and CF fail."""
        fail = MagicMock(returncode=1, stdout="", stderr="err")
        mock_run.side_effect = [fail, fail]

        tools = plugin.get_tools()
        info_fn = next(t for t in tools if t.__name__ == "hpc_get_cluster_info")

        result = info_fn(cluster_name="demo")

        assert "Error" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_cluster_info_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("network error")

        tools = plugin.get_tools()
        info_fn = next(t for t in tools if t.__name__ == "hpc_get_cluster_info")

        result = info_fn(cluster_name="demo")

        assert "Error" in result
        assert "network error" in result

    def test_hpc_get_queue_status_no_ip(self, plugin):
        """No IP configured returns error message."""
        tools = plugin.get_tools()
        queue_fn = next(t for t in tools if t.__name__ == "hpc_get_queue_status")

        result = queue_fn(cluster_name="unknown-cluster")

        assert "Error" in result
        assert "not configured" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_queue_status_success(self, mock_run, plugin):
        mock_run.return_value = MagicMock(returncode=0, stdout="JOBID  NAME  STATUS\n123 test RUNNING", stderr="")

        tools = plugin.get_tools()
        queue_fn = next(t for t in tools if t.__name__ == "hpc_get_queue_status")

        result = queue_fn(cluster_name="my-cluster")

        assert "Slurm Queue Status" in result
        assert "RUNNING" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_queue_status_ssh_fail(self, mock_run, plugin):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Connection refused")

        tools = plugin.get_tools()
        queue_fn = next(t for t in tools if t.__name__ == "hpc_get_queue_status")

        result = queue_fn(cluster_name="my-cluster")

        assert "Error connecting" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_queue_status_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("ssh timeout")

        tools = plugin.get_tools()
        queue_fn = next(t for t in tools if t.__name__ == "hpc_get_queue_status")

        result = queue_fn(cluster_name="my-cluster")

        assert "Error" in result

    def test_hpc_get_node_status_no_ip(self, plugin):
        tools = plugin.get_tools()
        node_fn = next(t for t in tools if t.__name__ == "hpc_get_node_status")

        result = node_fn(cluster_name="unknown-cluster")

        assert "Error" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_node_status_success(self, mock_run, plugin):
        mock_run.return_value = MagicMock(returncode=0, stdout="NODE STATUS\nnode1 idle", stderr="")

        tools = plugin.get_tools()
        node_fn = next(t for t in tools if t.__name__ == "hpc_get_node_status")

        result = node_fn(cluster_name="my-cluster")

        assert "Slurm Node Status" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_node_status_ssh_fail(self, mock_run, plugin):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="refused")

        tools = plugin.get_tools()
        node_fn = next(t for t in tools if t.__name__ == "hpc_get_node_status")

        result = node_fn(cluster_name="my-cluster")

        assert "Error" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_node_status_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("boom")

        tools = plugin.get_tools()
        node_fn = next(t for t in tools if t.__name__ == "hpc_get_node_status")

        result = node_fn(cluster_name="my-cluster")

        assert "Error" in result

    def test_hpc_get_job_history_no_ip(self, plugin):
        tools = plugin.get_tools()
        hist_fn = next(t for t in tools if t.__name__ == "hpc_get_job_history")

        result = hist_fn(cluster_name="unknown-cluster")

        assert "Error" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_job_history_success(self, mock_run, plugin):
        mock_run.return_value = MagicMock(returncode=0, stdout="JobID JobName State\n123 test COMPLETED", stderr="")

        tools = plugin.get_tools()
        hist_fn = next(t for t in tools if t.__name__ == "hpc_get_job_history")

        result = hist_fn(cluster_name="my-cluster", days=2)

        assert "Job History" in result
        assert "2 day(s)" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_job_history_fail(self, mock_run, plugin):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="sacct err")

        tools = plugin.get_tools()
        hist_fn = next(t for t in tools if t.__name__ == "hpc_get_job_history")

        result = hist_fn(cluster_name="my-cluster")

        assert "Error" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_hpc_get_job_history_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("oops")

        tools = plugin.get_tools()
        hist_fn = next(t for t in tools if t.__name__ == "hpc_get_job_history")

        result = hist_fn(cluster_name="my-cluster")

        assert "Error" in result

    @patch("src.plugins.hpc_plugin.subprocess.run")
    def test_tool_with_head_node_ip_arg(self, mock_run, plugin):
        """Passing head_node_ip explicitly overrides SSH config."""
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        tools = plugin.get_tools()
        queue_fn = next(t for t in tools if t.__name__ == "hpc_get_queue_status")

        result = queue_fn(cluster_name="no-ssh-config", head_node_ip="192.168.1.1")

        assert "ok" in result
        cmd_str = mock_run.call_args[1].get("shell") or str(mock_run.call_args)
        # Should have used the IP we passed
