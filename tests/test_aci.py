"""
ACI Unit Tests
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.aci import AgentCloudInterface
from src.aci.models import ResultStatus, LogEntry, EventEntry
from src.aci.security.filters import SecurityFilter


class TestSecurityFilter:
    """Test security filter functionality."""
    
    def setup_method(self):
        self.filter = SecurityFilter()
    
    def test_block_rm_rf(self):
        """Should block rm -rf /"""
        is_safe, reason = self.filter.check_shell("rm -rf /")
        assert not is_safe
        assert "dangerous" in reason.lower()
    
    def test_block_rm_rf_star(self):
        """Should block rm -rf /*"""
        is_safe, reason = self.filter.check_shell("rm -rf /*")
        assert not is_safe
    
    def test_allow_ls(self):
        """Should allow ls command"""
        is_safe, reason = self.filter.check_shell("ls -la /tmp")
        assert is_safe
    
    def test_allow_cat(self):
        """Should allow cat command"""
        is_safe, reason = self.filter.check_shell("cat /etc/hosts")
        assert is_safe
    
    def test_block_etc_passwd_write(self):
        """Should block write to /etc/passwd"""
        is_safe, reason = self.filter.check_shell("echo 'test' >> /etc/passwd")
        assert not is_safe
    
    def test_allow_etc_passwd_read(self):
        """Should allow read from /etc/passwd"""
        is_safe, reason = self.filter.check_shell("cat /etc/passwd")
        assert is_safe
    
    def test_kubectl_allow_get(self):
        """Should allow kubectl get"""
        is_safe, reason = self.filter.check_kubectl(["get", "pods"])
        assert is_safe
    
    def test_kubectl_block_delete_namespace_kubesystem(self):
        """Should block delete kube-system namespace"""
        is_safe, reason = self.filter.check_kubectl(["delete", "namespace", "kube-system"])
        assert not is_safe
    
    def test_kubectl_block_delete_all(self):
        """Should block kubectl delete --all"""
        is_safe, reason = self.filter.check_kubectl(["delete", "pods", "--all"])
        assert not is_safe


class TestLogEntry:
    """Test LogEntry model."""
    
    def test_to_dict(self):
        """Test LogEntry serialization."""
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            namespace="default",
            pod="nginx-abc123",
            container="nginx",
            message="Connection established",
            level="info",
        )
        
        result = entry.to_dict()
        
        assert result["namespace"] == "default"
        assert result["pod"] == "nginx-abc123"
        assert result["level"] == "info"


class TestEventEntry:
    """Test EventEntry model."""
    
    def test_to_dict(self):
        """Test EventEntry serialization."""
        entry = EventEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            namespace="default",
            event_type="Warning",
            reason="BackOff",
            message="Back-off restarting failed container",
            involved_object="nginx-abc123",
            involved_kind="Pod",
            count=5,
        )
        
        result = entry.to_dict()
        
        assert result["event_type"] == "Warning"
        assert result["reason"] == "BackOff"
        assert result["count"] == 5


class TestAgentCloudInterface:
    """Test ACI main interface."""
    
    def setup_method(self):
        self.aci = AgentCloudInterface(
            cluster_name="test-cluster",
            region="us-east-1",
            enable_audit=False,
        )
    
    @patch('src.aci.telemetry.logs.subprocess.run')
    def test_get_logs_empty(self, mock_run):
        """Test get_logs with no matching pods."""
        # Mock kubectl get pods returning empty
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        
        result = self.aci.get_logs(namespace="default", pod_name="nonexistent")
        
        assert result.status == ResultStatus.SUCCESS
        assert len(result.data) == 0
    
    def test_kubectl_safe_command(self):
        """Test kubectl with safe command doesn't get blocked."""
        # This tests that safe commands pass security check
        with patch('src.aci.operations.kubectl.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"items": []}',
                stderr="",
            )
            
            result = self.aci.kubectl(["get", "pods"])
            
            assert result.status == ResultStatus.SUCCESS
    
    def test_exec_shell_blocked(self):
        """Test exec_shell blocks dangerous commands."""
        result = self.aci.exec_shell("rm -rf /")
        
        assert result.status == ResultStatus.ERROR
        assert "Security blocked" in result.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
