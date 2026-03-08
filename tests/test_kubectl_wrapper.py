"""
Tests for src/kubectl_wrapper.py — kubectl subprocess wrapper

Coverage target: 60%+ (from 0%)
"""

import json
import pytest
from unittest.mock import patch, MagicMock
import subprocess

# Clear module cache between test runs
import src.kubectl_wrapper as kw


class TestKubectlRun:
    """Test raw kubectl command execution."""

    def test_success(self):
        mock_result = MagicMock(returncode=0, stdout="pod/nginx\n", stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.kubectl_run(['get', 'pods'])
        assert result == "pod/nginx\n"

    def test_failure(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="error: not found")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.kubectl_run(['get', 'nonexistent'])
        assert result is None

    def test_timeout(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='kubectl', timeout=10)):
            result = kw.kubectl_run(['get', 'pods'], timeout=10)
        assert result is None

    def test_exception(self):
        with patch('subprocess.run', side_effect=OSError("kubectl not found")):
            result = kw.kubectl_run(['get', 'pods'])
        assert result is None


class TestKubectlJson:
    """Test JSON output kubectl commands."""

    def test_valid_json(self):
        mock_result = MagicMock(returncode=0, stdout='{"items": []}', stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.kubectl_json(['get', 'pods'])
        assert result == {"items": []}

    def test_invalid_json(self):
        mock_result = MagicMock(returncode=0, stdout="not json", stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.kubectl_json(['get', 'pods'])
        assert result is None

    def test_command_failure(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.kubectl_json(['get', 'pods'])
        assert result is None


class TestGetCached:
    """Test caching mechanism."""

    def test_cache_miss_calls_fetch(self):
        kw._cache.clear()
        calls = []
        def fetch():
            calls.append(1)
            return {"data": "fresh"}
        result = kw._get_cached("test-key", fetch)
        assert result == {"data": "fresh"}
        assert len(calls) == 1

    def test_cache_hit_skips_fetch(self):
        kw._cache.clear()
        import time
        kw._cache["cached-key"] = {"data": "cached", "time": time.time()}
        calls = []
        def fetch():
            calls.append(1)
            return {"data": "fresh"}
        result = kw._get_cached("cached-key", fetch)
        assert result == "cached"
        assert len(calls) == 0

    def test_cache_expired(self):
        kw._cache.clear()
        import time
        kw._cache["old-key"] = {"data": "stale", "time": time.time() - 100}
        result = kw._get_cached("old-key", lambda: "fresh", ttl=30)
        assert result == "fresh"


class TestGetPods:
    """Test pod listing."""

    def test_get_pods_all(self):
        kw._cache.clear()
        pod_data = {"items": [{
            "metadata": {"name": "nginx-abc", "namespace": "default"},
            "status": {
                "phase": "Running",
                "containerStatuses": [{"ready": True, "restartCount": 0, "state": {}}],
            },
        }]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(pod_data), stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_pods()
        assert len(result["pods"]) == 1
        assert result["pods"][0]["name"] == "nginx-abc"

    def test_get_pods_namespace(self):
        kw._cache.clear()
        mock_result = MagicMock(returncode=0, stdout='{"items": []}', stderr="")
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            result = kw.get_pods(namespace="kube-system")
        assert result == {"pods": []}
        call_args = mock_run.call_args[0][0]
        assert '-n' in call_args
        assert 'kube-system' in call_args

    def test_get_pods_empty(self):
        kw._cache.clear()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_pods()
        assert result == {"pods": []}

    def test_get_pods_oom_status(self):
        kw._cache.clear()
        pod_data = {"items": [{
            "metadata": {"name": "oom-pod", "namespace": "default"},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "ready": False, "restartCount": 5,
                    "state": {},
                    "lastState": {"terminated": {"reason": "OOMKilled"}},
                }],
            },
        }]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(pod_data), stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_pods()
        assert result["pods"][0]["status"] == "OOMKilled"

    def test_get_pods_waiting_status(self):
        kw._cache.clear()
        pod_data = {"items": [{
            "metadata": {"name": "wait-pod", "namespace": "default"},
            "status": {
                "phase": "Pending",
                "containerStatuses": [{
                    "ready": False, "restartCount": 3,
                    "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                }],
            },
        }]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(pod_data), stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_pods()
        assert result["pods"][0]["status"] == "CrashLoopBackOff"

    def test_get_pods_no_container_statuses(self):
        """Pod with empty containerStatuses list."""
        kw._cache.clear()
        pod_data = {"items": [{
            "metadata": {"name": "init-pod", "namespace": "default"},
            "status": {"phase": "Pending", "containerStatuses": []},
        }]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(pod_data), stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_pods()
        assert result["pods"][0]["status"] == "Pending"
        assert result["pods"][0]["restarts"] == 0
        assert result["pods"][0]["ready"] == "0/0"


class TestGetNodes:
    """Test node listing."""

    def test_get_nodes_ready(self):
        kw._cache.clear()
        node_data = {"items": [{
            "metadata": {"name": "ip-10-0-1-100"},
            "status": {
                "conditions": [
                    {"type": "Ready", "status": "True"},
                    {"type": "MemoryPressure", "status": "False"},
                ],
                "nodeInfo": {"kubeletVersion": "v1.28.5"},
            },
        }]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(node_data), stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_nodes()
        assert len(result["nodes"]) == 1
        node = result["nodes"][0]
        assert node["name"] == "ip-10-0-1-100"
        assert node["status"] == "Ready"
        assert node["version"] == "v1.28.5"

    def test_get_nodes_not_ready(self):
        kw._cache.clear()
        node_data = {"items": [{
            "metadata": {"name": "bad-node"},
            "status": {
                "conditions": [{"type": "Ready", "status": "False"}],
                "nodeInfo": {"kubeletVersion": "v1.28.5"},
            },
        }]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(node_data), stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_nodes()
        assert result["nodes"][0]["status"] == "NotReady"

    def test_get_nodes_no_ready_condition(self):
        """Node without a Ready condition at all."""
        kw._cache.clear()
        node_data = {"items": [{
            "metadata": {"name": "weird-node"},
            "status": {
                "conditions": [{"type": "DiskPressure", "status": "True"}],
                "nodeInfo": {"kubeletVersion": "v1.28.0"},
            },
        }]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(node_data), stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_nodes()
        assert result["nodes"][0]["status"] == "NotReady"

    def test_get_nodes_empty(self):
        kw._cache.clear()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_nodes()
        assert result == {"nodes": []}


class TestGetDeployments:
    """Test deployment listing."""

    def test_get_deployments_all(self):
        kw._cache.clear()
        deploy_data = {"items": [{
            "metadata": {"name": "nginx-deploy", "namespace": "default"},
            "status": {"replicas": 3, "readyReplicas": 3, "availableReplicas": 3},
        }]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(deploy_data), stderr="")
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            result = kw.get_deployments()
        assert len(result["deployments"]) == 1
        d = result["deployments"][0]
        assert d["name"] == "nginx-deploy"
        assert d["replicas"] == 3
        assert d["ready"] == 3
        call_args = mock_run.call_args[0][0]
        assert '-A' in call_args

    def test_get_deployments_namespace(self):
        kw._cache.clear()
        mock_result = MagicMock(returncode=0, stdout='{"items": []}', stderr="")
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            result = kw.get_deployments(namespace="prod")
        assert result == {"deployments": []}
        call_args = mock_run.call_args[0][0]
        assert '-n' in call_args
        assert 'prod' in call_args

    def test_get_deployments_empty(self):
        kw._cache.clear()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_deployments()
        assert result == {"deployments": []}


class TestGetEvents:
    """Test event listing."""

    def test_get_events_all(self):
        kw._cache.clear()
        event_data = {"items": [
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "metadata": {"namespace": "default"},
                "involvedObject": {"name": "crash-pod"},
                "count": 5,
            },
            {
                "type": "Normal",
                "reason": "Pulled",
                "message": "Successfully pulled image",
                "metadata": {"namespace": "default"},
                "involvedObject": {"name": "nginx-pod"},
                "count": 1,
            },
        ]}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(event_data), stderr="")
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            result = kw.get_events()
        assert len(result["events"]) == 2
        # Reversed order
        assert result["events"][0]["reason"] == "Pulled"
        assert result["events"][1]["reason"] == "BackOff"
        call_args = mock_run.call_args[0][0]
        assert '-A' in call_args

    def test_get_events_namespace(self):
        kw._cache.clear()
        mock_result = MagicMock(returncode=0, stdout='{"items": []}', stderr="")
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            result = kw.get_events(namespace="kube-system")
        assert result == {"events": []}
        call_args = mock_run.call_args[0][0]
        assert '-n' in call_args
        assert 'kube-system' in call_args

    def test_get_events_empty(self):
        kw._cache.clear()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_events()
        assert result == {"events": []}

    def test_get_events_limit(self):
        """Only last N events are returned."""
        kw._cache.clear()
        items = [
            {
                "type": "Normal", "reason": f"Event{i}", "message": f"msg{i}",
                "metadata": {"namespace": "default"},
                "involvedObject": {"name": f"pod-{i}"}, "count": 1,
            }
            for i in range(5)
        ]
        event_data = {"items": items}
        mock_result = MagicMock(returncode=0, stdout=json.dumps(event_data), stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_events(limit=3)
        assert len(result["events"]) == 3


class TestGetPodLogs:
    """Test pod log retrieval."""

    def test_get_pod_logs_success(self):
        log_output = "2026-02-26 INFO  Starting...\n2026-02-26 INFO  Ready"
        mock_result = MagicMock(returncode=0, stdout=log_output, stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_pod_logs("default", "nginx-abc")
        assert "Starting" in result["logs"]

    def test_get_pod_logs_failure(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="error: pod not found")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.get_pod_logs("default", "nonexistent")
        assert result["logs"] == "No logs available"


class TestDescribePod:
    """Test pod describe."""

    def test_describe_pod_success(self):
        desc = "Name: nginx\nNamespace: default\nStatus: Running"
        mock_result = MagicMock(returncode=0, stdout=desc, stderr="")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.describe_pod("default", "nginx")
        assert "Running" in result["description"]

    def test_describe_pod_not_found(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="not found")
        with patch('subprocess.run', return_value=mock_result):
            result = kw.describe_pod("default", "gone")
        assert result["description"] == "Pod not found"


class TestGetClusterInfo:
    """Test cluster info retrieval."""

    def test_cluster_info_success(self):
        kw._cache.clear()

        def mock_run(args, **kwargs):
            cmd = args[1] if len(args) > 1 else ""
            if cmd == 'version':
                return MagicMock(returncode=0, stdout="Client Version: v1.28.5\nServer Version: v1.28.3\n", stderr="")
            elif cmd == 'config':
                return MagicMock(returncode=0, stdout="arn:aws:eks:ap-southeast-1:123:cluster/aiops\n", stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch('subprocess.run', side_effect=mock_run):
            result = kw.get_cluster_info()
        assert result["version"] == "v1.28.3"
        assert "aiops" in result["name"]
        assert result["status"] == "ACTIVE"

    def test_cluster_info_no_version(self):
        kw._cache.clear()

        def mock_run(args, **kwargs):
            return MagicMock(returncode=1, stdout="", stderr="error")

        with patch('subprocess.run', side_effect=mock_run):
            result = kw.get_cluster_info()
        assert result["version"] == "unknown"
        assert result["name"] == "unknown"

    def test_cluster_info_version_no_server_line(self):
        """Version output without a Server line."""
        kw._cache.clear()

        def mock_run(args, **kwargs):
            cmd = args[1] if len(args) > 1 else ""
            if cmd == 'version':
                return MagicMock(returncode=0, stdout="Client Version: v1.28.5\n", stderr="")
            elif cmd == 'config':
                return MagicMock(returncode=0, stdout="my-cluster\n", stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch('subprocess.run', side_effect=mock_run):
            result = kw.get_cluster_info()
        assert result["version"] == "unknown"
        assert result["name"] == "my-cluster"


class TestGetClusterHealth:
    """Test cluster health summary."""

    def test_healthy_cluster(self):
        kw._cache.clear()
        with patch.object(kw, 'get_nodes', return_value={
            "nodes": [{"status": "Ready"}, {"status": "Ready"}]
        }), patch.object(kw, 'get_pods', return_value={
            "pods": [
                {"status": "Running"}, {"status": "Running"},
                {"status": "Running"}, {"status": "Running"},
                {"status": "Running"},
            ]
        }):
            result = kw.get_cluster_health()
        assert result["status"] == "healthy"
        assert result["nodes"]["ready"] == 2
        assert result["pods"]["running"] == 5

    def test_critical_cluster_node_down(self):
        kw._cache.clear()
        with patch.object(kw, 'get_nodes', return_value={
            "nodes": [{"status": "Ready"}, {"status": "NotReady"}]
        }), patch.object(kw, 'get_pods', return_value={
            "pods": [{"status": "Running"}, {"status": "CrashLoopBackOff"}]
        }):
            result = kw.get_cluster_health()
        assert result["status"] == "critical"

    def test_critical_cluster_low_pods(self):
        """Less than 50% pods running → critical."""
        kw._cache.clear()
        with patch.object(kw, 'get_nodes', return_value={
            "nodes": [{"status": "Ready"}]
        }), patch.object(kw, 'get_pods', return_value={
            "pods": [
                {"status": "Running"},
                {"status": "CrashLoopBackOff"},
                {"status": "CrashLoopBackOff"},
                {"status": "CrashLoopBackOff"},
            ]
        }):
            result = kw.get_cluster_health()
        assert result["status"] == "critical"

    def test_degraded_cluster(self):
        """All nodes ready but 50-80% pods running → degraded."""
        kw._cache.clear()
        with patch.object(kw, 'get_nodes', return_value={
            "nodes": [{"status": "Ready"}]
        }), patch.object(kw, 'get_pods', return_value={
            "pods": [
                {"status": "Running"}, {"status": "Running"},
                {"status": "Running"},
                {"status": "CrashLoopBackOff"}, {"status": "Pending"},
            ]
        }):
            result = kw.get_cluster_health()
        assert result["status"] == "degraded"

    def test_empty_cluster(self):
        """No nodes or pods → healthy (0 == 0)."""
        kw._cache.clear()
        with patch.object(kw, 'get_nodes', return_value={"nodes": []}), \
             patch.object(kw, 'get_pods', return_value={"pods": []}):
            result = kw.get_cluster_health()
        assert result["status"] == "healthy"
        assert result["nodes"]["total"] == 0
        assert result["pods"]["total"] == 0
