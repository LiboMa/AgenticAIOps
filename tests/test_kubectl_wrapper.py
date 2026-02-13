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
