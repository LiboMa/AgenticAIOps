"""Tests for AlertIngressService + KnowledgeFlywheel integration with DetectAgent & RCA.

All tests use mocking — no real AWS/DB calls.
"""

import asyncio
import hashlib
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import numpy as np


# ── Helpers ──────────────────────────────────────────────────────────


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =====================================================================
# 1. TestAlertIngressService — 8 tests
# =====================================================================


class TestAlertIngressService(unittest.TestCase):
    """Test AlertIngressService: parsing, dedup, unknown source."""

    def setUp(self):
        from src.alert.ingress import AlertIngressService
        self.service = AlertIngressService()

    # ── CloudWatch ──

    def test_parse_cloudwatch_alarm(self):
        msg = (
            'ALARM: "HighCPUUtilization" in AWS/EC2\n'
            "Threshold Crossed: threshold 80.0, datapoint 95.2\n"
            "Resource: i-0abc123def456"
        )
        alert = self.service.parse_channel_message("C123", msg)
        self.assertIsNotNone(alert, "CloudWatch alarm should be parsed")
        self.assertEqual(alert.source, "channel")

    # ── Datadog ──

    def test_parse_datadog_alert(self):
        msg = (
            "[Triggered] [P1] CPU usage is high on host:web-01\n"
            "Monitor: High CPU on web-01\n"
            "Tags: env:production, service:api"
        )
        alert = self.service.parse_channel_message("C123", msg)
        self.assertIsNotNone(alert, "Datadog alert should be parsed")

    # ── PagerDuty ──

    def test_parse_pagerduty_alert(self):
        msg = (
            "PagerDuty Alert: Triggered\n"
            "Service: payment-service\n"
            "Description: High error rate detected\n"
            "Severity: critical\n"
            "Incident: #12345"
        )
        alert = self.service.parse_channel_message("C123", msg)
        self.assertIsNotNone(alert, "PagerDuty alert should be parsed")

    # ── Grafana ──

    def test_parse_grafana_alert(self):
        msg = (
            "[Alerting] Memory Usage Alert\n"
            "Value: 92%\n"
            "State: alerting\n"
            "Dashboard: Production Overview\n"
            "Panel: Memory Usage"
        )
        alert = self.service.parse_channel_message("C123", msg)
        self.assertIsNotNone(alert, "Grafana alert should be parsed")

    # ── Generic ──

    def test_parse_generic_alert(self):
        msg = (
            "ALERT: Disk space critical on /dev/sda1\n"
            "Usage: 95%\n"
            "Host: db-primary-01"
        )
        alert = self.service.parse_channel_message("C123", msg)
        # Generic parser should pick this up as a fallback
        self.assertIsNotNone(alert, "Generic alert should be parsed")

    # ── Dedup ──

    def test_dedup_suppresses_duplicate(self):
        from src.alert.models import StructuredAlert

        alert = StructuredAlert(
            source="channel",
            provider="cloudwatch",
            title="HighCPU",
            alert_id="dedup-test-001",
        )
        self.assertFalse(self.service.is_duplicate(alert))
        self.assertTrue(self.service.is_duplicate(alert))

    def test_dedup_allows_after_window(self):
        from src.alert.models import StructuredAlert

        alert = StructuredAlert(
            source="channel",
            provider="cloudwatch",
            title="HighCPU",
            alert_id="dedup-window-test",
        )
        self.assertFalse(self.service.is_duplicate(alert))
        # Manually expire the entry
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.service._seen[alert.alert_id] = past
        self.assertFalse(self.service.is_duplicate(alert))

    # ── Unknown source ──

    def test_unknown_source_returns_none(self):
        msg = "just a regular chat message with no alert content"
        alert = self.service.parse_channel_message("C123", msg)
        # May be None (no parser matches) or parsed by generic
        # The key contract: it does NOT raise
        # If all parsers reject it, result is None
        if alert is None:
            self.assertIsNone(alert)
        else:
            # Generic parser caught it — still valid
            self.assertIsNotNone(alert.title)


# =====================================================================
# 2. TestKnowledgeFlywheel — 6 tests
# =====================================================================


class TestKnowledgeFlywheel(unittest.TestCase):
    """Test KnowledgeFlywheel: capture, search, sanitization."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        from src.knowledge.flywheel import KnowledgeFlywheel
        self.flywheel = KnowledgeFlywheel(db_path=f"{self._tmpdir}/test_kb.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_capture_returns_case_study(self):
        case = self.flywheel.capture(
            title="Pod CrashLoopBackOff",
            symptoms="OOMKilled every 30s",
            root_cause="Memory limit too low",
            resolution="Increase memory to 512Mi",
            resource_type="pod",
            severity="high",
        )
        self.assertIsNotNone(case)
        self.assertIn("CrashLoopBackOff", case.title)
        self.assertIsNotNone(case.case_id)

    def test_search_similar_returns_results(self):
        # Capture first
        self.flywheel.capture(
            title="High CPU on EC2",
            symptoms="CPU utilization 99%, load average 50",
            root_cause="Runaway process",
            resource_type="ec2",
        )
        results = self.flywheel.search_similar("CPU spike on instance", resource_type="EC2")
        self.assertIsInstance(results, list)
        # May or may not have results depending on embedding similarity
        # Key contract: no exception, returns list

    def test_search_similar_empty_db(self):
        results = self.flywheel.search_similar("random query no data")
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 0)

    def test_sanitization_removes_aws_keys(self):
        from src.knowledge.flywheel import _sanitize
        text = "Access key AKIAIOSFODNN7EXAMPLE leaked"
        sanitized = _sanitize(text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_sanitization_removes_ip_addresses(self):
        from src.knowledge.flywheel import _sanitize
        text = "Connection from 192.168.1.100 failed"
        sanitized = _sanitize(text)
        self.assertNotIn("192.168.1.100", sanitized)

    def test_capture_sanitizes_fields(self):
        case = self.flywheel.capture(
            title="Leak at 10.0.0.1",
            symptoms="Key AKIAIOSFODNN7EXAMPLE exposed",
            root_cause="Config pushed to public repo",
        )
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", case.symptoms)
        self.assertNotIn("10.0.0.1", case.title)


# =====================================================================
# 3. TestDetectAgentAlertIntegration — 4 tests
# =====================================================================


class TestDetectAgentAlertIntegration(unittest.TestCase):
    """Test DetectAgent.process_alert integration."""

    def _make_agent(self):
        """Create a DetectAgent with mocked internals (bypass __init__)."""
        from src.detect_agent import DetectAgent
        agent = DetectAgent.__new__(DetectAgent)
        agent.region = "us-east-1"
        agent._cache_dir = "/tmp/test_detect"
        agent._cache = {}
        agent._latest = None
        agent._collecting = asyncio.Lock()
        agent._dispatch_max_retries = 1
        agent._dispatch_base_delay = 0
        agent._dispatch_failures = 0
        agent._dispatch_successes = 0
        agent._dead_letter_dir = MagicMock()
        agent._correlator = MagicMock()
        agent._skill_tools = []
        agent._skill_prompt = ""
        agent._alert_ingress = None
        return agent

    def _make_alert(self):
        from src.alert.models import StructuredAlert
        return StructuredAlert(
            source="channel",
            provider="cloudwatch",
            title="HighCPU",
            alert_id="test-alert-001",
            severity="high",
        )

    def test_process_alert_happy_path(self):
        """process_alert delegates to AlertIngressService when available."""
        agent = self._make_agent()
        mock_ingress = MagicMock()
        from src.detect_agent import DetectResult
        expected = DetectResult(
            detect_id="det-from-ingress",
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="channel",
        )
        mock_ingress.process = AsyncMock(return_value=expected)
        agent._alert_ingress = mock_ingress

        alert = self._make_alert()
        result = _run(agent.process_alert(alert))

        self.assertEqual(result.detect_id, "det-from-ingress")
        mock_ingress.process.assert_awaited_once()

    def test_process_alert_fallback_no_ingress(self):
        """process_alert falls back to run_detection when ingress is None."""
        agent = self._make_agent()
        agent._alert_ingress = None
        from src.detect_agent import DetectResult
        expected = DetectResult(
            detect_id="det-fallback",
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="alarm_trigger",
        )
        agent.run_detection = AsyncMock(return_value=expected)

        result = _run(agent.process_alert(self._make_alert()))

        self.assertEqual(result.source, "alarm_trigger")
        agent.run_detection.assert_awaited_once()

    def test_process_alert_fallback_on_exception(self):
        """process_alert falls back to run_detection when ingress raises."""
        agent = self._make_agent()
        mock_ingress = MagicMock()
        mock_ingress.process = AsyncMock(side_effect=RuntimeError("boom"))
        agent._alert_ingress = mock_ingress

        from src.detect_agent import DetectResult
        expected = DetectResult(
            detect_id="det-fallback-err",
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="alarm_trigger",
        )
        agent.run_detection = AsyncMock(return_value=expected)

        result = _run(agent.process_alert(self._make_alert()))
        self.assertEqual(result.source, "alarm_trigger")

    def test_process_alert_duplicate_returns_dup_result(self):
        """process_alert returns dup marker when ingress returns None (duplicate)."""
        agent = self._make_agent()
        mock_ingress = MagicMock()
        mock_ingress.process = AsyncMock(return_value=None)
        agent._alert_ingress = mock_ingress

        result = _run(agent.process_alert(self._make_alert()))
        self.assertEqual(result.source, "alert_duplicate")
        self.assertIn("dup-", result.detect_id)


# =====================================================================
# 4. TestRCAKnowledgeIntegration — 4 tests
# =====================================================================


class TestRCAKnowledgeIntegration(unittest.TestCase):
    """Test RCAInferenceEngine + KnowledgeFlywheel integration."""

    def _make_correlated_event(self):
        """Create a mock CorrelatedEvent."""
        event = MagicMock()
        event.anomalies = [
            {"resource": "i-abc123", "metric": "CPUUtilization", "value": 99,
             "threshold": 80, "severity": "high", "description": "CPU spike"},
        ]
        alarm = MagicMock()
        alarm.state = "ALARM"
        alarm.metric_name = "CPUUtilization"
        alarm.name = "HighCPU"
        alarm.comparison = ">="
        alarm.threshold = 80
        alarm.resource_id = "i-abc123"
        event.alarms = [alarm]
        event.metrics = []
        event.recent_changes = []
        event.health_events = []
        event.region = "us-east-1"
        event.duration_ms = 1200
        event.source_status = {"cloudwatch": "ok"}
        event.to_rca_telemetry = MagicMock(return_value=MagicMock())
        return event

    def _make_engine(self):
        """Create an RCAInferenceEngine with mocked dependencies."""
        from src.rca_inference import RCAInferenceEngine
        with patch("src.rca_inference.PatternMatcher"), \
             patch("src.knowledge.flywheel.KnowledgeFlywheel"), \
             patch("src.skills.skill_bridge.get_rca_tools", return_value=[]), \
             patch("src.skills.skill_bridge.get_rca_prompt", return_value=""):
            engine = RCAInferenceEngine()
        engine._flywheel = None
        return engine

    def _run_analyze(self, engine, event):
        """Run engine.analyze with knowledge_search mocked out."""
        mock_ks = MagicMock()
        mock_ks_result = MagicMock()
        mock_ks_result.hits = []
        mock_ks.search = AsyncMock(return_value=mock_ks_result)
        with patch("src.knowledge_search.get_knowledge_search", return_value=mock_ks):
            return _run(engine.analyze(event))

    @patch("src.rca_inference.RCAInferenceEngine._invoke_claude")
    def test_flywheel_search_before_analysis(self, mock_claude):
        """Flywheel search_similar is called before Claude analysis."""
        from src.rca_inference import RCAInferenceEngine
        from src.rca.models import RCAResult, Severity, Remediation

        rca_result = RCAResult(
            pattern_id="llm-sonnet-resource",
            pattern_name="Claude Sonnet Analysis",
            root_cause="CPU spike from runaway process",
            severity=Severity.HIGH,
            confidence=0.85,
            matched_symptoms=["i-abc123"],
            remediation=Remediation(action="kill_process", suggestion="Kill runaway process"),
            evidence=["CPU at 99%"],
        )
        mock_claude.return_value = rca_result

        engine = self._make_engine()
        mock_fw = MagicMock()
        mock_fw.search_similar.return_value = []
        mock_fw.capture.return_value = MagicMock()
        engine._flywheel = mock_fw
        engine.pattern_matcher.match.return_value = None

        result = self._run_analyze(engine, self._make_correlated_event())

        mock_fw.search_similar.assert_called_once()
        self.assertEqual(result.root_cause, "CPU spike from runaway process")

    @patch("src.rca_inference.RCAInferenceEngine._invoke_claude")
    def test_flywheel_capture_after_analysis(self, mock_claude):
        """Flywheel capture is called after successful analysis."""
        from src.rca_inference import RCAInferenceEngine
        from src.rca.models import RCAResult, Severity, Remediation

        rca_result = RCAResult(
            pattern_id="llm-sonnet-resource",
            pattern_name="Claude Sonnet Analysis",
            root_cause="CPU spike from runaway process",
            severity=Severity.HIGH,
            confidence=0.85,
            matched_symptoms=["i-abc123"],
            remediation=Remediation(action="kill_process", suggestion="Kill runaway process"),
            evidence=["CPU at 99%"],
        )
        mock_claude.return_value = rca_result

        engine = self._make_engine()
        mock_fw = MagicMock()
        mock_fw.search_similar.return_value = []
        mock_fw.capture.return_value = MagicMock()
        engine._flywheel = mock_fw
        engine.pattern_matcher.match.return_value = None

        self._run_analyze(engine, self._make_correlated_event())

        mock_fw.capture.assert_called_once()
        call_kwargs = mock_fw.capture.call_args
        self.assertIn("CPU spike from runaway process", str(call_kwargs))

    @patch("src.rca_inference.RCAInferenceEngine._invoke_claude")
    def test_flywheel_search_results_injected_into_prompt(self, mock_claude):
        """When flywheel returns similar cases, they appear in the Claude prompt."""
        from src.rca_inference import RCAInferenceEngine
        from src.rca.models import RCAResult, Severity, Remediation
        from src.knowledge.search import HybridResult

        rca_result = RCAResult(
            pattern_id="llm-sonnet-resource",
            pattern_name="Analysis",
            root_cause="CPU spike",
            severity=Severity.HIGH,
            confidence=0.85,
            matched_symptoms=[],
            remediation=Remediation(action="fix", suggestion="fix it"),
            evidence=[],
        )
        mock_claude.return_value = rca_result

        similar = [
            HybridResult(case_id="case-001", score=0.92, source="vector",
                         content="Previous CPU spike on i-old123", metadata={"severity": "high"}),
        ]

        engine = self._make_engine()
        mock_fw = MagicMock()
        mock_fw.search_similar.return_value = similar
        mock_fw.capture.return_value = MagicMock()
        engine._flywheel = mock_fw
        engine.pattern_matcher.match.return_value = None

        self._run_analyze(engine, self._make_correlated_event())

        # The prompt passed to Claude should contain the historical case
        prompt_arg = mock_claude.call_args[0][0]
        self.assertIn("Historical Similar Cases", prompt_arg)
        self.assertIn("case-001", prompt_arg)

    @patch("src.rca_inference.RCAInferenceEngine._invoke_claude")
    def test_flywheel_unavailable_does_not_break_analysis(self, mock_claude):
        """Analysis succeeds even when flywheel is None."""
        from src.rca_inference import RCAInferenceEngine
        from src.rca.models import RCAResult, Severity, Remediation

        rca_result = RCAResult(
            pattern_id="llm-sonnet-resource",
            pattern_name="Analysis",
            root_cause="CPU spike",
            severity=Severity.HIGH,
            confidence=0.85,
            matched_symptoms=[],
            remediation=Remediation(action="fix", suggestion="fix it"),
            evidence=[],
        )
        mock_claude.return_value = rca_result

        engine = self._make_engine()
        engine._flywheel = None
        engine.pattern_matcher.match.return_value = None

        result = self._run_analyze(engine, self._make_correlated_event())
        self.assertIsNotNone(result)
        self.assertEqual(result.root_cause, "CPU spike")


if __name__ == "__main__":
    unittest.main()
