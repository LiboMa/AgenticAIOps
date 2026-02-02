"""
Tests for Health Check Module
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import time

from src.health import (
    HealthCheckResult, CheckType, CheckStatus,
    HealthChecker, HealthCheckScheduler
)
from src.health.models import CheckItem, HealthCheckConfig


class TestHealthCheckModels:
    """Tests for health check data models."""
    
    def test_check_type_enum(self):
        """Test check type enum values."""
        assert CheckType.PODS.value == "pods"
        assert CheckType.NODES.value == "nodes"
        assert CheckType.FULL.value == "full"
    
    def test_check_status_enum(self):
        """Test check status enum values."""
        assert CheckStatus.HEALTHY.value == "healthy"
        assert CheckStatus.WARNING.value == "warning"
        assert CheckStatus.CRITICAL.value == "critical"
    
    def test_check_item_creation(self):
        """Test CheckItem creation."""
        item = CheckItem(
            name="test-pod",
            namespace="default",
            status=CheckStatus.HEALTHY,
            message="Pod running normally"
        )
        
        assert item.name == "test-pod"
        assert item.namespace == "default"
        assert item.status == CheckStatus.HEALTHY
    
    def test_health_check_result_counts(self):
        """Test HealthCheckResult status counts."""
        items = [
            CheckItem("pod1", "ns", CheckStatus.HEALTHY, "ok"),
            CheckItem("pod2", "ns", CheckStatus.HEALTHY, "ok"),
            CheckItem("pod3", "ns", CheckStatus.WARNING, "warning"),
            CheckItem("pod4", "ns", CheckStatus.CRITICAL, "critical"),
        ]
        
        result = HealthCheckResult(
            check_type=CheckType.PODS,
            status=CheckStatus.CRITICAL,
            items=items,
        )
        
        assert result.healthy_count == 2
        assert result.warning_count == 1
        assert result.critical_count == 1
    
    def test_health_check_result_to_dict(self):
        """Test HealthCheckResult serialization."""
        items = [
            CheckItem("pod1", "default", CheckStatus.HEALTHY, "ok"),
        ]
        
        result = HealthCheckResult(
            check_type=CheckType.PODS,
            status=CheckStatus.HEALTHY,
            items=items,
            issues_created=0,
        )
        
        data = result.to_dict()
        
        assert data["check_type"] == "pods"
        assert data["status"] == "healthy"
        assert data["summary"]["total"] == 1
        assert data["summary"]["healthy"] == 1
    
    def test_health_check_config_defaults(self):
        """Test HealthCheckConfig defaults."""
        config = HealthCheckConfig()
        
        assert config.enabled is True
        assert config.interval_seconds == 60
        assert CheckType.PODS in config.check_types


class TestHealthChecker:
    """Tests for HealthChecker."""
    
    @pytest.fixture
    def mock_aci(self):
        """Create mock ACI."""
        aci = Mock()
        
        # Mock successful pod response
        aci.get_pods.return_value = Mock(
            status=Mock(value="success"),
            data=[
                {
                    "name": "healthy-pod",
                    "namespace": "default",
                    "phase": "Running",
                    "ready": True,
                    "restart_count": 0,
                    "status": "Running",
                },
                {
                    "name": "unhealthy-pod",
                    "namespace": "default",
                    "phase": "Failed",
                    "ready": False,
                    "restart_count": 10,
                    "status": "CrashLoopBackOff",
                },
            ]
        )
        
        # Mock node response
        aci.get_nodes.return_value = Mock(
            status=Mock(value="success"),
            data=[
                {
                    "name": "node-1",
                    "status": "Ready",
                    "conditions": {"Ready": True, "MemoryPressure": False, "DiskPressure": False},
                },
            ]
        )
        
        # Mock events response
        aci.get_events.return_value = Mock(
            status=Mock(value="success"),
            data=[
                {
                    "reason": "OOMKilled",
                    "message": "Container killed due to OOM",
                    "involvedObject": {"name": "test-pod", "namespace": "default"},
                },
            ]
        )
        
        # Mock metrics response
        aci.get_metrics.return_value = Mock(
            status=Mock(value="success"),
            data={
                "cpu_usage_percent": 45,
                "memory_usage_percent": 60,
            }
        )
        
        return aci
    
    @pytest.fixture
    def checker(self, mock_aci):
        """Create checker with mock ACI."""
        return HealthChecker(aci=mock_aci)
    
    def test_check_pods_healthy_and_unhealthy(self, checker):
        """Test pod health checking."""
        result = checker.check_pods(namespaces=["default"])
        
        assert result.check_type == CheckType.PODS
        assert len(result.items) == 2
        assert result.healthy_count == 1
        assert result.critical_count == 1
    
    def test_check_pods_determines_status(self, checker):
        """Test overall status determination."""
        result = checker.check_pods()
        
        # Should be CRITICAL because one pod is in CrashLoopBackOff
        assert result.status == CheckStatus.CRITICAL
    
    def test_check_nodes_healthy(self, checker):
        """Test node health checking."""
        result = checker.check_nodes()
        
        assert result.check_type == CheckType.NODES
        assert len(result.items) == 1
        assert result.items[0].status == CheckStatus.HEALTHY
    
    def test_check_events_finds_warnings(self, checker):
        """Test event checking."""
        result = checker.check_events()
        
        assert result.check_type == CheckType.EVENTS
        assert len(result.items) == 1
        assert result.items[0].status == CheckStatus.CRITICAL  # OOMKilled is critical
    
    def test_check_resources_healthy(self, checker):
        """Test resource checking with healthy metrics."""
        result = checker.check_resources()
        
        assert result.check_type == CheckType.RESOURCES
        assert result.status == CheckStatus.HEALTHY  # 45% CPU, 60% memory
    
    def test_run_full_check(self, checker):
        """Test full health check."""
        # Configure checker for pods and events only
        checker.config.check_types = [CheckType.PODS, CheckType.EVENTS]
        
        result = checker.run_full_check()
        
        assert result.check_type == CheckType.FULL
        assert len(result.items) >= 2  # At least pods + events
    
    def test_check_without_aci(self):
        """Test checker without ACI returns unknown status."""
        checker = HealthChecker(aci=None)
        checker._aci = None  # Ensure it stays None
        
        result = checker.check_pods()
        
        assert result.status == CheckStatus.UNKNOWN
    
    def test_pod_status_mapping(self, checker):
        """Test pod status to check status mapping."""
        # Test healthy pod
        pod = {
            "name": "test",
            "namespace": "default",
            "phase": "Running",
            "ready": True,
            "restart_count": 0,
            "status": "Running",
        }
        item = checker._check_pod(pod)
        assert item.status == CheckStatus.HEALTHY
        
        # Test high restart count
        pod["restart_count"] = 10
        item = checker._check_pod(pod)
        assert item.status == CheckStatus.WARNING
        
        # Test pending pod
        pod["phase"] = "Pending"
        pod["restart_count"] = 0
        item = checker._check_pod(pod)
        assert item.status == CheckStatus.WARNING
        
        # Test failed pod
        pod["phase"] = "Failed"
        item = checker._check_pod(pod)
        assert item.status == CheckStatus.CRITICAL


class TestHealthCheckScheduler:
    """Tests for HealthCheckScheduler."""
    
    @pytest.fixture
    def mock_checker(self):
        """Create mock health checker."""
        checker = Mock(spec=HealthChecker)
        checker.run_full_check.return_value = HealthCheckResult(
            check_type=CheckType.FULL,
            status=CheckStatus.HEALTHY,
            items=[],
        )
        checker.config = HealthCheckConfig()
        return checker
    
    @pytest.fixture
    def scheduler(self, mock_checker):
        """Create scheduler with mock checker."""
        config = HealthCheckConfig(
            enabled=True,
            interval_seconds=5,
        )
        return HealthCheckScheduler(config=config, checker=mock_checker)
    
    def test_scheduler_initial_state(self, scheduler):
        """Test scheduler initial state."""
        assert not scheduler.is_running
        assert scheduler.last_result is None
    
    def test_scheduler_start_stop(self, scheduler):
        """Test scheduler start and stop."""
        scheduler.start()
        assert scheduler.is_running
        
        scheduler.stop()
        assert not scheduler.is_running
    
    def test_scheduler_disabled(self):
        """Test scheduler doesn't start when disabled."""
        config = HealthCheckConfig(enabled=False)
        scheduler = HealthCheckScheduler(config=config)
        
        scheduler.start()
        assert not scheduler.is_running
    
    def test_run_now(self, scheduler, mock_checker):
        """Test immediate health check."""
        result = scheduler.run_now()
        
        assert result is not None
        assert result.check_type == CheckType.FULL
        mock_checker.run_full_check.assert_called_once()
    
    def test_callback_on_check_complete(self, scheduler, mock_checker):
        """Test callback fires on check complete."""
        callback_called = []
        scheduler.on_check_complete = lambda r: callback_called.append(r)
        
        scheduler.run_now()
        
        assert len(callback_called) == 1
    
    def test_callback_on_status_change(self, scheduler, mock_checker):
        """Test callback fires on status change."""
        callback_called = []
        scheduler.on_status_change = lambda r: callback_called.append(r)
        
        # First check - sets baseline
        scheduler.run_now()
        assert len(callback_called) == 0  # No change on first run
        
        # Second check with different status
        mock_checker.run_full_check.return_value = HealthCheckResult(
            check_type=CheckType.FULL,
            status=CheckStatus.CRITICAL,
            items=[],
        )
        scheduler.run_now()
        
        assert len(callback_called) == 1
    
    def test_callback_on_critical(self, scheduler, mock_checker):
        """Test callback fires on critical status."""
        callback_called = []
        scheduler.on_critical = lambda r: callback_called.append(r)
        
        # Set critical result
        mock_checker.run_full_check.return_value = HealthCheckResult(
            check_type=CheckType.FULL,
            status=CheckStatus.CRITICAL,
            items=[],
        )
        
        scheduler.run_now()
        
        assert len(callback_called) == 1
    
    def test_get_history(self, scheduler):
        """Test history retrieval."""
        scheduler.run_now()
        scheduler.run_now()
        scheduler.run_now()
        
        history = scheduler.get_history(limit=2)
        
        assert len(history) == 2
    
    def test_get_status(self, scheduler):
        """Test status retrieval."""
        status = scheduler.get_status()
        
        assert "running" in status
        assert "enabled" in status
        assert "interval_seconds" in status
    
    def test_update_config(self, scheduler):
        """Test configuration update."""
        scheduler.start()
        assert scheduler.is_running
        
        new_config = HealthCheckConfig(
            enabled=True,
            interval_seconds=120,
        )
        scheduler.update_config(new_config)
        
        assert scheduler.is_running
        assert scheduler.config.interval_seconds == 120


class TestIntegration:
    """Integration tests for health module."""
    
    def test_full_pipeline_mock(self):
        """Test full health check pipeline with mocks."""
        # Create mock ACI
        mock_aci = Mock()
        mock_aci.get_pods.return_value = Mock(
            status=Mock(value="success"),
            data=[
                {
                    "name": "app-pod",
                    "namespace": "production",
                    "phase": "Running",
                    "ready": True,
                    "restart_count": 0,
                    "status": "Running",
                }
            ]
        )
        mock_aci.get_events.return_value = Mock(
            status=Mock(value="success"),
            data=[]
        )
        
        # Create checker
        config = HealthCheckConfig(
            check_types=[CheckType.PODS, CheckType.EVENTS]
        )
        checker = HealthChecker(aci=mock_aci, config=config)
        
        # Run check
        result = checker.run_full_check(namespaces=["production"])
        
        assert result.status == CheckStatus.HEALTHY
        assert result.healthy_count == 1
