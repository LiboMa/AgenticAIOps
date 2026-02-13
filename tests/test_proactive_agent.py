"""
Tests for proactive_agent.py — Detect Agent 主动采集框架

Coverage targets:
- ProactiveTask / ProactiveResult dataclasses
- ProactiveAgentSystem: init, task CRUD, scheduling logic
- Heartbeat loop, event triggering
- "无事不扰，有事报告" notification pattern
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.proactive_agent import (
    TaskType,
    ProactiveTask,
    ProactiveResult,
    ProactiveAgentSystem,
    get_proactive_system,
)


# ─── Dataclass Tests ──────────────────────────────────────────────────────────

class TestTaskType:
    def test_heartbeat_value(self):
        assert TaskType.HEARTBEAT.value == "heartbeat"

    def test_cron_value(self):
        assert TaskType.CRON.value == "cron"

    def test_event_value(self):
        assert TaskType.EVENT.value == "event"


class TestProactiveTask:
    def test_creation_defaults(self):
        task = ProactiveTask(
            name="test_task",
            task_type=TaskType.HEARTBEAT,
            action="quick_scan",
        )
        assert task.name == "test_task"
        assert task.task_type == TaskType.HEARTBEAT
        assert task.action == "quick_scan"
        assert task.interval_seconds is None
        assert task.cron_expr is None
        assert task.last_run is None
        assert task.next_run is None
        assert task.enabled is True
        assert task.config == {}

    def test_creation_with_all_fields(self):
        now = datetime.now(timezone.utc)
        task = ProactiveTask(
            name="full_task",
            task_type=TaskType.CRON,
            action="full_report",
            interval_seconds=3600,
            cron_expr="0 * * * *",
            last_run=now,
            next_run=now + timedelta(hours=1),
            enabled=False,
            config={"key": "value"},
        )
        assert task.interval_seconds == 3600
        assert task.cron_expr == "0 * * * *"
        assert task.last_run == now
        assert task.enabled is False
        assert task.config["key"] == "value"


class TestProactiveResult:
    def test_creation_ok(self):
        result = ProactiveResult(
            task_name="heartbeat",
            task_type=TaskType.HEARTBEAT,
            status="ok",
            timestamp=datetime.now(timezone.utc),
            summary="HEARTBEAT_OK",
        )
        assert result.status == "ok"
        assert result.findings == []
        assert result.details is None

    def test_creation_alert(self):
        result = ProactiveResult(
            task_name="security",
            task_type=TaskType.CRON,
            status="alert",
            timestamp=datetime.now(timezone.utc),
            findings=[{"issue": "public_bucket"}],
            summary="1 issues detected",
        )
        assert result.status == "alert"
        assert len(result.findings) == 1


# ─── ProactiveAgentSystem Tests ───────────────────────────────────────────────

class TestProactiveAgentSystemInit:
    def test_default_tasks_created(self):
        system = ProactiveAgentSystem()
        assert "heartbeat" in system.tasks
        assert "daily_report" in system.tasks
        assert "security_scan" in system.tasks

    def test_heartbeat_task_config(self):
        system = ProactiveAgentSystem()
        hb = system.tasks["heartbeat"]
        assert hb.task_type == TaskType.HEARTBEAT
        assert hb.action == "quick_scan"
        assert hb.interval_seconds == 300
        assert hb.enabled is True

    def test_daily_report_task_config(self):
        system = ProactiveAgentSystem()
        dr = system.tasks["daily_report"]
        assert dr.task_type == TaskType.CRON
        assert dr.action == "full_report"
        assert dr.interval_seconds == 86400
        assert dr.cron_expr == "0 8 * * *"

    def test_security_scan_task_config(self):
        system = ProactiveAgentSystem()
        ss = system.tasks["security_scan"]
        assert ss.action == "security_check"
        assert ss.interval_seconds == 43200

    def test_init_with_agent(self):
        mock_agent = MagicMock()
        system = ProactiveAgentSystem(agent=mock_agent)
        assert system.agent is mock_agent

    def test_initial_state(self):
        system = ProactiveAgentSystem()
        assert system._running is False
        assert system._heartbeat_task is None


class TestTaskManagement:
    def test_enable_task(self):
        system = ProactiveAgentSystem()
        system.enable_task("heartbeat", False)
        assert system.tasks["heartbeat"].enabled is False

    def test_enable_task_true(self):
        system = ProactiveAgentSystem()
        system.enable_task("heartbeat", False)
        system.enable_task("heartbeat", True)
        assert system.tasks["heartbeat"].enabled is True

    def test_enable_nonexistent_task(self):
        system = ProactiveAgentSystem()
        # Should not raise
        system.enable_task("nonexistent", True)

    def test_update_task_interval(self):
        system = ProactiveAgentSystem()
        system.update_task_interval("heartbeat", 60)
        assert system.tasks["heartbeat"].interval_seconds == 60

    def test_update_nonexistent_task_interval(self):
        system = ProactiveAgentSystem()
        # Should not raise
        system.update_task_interval("nonexistent", 60)

    def test_register_callback(self):
        system = ProactiveAgentSystem()
        callback = AsyncMock()
        system.register_callback("alert", callback)
        assert "alert" in system.callbacks

    def test_get_status(self):
        system = ProactiveAgentSystem()
        status = system.get_status()
        assert status["running"] is False
        assert "heartbeat" in status["tasks"]
        assert status["tasks"]["heartbeat"]["enabled"] is True
        assert status["tasks"]["heartbeat"]["action"] == "quick_scan"
        assert status["tasks"]["heartbeat"]["last_run"] is None

    def test_get_status_with_last_run(self):
        system = ProactiveAgentSystem()
        now = datetime.now(timezone.utc)
        system.tasks["heartbeat"].last_run = now
        status = system.get_status()
        assert status["tasks"]["heartbeat"]["last_run"] == now.isoformat()


# ─── Scheduling Logic ─────────────────────────────────────────────────────────

class TestShouldRun:
    def test_first_run_always_true(self):
        system = ProactiveAgentSystem()
        task = system.tasks["heartbeat"]
        assert task.last_run is None
        assert system._should_run(task) is True

    def test_not_due_yet(self):
        system = ProactiveAgentSystem()
        task = system.tasks["heartbeat"]
        task.last_run = datetime.now(timezone.utc)
        assert system._should_run(task) is False

    def test_due_after_interval(self):
        system = ProactiveAgentSystem()
        task = system.tasks["heartbeat"]
        task.last_run = datetime.now(timezone.utc) - timedelta(seconds=301)
        assert system._should_run(task) is True

    def test_no_interval_after_first_run(self):
        system = ProactiveAgentSystem()
        task = ProactiveTask(
            name="no_interval",
            task_type=TaskType.EVENT,
            action="analyze_alert",
        )
        task.last_run = datetime.now(timezone.utc)
        # No interval_seconds → should not run again
        assert system._should_run(task) is False


# ─── Task Execution ───────────────────────────────────────────────────────────

class TestTaskExecution:
    @pytest.fixture
    def system(self):
        return ProactiveAgentSystem()

    @pytest.fixture
    def mock_correlator(self):
        """Mock EventCorrelator so quick_scan doesn't hit real AWS."""
        mock_event = MagicMock()
        mock_event.anomalies = []
        mock_event.alarms = []
        mock_event.trail_events = []
        mock_event.health_events = []

        mock_corr = MagicMock()
        mock_corr.collect = AsyncMock(return_value=mock_event)

        with patch("src.proactive_agent.get_correlator", return_value=mock_corr) as _:
            # Also patch the import inside _action_quick_scan
            with patch.dict("sys.modules", {}):
                pass
        return mock_corr, mock_event

    @pytest.mark.asyncio
    async def test_quick_scan_ok_no_findings(self, system):
        """Quick scan with no anomalies returns ok."""
        mock_result = MagicMock()
        mock_result.error = None
        mock_result.anomalies_detected = []
        mock_result.correlated_event = MagicMock()
        mock_result.correlated_event.alarms = []

        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            result = await system._execute_task(system.tasks["heartbeat"])
        assert result.task_name == "heartbeat"
        assert result.task_type == TaskType.HEARTBEAT
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_quick_scan_with_anomalies(self, system):
        """Quick scan with anomalies returns alert."""
        mock_result = MagicMock()
        mock_result.error = None
        mock_result.anomalies_detected = [
            {"type": "cpu_spike", "resource": "i-123", "metric": "CPUUtilization",
             "value": 95, "severity": "high", "description": "CPU > 90%"}
        ]
        mock_result.correlated_event = MagicMock()
        mock_result.correlated_event.alarms = []

        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            result = await system._execute_task(system.tasks["heartbeat"])
        assert result.status == "alert"
        assert len(result.findings) >= 1

    @pytest.mark.asyncio
    async def test_quick_scan_correlator_error_fallback(self, system):
        """Quick scan handles DetectAgent errors and falls back to scanner."""
        mock_scanner = MagicMock()
        mock_scanner.scan_all_resources.return_value = {
            "summary": {"issues_found": []}
        }
        with patch("src.detect_agent.get_detect_agent_async", side_effect=Exception("DetectAgent error")):
            with patch("src.aws_scanner.get_scanner", return_value=mock_scanner):
                with patch("src.event_correlator.get_correlator", side_effect=Exception("also fails")):
                    result = await system._execute_task(system.tasks["heartbeat"])
        assert result.task_name == "heartbeat"

    @pytest.mark.asyncio
    async def test_full_report(self, system):
        mock_scanner = MagicMock()
        mock_scanner.scan_all_resources.return_value = {
            "services": {
                "ec2": {"count": 5, "status": {"running": 4, "stopped": 1}},
                "lambda": {"count": 3, "status": {}},
            },
            "summary": {"issues_found": []},
        }
        with patch("src.aws_scanner.get_scanner", return_value=mock_scanner):
            result = await system._execute_task(system.tasks["daily_report"])
        assert result.task_name == "daily_report"
        assert result.status == "ok"
        assert "Health Report" in result.summary

    @pytest.mark.asyncio
    async def test_security_check(self, system):
        mock_scanner = MagicMock()
        mock_scanner.scan_all_resources.return_value = {
            "services": {
                "iam": {"users_without_mfa": []},
                "s3": {"public_count": 0, "buckets": []},
                "ec2": {"instances": []},
            },
            "summary": {"issues_found": []},
        }
        # Mock individual scanner methods that security_check uses
        mock_scanner._scan_iam.return_value = {"users_without_mfa": []}
        mock_scanner._scan_s3.return_value = {"public_count": 0, "buckets": []}
        mock_scanner._get_client.return_value = MagicMock()
        with patch("src.aws_scanner.get_scanner", return_value=mock_scanner):
            result = await system._execute_task(system.tasks["security_scan"])
        assert result.task_name == "security_scan"

    @pytest.mark.asyncio
    async def test_unknown_action(self, system):
        task = ProactiveTask(
            name="unknown",
            task_type=TaskType.CRON,
            action="nonexistent_action",
        )
        result = await system._execute_task(task)
        assert result.status == "error"
        assert "Unknown action" in result.summary


# ─── Result Handling ("无事不扰，有事报告") ────────────────────────────────────

class TestResultHandling:
    @pytest.mark.asyncio
    async def test_ok_result_not_queued(self):
        system = ProactiveAgentSystem()
        ok_result = ProactiveResult(
            task_name="test",
            task_type=TaskType.HEARTBEAT,
            status="ok",
            timestamp=datetime.now(timezone.utc),
            summary="all good",
        )
        await system._handle_result(ok_result)
        assert system.results_queue.empty()

    @pytest.mark.asyncio
    async def test_alert_result_queued(self):
        system = ProactiveAgentSystem()
        alert_result = ProactiveResult(
            task_name="test",
            task_type=TaskType.HEARTBEAT,
            status="alert",
            timestamp=datetime.now(timezone.utc),
            findings=[{"issue": "something"}],
            summary="1 issues detected",
        )
        await system._handle_result(alert_result)
        assert not system.results_queue.empty()
        queued = await system.results_queue.get()
        assert queued.status == "alert"

    @pytest.mark.asyncio
    async def test_alert_triggers_callback(self):
        system = ProactiveAgentSystem()
        callback = AsyncMock()
        system.register_callback("alert", callback)

        alert_result = ProactiveResult(
            task_name="test",
            task_type=TaskType.HEARTBEAT,
            status="alert",
            timestamp=datetime.now(timezone.utc),
            summary="issue",
        )
        await system._handle_result(alert_result)
        callback.assert_awaited_once_with(alert_result)

    @pytest.mark.asyncio
    async def test_ok_does_not_trigger_callback(self):
        system = ProactiveAgentSystem()
        callback = AsyncMock()
        system.register_callback("alert", callback)

        ok_result = ProactiveResult(
            task_name="test",
            task_type=TaskType.HEARTBEAT,
            status="ok",
            timestamp=datetime.now(timezone.utc),
            summary="fine",
        )
        await system._handle_result(ok_result)
        callback.assert_not_awaited()


# ─── Event Triggering ─────────────────────────────────────────────────────────

class TestEventTriggering:
    @pytest.mark.asyncio
    async def test_trigger_event(self):
        system = ProactiveAgentSystem()
        result = await system.trigger_event(
            "cloudwatch_alarm",
            {"alarm": "HighCPU", "instance": "i-12345"}
        )
        assert result.task_name == "event_cloudwatch_alarm"
        assert result.task_type == TaskType.EVENT

    @pytest.mark.asyncio
    async def test_trigger_event_creates_adhoc_task(self):
        system = ProactiveAgentSystem()
        # Should not crash; the task action "analyze_alert" is unknown
        # so it returns an error result
        result = await system.trigger_event("custom", {"data": "test"})
        assert result.status == "error"
        assert "Unknown action" in result.summary


# ─── Start/Stop Lifecycle ─────────────────────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        system = ProactiveAgentSystem()
        await system.start()
        assert system._running is True
        assert system._heartbeat_task is not None
        await system.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self):
        system = ProactiveAgentSystem()
        await system.start()
        await system.stop()
        assert system._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self):
        system = ProactiveAgentSystem()
        await system.start()
        first_task = system._heartbeat_task
        await system.start()  # Should not create duplicate
        assert system._heartbeat_task is first_task
        await system.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        system = ProactiveAgentSystem()
        await system.stop()  # Should not crash
        assert system._running is False


# ─── Singleton ─────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_proactive_system_returns_instance(self):
        # Reset singleton for clean test
        import src.proactive_agent as pa
        pa.proactive_system = None

        system1 = get_proactive_system()
        system2 = get_proactive_system()
        assert system1 is system2

        # Cleanup
        pa.proactive_system = None

    def test_get_proactive_system_with_agent(self):
        import src.proactive_agent as pa
        pa.proactive_system = None

        mock_agent = MagicMock()
        system = get_proactive_system(agent=mock_agent)
        assert system.agent is mock_agent

        # Cleanup
        pa.proactive_system = None
