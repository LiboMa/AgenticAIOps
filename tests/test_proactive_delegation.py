"""
Tests for ProactiveAgent → DetectAgent delegation (Step 3).

Covers:
- _action_quick_scan delegates to DetectAgent.run_detection() (R3)
- ProactiveAgent does NOT call EventCorrelator directly
- _handle_result passes DetectResult to Orchestrator on alert
- _handle_result is silent on "ok" (no Orchestrator call)
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.proactive_agent import ProactiveAgentSystem, ProactiveTask, TaskType


# =============================================================================
# Helpers
# =============================================================================

def _make_detect_result(anomalies=None, with_alarms=False):
    """Create a mock DetectResult."""
    from src.event_correlator import CorrelatedEvent

    alarms = []
    if with_alarms:
        alarm = MagicMock()
        alarm.state = "ALARM"
        alarm.resource_id = "i-alarm123"
        alarm.metric_name = "CPUUtilization"
        alarm.threshold = 90.0
        alarm.name = "HighCPU"
        alarm.reason = "Threshold crossed"
        alarms = [alarm]

    event = MagicMock(spec=CorrelatedEvent)
    event.alarms = alarms
    event.anomalies = anomalies or []
    event.collection_id = "evt-mock-001"

    result = MagicMock()
    result.detect_id = "det-proactive-test"
    result.error = None
    result.correlated_event = event
    result.anomalies_detected = anomalies or []
    result.freshness_label = "fresh"
    result.is_stale = False
    return result


def _make_detect_result_with_error():
    result = MagicMock()
    result.detect_id = "det-err"
    result.error = "AWS timeout"
    result.correlated_event = None
    result.anomalies_detected = []
    result.freshness_label = "fresh"
    return result


@pytest.fixture
def system():
    s = ProactiveAgentSystem.__new__(ProactiveAgentSystem)
    s.agent = None
    s.tasks = {}
    s.results_queue = asyncio.Queue()
    s.callbacks = {}
    s._running = False
    s._heartbeat_task = None
    s._last_detect_result = None
    s._init_default_tasks()
    return s


# =============================================================================
# _action_quick_scan → DetectAgent delegation (R3)
# =============================================================================

class TestQuickScanDelegation:

    @pytest.mark.asyncio
    async def test_delegates_to_detect_agent(self, system):
        """_action_quick_scan must call DetectAgent.run_detection(), not EventCorrelator."""
        mock_result = _make_detect_result()
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            task = system.tasks["heartbeat"]
            result = await system._action_quick_scan(task)

        # DetectAgent.run_detection was called
        mock_agent.run_detection.assert_called_once_with(
            source="proactive_scan",
            services=["ec2", "lambda", "s3", "rds"],
            lookback_minutes=15,
        )

    @pytest.mark.asyncio
    async def test_does_not_call_correlator_directly(self, system):
        """ProactiveAgent should NOT import or call EventCorrelator directly."""
        mock_result = _make_detect_result()
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)), \
             patch("src.event_correlator.get_correlator") as mock_correlator:
            task = system.tasks["heartbeat"]
            await system._action_quick_scan(task)

        # EventCorrelator should NOT be called by ProactiveAgent
        mock_correlator.assert_not_called()

    @pytest.mark.asyncio
    async def test_converts_anomalies_to_findings(self, system):
        """Anomalies from DetectResult should become ProactiveResult findings."""
        anomalies = [
            {"type": "CPUUtilization_anomaly", "resource": "i-123", "metric": "CPUUtilization",
             "value": 95, "severity": "critical", "description": "High CPU"},
        ]
        mock_result = _make_detect_result(anomalies=anomalies)
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            result = await system._action_quick_scan(system.tasks["heartbeat"])

        assert result.status == "alert"
        assert len(result.findings) == 1
        assert result.findings[0]["resource"] == "i-123"

    @pytest.mark.asyncio
    async def test_converts_alarms_to_findings(self, system):
        """Firing CW alarms from correlated event should appear as findings."""
        mock_result = _make_detect_result(with_alarms=True)
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            result = await system._action_quick_scan(system.tasks["heartbeat"])

        assert result.status == "alert"
        alarm_findings = [f for f in result.findings if f["type"] == "cloudwatch_alarm"]
        assert len(alarm_findings) == 1
        assert alarm_findings[0]["resource"] == "i-alarm123"

    @pytest.mark.asyncio
    async def test_ok_when_no_issues(self, system):
        """No anomalies + no alarms → status=ok, summary=HEARTBEAT_OK."""
        mock_result = _make_detect_result()
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            result = await system._action_quick_scan(system.tasks["heartbeat"])

        assert result.status == "ok"
        assert result.summary == "HEARTBEAT_OK"

    @pytest.mark.asyncio
    async def test_caches_detect_result(self, system):
        """DetectResult should be cached on the system for _handle_result."""
        mock_result = _make_detect_result()
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            await system._action_quick_scan(system.tasks["heartbeat"])

        assert system._last_detect_result is mock_result

    @pytest.mark.asyncio
    async def test_handles_detect_agent_error(self, system):
        """If DetectAgent returns error, should handle gracefully."""
        mock_result = _make_detect_result_with_error()
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            result = await system._action_quick_scan(system.tasks["heartbeat"])

        assert result.status == "ok"  # no findings = ok
        assert len(result.findings) == 0

    @pytest.mark.asyncio
    async def test_details_contains_detect_id(self, system):
        """ProactiveResult details should include detect_id and freshness."""
        mock_result = _make_detect_result()
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            result = await system._action_quick_scan(system.tasks["heartbeat"])

        assert result.details["detect_id"] == "det-proactive-test"
        assert result.details["freshness"] == "fresh"


# =============================================================================
# _handle_result → Orchestrator with DetectResult
# =============================================================================

class TestHandleResult:

    @pytest.mark.asyncio
    async def test_alert_triggers_orchestrator_with_detect_result(self, system):
        """Alert should trigger Orchestrator with the cached DetectResult."""
        from src.proactive_agent import ProactiveResult

        mock_detect_result = _make_detect_result()
        system._last_detect_result = mock_detect_result

        mock_incident = MagicMock()
        mock_incident.incident_id = "inc-test"
        mock_incident.status.value = "completed"

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_incident = AsyncMock(return_value=mock_incident)

        alert_result = ProactiveResult(
            task_name="heartbeat",
            task_type=TaskType.HEARTBEAT,
            status="alert",
            timestamp=datetime.now(timezone.utc),
            findings=[{"type": "test"}],
            summary="1 issues detected",
        )

        with patch("src.incident_orchestrator.get_orchestrator", return_value=mock_orchestrator):
            await system._handle_result(alert_result)

        mock_orchestrator.handle_incident.assert_called_once()
        call_kwargs = mock_orchestrator.handle_incident.call_args[1]
        assert call_kwargs["trigger_type"] == "proactive"
        assert call_kwargs["detect_result"] is mock_detect_result

    @pytest.mark.asyncio
    async def test_ok_does_not_trigger_orchestrator(self, system):
        """OK result should NOT trigger the Orchestrator."""
        from src.proactive_agent import ProactiveResult

        ok_result = ProactiveResult(
            task_name="heartbeat",
            task_type=TaskType.HEARTBEAT,
            status="ok",
            timestamp=datetime.now(timezone.utc),
            summary="HEARTBEAT_OK",
        )

        with patch("src.incident_orchestrator.get_orchestrator") as mock_get_orch:
            await system._handle_result(ok_result)

        mock_get_orch.assert_not_called()

    @pytest.mark.asyncio
    async def test_alert_without_detect_result_skips_orchestrator(self, system):
        """Alert with no cached DetectResult should not crash."""
        from src.proactive_agent import ProactiveResult

        system._last_detect_result = None

        alert_result = ProactiveResult(
            task_name="heartbeat",
            task_type=TaskType.HEARTBEAT,
            status="alert",
            timestamp=datetime.now(timezone.utc),
            findings=[{"type": "test"}],
            summary="1 issues detected",
        )

        with patch("src.incident_orchestrator.get_orchestrator") as mock_get_orch:
            await system._handle_result(alert_result)

        mock_get_orch.assert_not_called()
