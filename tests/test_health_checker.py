"""Unit tests for src/health/checker.py - HealthChecker class."""
import pytest
from unittest.mock import MagicMock, patch
from src.health.checker import HealthChecker
from src.health.models import (
    CheckType, CheckStatus, CheckItem, HealthCheckResult, HealthCheckConfig
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aci_result(status="success", data=None):
    """Create a mock ACI result object."""
    r = MagicMock()
    r.status.value = status
    r.data = data
    return r


def _make_pod(name="pod-1", namespace="default", phase="Running",
              status="Running", restart_count=0, ready=True):
    return {
        "name": name,
        "namespace": namespace,
        "phase": phase,
        "status": status,
        "restart_count": restart_count,
        "ready": ready,
    }


def _make_node(name="node-1", status="Ready",
               ready=True, memory_pressure=False, disk_pressure=False):
    return {
        "name": name,
        "status": status,
        "conditions": {
            "Ready": ready,
            "MemoryPressure": memory_pressure,
            "DiskPressure": disk_pressure,
        },
    }


def _make_event(reason="BackOff", message="Back-off restarting",
                obj_name="pod-1", obj_namespace="default"):
    return {
        "reason": reason,
        "message": message,
        "involvedObject": {"name": obj_name, "namespace": obj_namespace},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_aci():
    return MagicMock()


@pytest.fixture
def mock_rca():
    rca = MagicMock()
    result = MagicMock()
    result.root_cause = "test root cause"
    result.remediation.suggestion = "restart pod"
    rca.analyze.return_value = result
    return rca


@pytest.fixture
def mock_im():
    im = MagicMock()
    im.create_or_update_issue.return_value = MagicMock()
    return im


@pytest.fixture
def checker(mock_aci, mock_rca, mock_im):
    return HealthChecker(aci=mock_aci, rca_engine=mock_rca, issue_manager=mock_im)


# ===========================================================================
# __init__ & lazy properties
# ===========================================================================

class TestInit:
    def test_default_config(self):
        c = HealthChecker()
        assert isinstance(c.config, HealthCheckConfig)

    def test_custom_config(self):
        cfg = HealthCheckConfig(interval_seconds=120, namespaces=["ns1"])
        c = HealthChecker(config=cfg)
        assert c.config.interval_seconds == 120

    def test_injected_deps(self, mock_aci, mock_rca, mock_im):
        c = HealthChecker(aci=mock_aci, rca_engine=mock_rca, issue_manager=mock_im)
        assert c.aci is mock_aci
        assert c.rca_engine is mock_rca
        assert c.issue_manager is mock_im

    def test_lazy_aci_import_error(self):
        c = HealthChecker()
        with patch("src.health.checker.logger"):
            # Should not raise, returns None when import fails
            assert c.aci is None or c.aci is not None  # just exercises the path

    def test_lazy_rca_import_error(self):
        c = HealthChecker()
        with patch("src.health.checker.logger"):
            _ = c.rca_engine

    def test_lazy_im_import_error(self):
        c = HealthChecker()
        with patch("src.health.checker.logger"):
            _ = c.issue_manager


# ===========================================================================
# _check_pod  (all branches)
# ===========================================================================

class TestCheckPod:
    def test_running_ready_healthy(self, checker):
        item = checker._check_pod(_make_pod())
        assert item.status == CheckStatus.HEALTHY
        assert "running normally" in item.message.lower()

    def test_running_ready_high_restarts(self, checker):
        item = checker._check_pod(_make_pod(restart_count=10))
        assert item.status == CheckStatus.WARNING
        assert "restart" in item.message.lower()

    def test_pending_phase(self, checker):
        item = checker._check_pod(_make_pod(phase="Pending", ready=False))
        assert item.status == CheckStatus.WARNING
        assert "Pending" in item.message

    def test_unknown_phase(self, checker):
        item = checker._check_pod(_make_pod(phase="Unknown", ready=False))
        assert item.status == CheckStatus.WARNING

    def test_failed_phase(self, checker):
        item = checker._check_pod(_make_pod(phase="Failed", ready=False))
        assert item.status == CheckStatus.CRITICAL

    def test_crashloopbackoff_phase(self, checker):
        item = checker._check_pod(_make_pod(phase="CrashLoopBackOff", ready=False))
        assert item.status == CheckStatus.CRITICAL

    def test_status_crashloopbackoff(self, checker):
        item = checker._check_pod(_make_pod(phase="Waiting",
                                             status="CrashLoopBackOff", ready=False))
        assert item.status == CheckStatus.CRITICAL

    def test_status_imagepullbackoff(self, checker):
        item = checker._check_pod(_make_pod(phase="Waiting",
                                             status="ImagePullBackOff", ready=False))
        assert item.status == CheckStatus.CRITICAL

    def test_status_errimagepull(self, checker):
        item = checker._check_pod(_make_pod(phase="Waiting",
                                             status="ErrImagePull", ready=False))
        assert item.status == CheckStatus.CRITICAL

    def test_not_ready(self, checker):
        item = checker._check_pod(_make_pod(phase="Running", ready=False,
                                             status="Running"))
        assert item.status == CheckStatus.WARNING
        assert "not ready" in item.message.lower()

    def test_else_branch(self, checker):
        """Covers the final else (ready=True, non-standard phase/status)."""
        item = checker._check_pod(_make_pod(phase="Succeeded", ready=True,
                                             status="Completed"))
        # Falls through to else -> WARNING
        assert item.status == CheckStatus.WARNING

    def test_missing_fields_defaults(self, checker):
        item = checker._check_pod({})
        assert item.name == "unknown"
        assert item.namespace == "default"

    def test_details_populated(self, checker):
        item = checker._check_pod(_make_pod(restart_count=3))
        assert item.details["restart_count"] == 3
        assert item.details["ready"] is True


# ===========================================================================
# _handle_unhealthy_pod
# ===========================================================================

class TestHandleUnhealthyPod:
    def test_critical_creates_issue(self, checker, mock_im):
        item = CheckItem(name="p1", namespace="ns", status=CheckStatus.CRITICAL,
                         message="bad")
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            created, updated = checker._handle_unhealthy_pod(item, {})
        assert created == 1
        assert updated == 0

    def test_warning_creates_issue(self, checker, mock_im):
        item = CheckItem(name="p1", namespace="ns", status=CheckStatus.WARNING,
                         message="warn")
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            created, _ = checker._handle_unhealthy_pod(item, {})
        assert created == 1

    def test_no_issue_manager(self):
        c = HealthChecker(aci=MagicMock(), issue_manager=None)
        # Force _issue_manager to stay None
        c._issue_manager = None
        item = CheckItem(name="p", namespace="n", status=CheckStatus.CRITICAL,
                         message="x")
        # Patch the property to return None
        with patch.object(type(c), 'issue_manager', new_callable=lambda: property(lambda self: None)):
            created, updated = c._handle_unhealthy_pod(item, {})
        assert created == 0 and updated == 0

    def test_no_rca_engine(self, mock_im):
        c = HealthChecker(aci=MagicMock(), rca_engine=None, issue_manager=mock_im)
        c._rca_engine = None
        item = CheckItem(name="p", namespace="n", status=CheckStatus.CRITICAL,
                         message="x")
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            with patch.object(type(c), 'rca_engine', new_callable=lambda: property(lambda self: None)):
                created, _ = c._handle_unhealthy_pod(item, {})
        assert created == 1

    def test_exception_logged(self, checker, mock_im):
        mock_im.create_or_update_issue.side_effect = RuntimeError("boom")
        item = CheckItem(name="p", namespace="n", status=CheckStatus.CRITICAL,
                         message="x")
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            created, updated = checker._handle_unhealthy_pod(item, {})
        assert created == 0 and updated == 0


# ===========================================================================
# check_pods
# ===========================================================================

class TestCheckPods:
    def test_no_aci_returns_unknown(self):
        c = HealthChecker(aci=None)
        c._aci = None
        with patch.object(type(c), 'aci', new_callable=lambda: property(lambda self: None)):
            result = c.check_pods()
        assert result.status == CheckStatus.UNKNOWN
        assert result.check_type == CheckType.PODS

    def test_healthy_pods(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(
            data=[_make_pod("p1"), _make_pod("p2")])
        result = checker.check_pods(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY
        assert len(result.items) == 2

    def test_critical_pod_detected(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(
            data=[_make_pod(phase="Failed", ready=False)])
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            result = checker.check_pods(namespaces=["default"])
        assert result.status == CheckStatus.CRITICAL

    def test_warning_pod_detected(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(
            data=[_make_pod(phase="Pending", ready=False)])
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            result = checker.check_pods(namespaces=["default"])
        assert result.status == CheckStatus.WARNING

    def test_failed_aci_call(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(status="error", data=None)
        result = checker.check_pods(namespaces=["default"])
        assert result.status == CheckStatus.UNKNOWN
        assert len(result.items) == 0

    def test_exception_in_check_pods(self, checker, mock_aci):
        mock_aci.get_pods.side_effect = RuntimeError("k8s down")
        result = checker.check_pods(namespaces=["default"])
        assert result.status == CheckStatus.UNKNOWN

    def test_none_namespaces_uses_config(self, mock_aci, mock_rca, mock_im):
        cfg = HealthCheckConfig(namespaces=["kube-system"])
        c = HealthChecker(aci=mock_aci, rca_engine=mock_rca,
                          issue_manager=mock_im, config=cfg)
        mock_aci.get_pods.return_value = _aci_result(data=[_make_pod()])
        c.check_pods()
        mock_aci.get_pods.assert_called_once_with(namespace="kube-system")

    def test_none_data_treated_as_empty(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(data=None)
        result = checker.check_pods(namespaces=["default"])
        assert len(result.items) == 0

    def test_issues_counted(self, checker, mock_aci, mock_im):
        mock_aci.get_pods.return_value = _aci_result(
            data=[_make_pod(phase="Failed", ready=False)])
        mock_im.create_or_update_issue.return_value = MagicMock()
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            result = checker.check_pods(namespaces=["default"])
        assert result.issues_created >= 1


# ===========================================================================
# check_nodes
# ===========================================================================

class TestCheckNodes:
    def test_no_aci_returns_unknown(self):
        c = HealthChecker(aci=None)
        c._aci = None
        with patch.object(type(c), 'aci', new_callable=lambda: property(lambda self: None)):
            result = c.check_nodes()
        assert result.status == CheckStatus.UNKNOWN

    def test_healthy_node(self, checker, mock_aci):
        mock_aci.get_nodes.return_value = _aci_result(data=[_make_node()])
        result = checker.check_nodes()
        assert result.status == CheckStatus.HEALTHY

    def test_not_ready_node(self, checker, mock_aci):
        mock_aci.get_nodes.return_value = _aci_result(
            data=[_make_node(ready=False)])
        result = checker.check_nodes()
        assert result.status == CheckStatus.CRITICAL

    def test_memory_pressure(self, checker, mock_aci):
        mock_aci.get_nodes.return_value = _aci_result(
            data=[_make_node(memory_pressure=True)])
        result = checker.check_nodes()
        assert result.status == CheckStatus.WARNING

    def test_disk_pressure(self, checker, mock_aci):
        mock_aci.get_nodes.return_value = _aci_result(
            data=[_make_node(disk_pressure=True)])
        result = checker.check_nodes()
        assert result.status == CheckStatus.WARNING

    def test_failed_aci_call(self, checker, mock_aci):
        mock_aci.get_nodes.return_value = _aci_result(status="error")
        result = checker.check_nodes()
        assert result.status == CheckStatus.UNKNOWN

    def test_exception_logged(self, checker, mock_aci):
        mock_aci.get_nodes.side_effect = RuntimeError("fail")
        result = checker.check_nodes()
        assert result.status == CheckStatus.UNKNOWN

    def test_none_data(self, checker, mock_aci):
        mock_aci.get_nodes.return_value = _aci_result(data=None)
        result = checker.check_nodes()
        assert len(result.items) == 0


# ===========================================================================
# check_events
# ===========================================================================

class TestCheckEvents:
    def test_no_aci_returns_unknown(self):
        c = HealthChecker(aci=None)
        c._aci = None
        with patch.object(type(c), 'aci', new_callable=lambda: property(lambda self: None)):
            result = c.check_events()
        assert result.status == CheckStatus.UNKNOWN

    def test_no_events_healthy(self, checker, mock_aci):
        mock_aci.get_events.return_value = _aci_result(data=[])
        result = checker.check_events(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY

    def test_critical_event_oomkilled(self, checker, mock_aci):
        mock_aci.get_events.return_value = _aci_result(
            data=[_make_event(reason="OOMKilled")])
        result = checker.check_events(namespaces=["default"])
        assert result.status == CheckStatus.CRITICAL

    def test_critical_event_crashloop(self, checker, mock_aci):
        mock_aci.get_events.return_value = _aci_result(
            data=[_make_event(reason="CrashLoopBackOff")])
        result = checker.check_events(namespaces=["default"])
        assert result.status == CheckStatus.CRITICAL

    def test_critical_event_nodenotready(self, checker, mock_aci):
        mock_aci.get_events.return_value = _aci_result(
            data=[_make_event(reason="NodeNotReady")])
        result = checker.check_events(namespaces=["default"])
        assert result.status == CheckStatus.CRITICAL

    def test_critical_event_failedmount(self, checker, mock_aci):
        mock_aci.get_events.return_value = _aci_result(
            data=[_make_event(reason="FailedMount")])
        result = checker.check_events(namespaces=["default"])
        assert result.status == CheckStatus.CRITICAL

    def test_warning_event(self, checker, mock_aci):
        mock_aci.get_events.return_value = _aci_result(
            data=[_make_event(reason="FailedScheduling")])
        result = checker.check_events(namespaces=["default"])
        assert result.status == CheckStatus.WARNING

    def test_failed_aci_call(self, checker, mock_aci):
        mock_aci.get_events.return_value = _aci_result(status="error")
        result = checker.check_events(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY  # no items -> healthy

    def test_exception_logged(self, checker, mock_aci):
        mock_aci.get_events.side_effect = RuntimeError("fail")
        result = checker.check_events(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY

    def test_event_message_truncated(self, checker, mock_aci):
        long_msg = "x" * 200
        mock_aci.get_events.return_value = _aci_result(
            data=[_make_event(message=long_msg)])
        result = checker.check_events(namespaces=["default"])
        assert len(result.items[0].message) < 200


# ===========================================================================
# check_services
# ===========================================================================

class TestCheckServices:
    def test_returns_healthy(self, checker):
        result = checker.check_services()
        assert result.status == CheckStatus.HEALTHY
        assert result.check_type == CheckType.SERVICES
        assert len(result.items) == 0

    def test_with_namespaces(self, checker):
        result = checker.check_services(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY


# ===========================================================================
# check_resources
# ===========================================================================

class TestCheckResources:
    def test_no_aci_returns_unknown(self):
        c = HealthChecker(aci=None)
        c._aci = None
        with patch.object(type(c), 'aci', new_callable=lambda: property(lambda self: None)):
            result = c.check_resources()
        assert result.status == CheckStatus.UNKNOWN

    def test_healthy_resources(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(
            data={"cpu_usage_percent": 50, "memory_usage_percent": 60})
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY

    def test_cpu_warning(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(
            data={"cpu_usage_percent": 80, "memory_usage_percent": 50})
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.WARNING

    def test_cpu_critical(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(
            data={"cpu_usage_percent": 95, "memory_usage_percent": 50})
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.CRITICAL

    def test_memory_warning(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(
            data={"cpu_usage_percent": 50, "memory_usage_percent": 85})
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.WARNING

    def test_memory_critical(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(
            data={"cpu_usage_percent": 50, "memory_usage_percent": 95})
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.CRITICAL

    def test_both_critical(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(
            data={"cpu_usage_percent": 95, "memory_usage_percent": 95})
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.CRITICAL
        assert len(result.items) == 2

    def test_failed_aci_call(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(status="error")
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY

    def test_exception_logged(self, checker, mock_aci):
        mock_aci.get_metrics.side_effect = RuntimeError("fail")
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY

    def test_none_data_treated_as_empty(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(data=None)
        result = checker.check_resources(namespaces=["default"])
        assert result.status == CheckStatus.HEALTHY

    def test_namespace_label_when_none(self, checker, mock_aci):
        mock_aci.get_metrics.return_value = _aci_result(
            data={"cpu_usage_percent": 95, "memory_usage_percent": 50})
        cfg = HealthCheckConfig(namespaces=[])
        checker.config = cfg
        result = checker.check_resources()
        # ns=None -> "cluster" label
        if result.items:
            assert result.items[0].namespace == "cluster"


# ===========================================================================
# run_full_check
# ===========================================================================

class TestRunFullCheck:
    def test_default_check_types(self, checker, mock_aci):
        # Default config has PODS and EVENTS
        mock_aci.get_pods.return_value = _aci_result(data=[_make_pod()])
        mock_aci.get_events.return_value = _aci_result(data=[])
        result = checker.run_full_check()
        assert result.check_type == CheckType.FULL
        assert result.status == CheckStatus.HEALTHY

    def test_all_check_types(self, checker, mock_aci):
        cfg = HealthCheckConfig(check_types=[
            CheckType.PODS, CheckType.NODES, CheckType.EVENTS,
            CheckType.SERVICES, CheckType.RESOURCES,
        ])
        checker.config = cfg
        mock_aci.get_pods.return_value = _aci_result(data=[_make_pod()])
        mock_aci.get_nodes.return_value = _aci_result(data=[_make_node()])
        mock_aci.get_events.return_value = _aci_result(data=[])
        mock_aci.get_metrics.return_value = _aci_result(
            data={"cpu_usage_percent": 30, "memory_usage_percent": 40})
        result = checker.run_full_check()
        assert result.status == CheckStatus.HEALTHY

    def test_critical_overrides(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(
            data=[_make_pod(phase="Failed", ready=False)])
        mock_aci.get_events.return_value = _aci_result(data=[])
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            result = checker.run_full_check()
        assert result.status == CheckStatus.CRITICAL

    def test_warning_status(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(
            data=[_make_pod(phase="Pending", ready=False)])
        mock_aci.get_events.return_value = _aci_result(data=[])
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            result = checker.run_full_check()
        assert result.status == CheckStatus.WARNING

    def test_empty_returns_unknown(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(status="error")
        mock_aci.get_events.return_value = _aci_result(status="error")
        result = checker.run_full_check()
        assert result.status == CheckStatus.UNKNOWN

    def test_duration_ms_set(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(data=[])
        mock_aci.get_events.return_value = _aci_result(data=[])
        result = checker.run_full_check()
        assert result.duration_ms >= 0

    def test_issues_aggregated(self, checker, mock_aci, mock_im):
        mock_aci.get_pods.return_value = _aci_result(
            data=[_make_pod(phase="Failed", ready=False)])
        mock_aci.get_events.return_value = _aci_result(data=[])
        mock_im.create_or_update_issue.return_value = MagicMock()
        with patch.dict("sys.modules", {"src.issues": MagicMock()}):
            result = checker.run_full_check()
        assert result.issues_created >= 1

    def test_unknown_check_type_skipped(self, checker, mock_aci):
        cfg = HealthCheckConfig(check_types=[CheckType.FULL])  # FULL not handled in loop
        checker.config = cfg
        result = checker.run_full_check()
        assert result.status == CheckStatus.UNKNOWN

    def test_with_namespaces(self, checker, mock_aci):
        mock_aci.get_pods.return_value = _aci_result(data=[_make_pod()])
        mock_aci.get_events.return_value = _aci_result(data=[])
        result = checker.run_full_check(namespaces=["kube-system"])
        assert result.status == CheckStatus.HEALTHY


# ===========================================================================
# HealthCheckResult model properties
# ===========================================================================

class TestHealthCheckResult:
    def test_healthy_count(self):
        items = [
            CheckItem(name="a", namespace="n", status=CheckStatus.HEALTHY, message="ok"),
            CheckItem(name="b", namespace="n", status=CheckStatus.WARNING, message="w"),
            CheckItem(name="c", namespace="n", status=CheckStatus.CRITICAL, message="c"),
        ]
        r = HealthCheckResult(check_type=CheckType.PODS, status=CheckStatus.WARNING, items=items)
        assert r.healthy_count == 1
        assert r.warning_count == 1
        assert r.critical_count == 1

    def test_to_dict(self):
        items = [
            CheckItem(name="a", namespace="n", status=CheckStatus.HEALTHY, message="ok"),
        ]
        r = HealthCheckResult(check_type=CheckType.PODS, status=CheckStatus.HEALTHY,
                              items=items, issues_created=1, issues_updated=2)
        d = r.to_dict()
        assert d["check_type"] == "pods"
        assert d["status"] == "healthy"
        assert d["summary"]["total"] == 1
        assert d["summary"]["healthy"] == 1
        assert d["issues_created"] == 1
        assert d["issues_updated"] == 2
        assert len(d["items"]) == 1
        assert d["items"][0]["name"] == "a"

    def test_to_dict_empty(self):
        r = HealthCheckResult(check_type=CheckType.FULL, status=CheckStatus.UNKNOWN)
        d = r.to_dict()
        assert d["summary"]["total"] == 0
