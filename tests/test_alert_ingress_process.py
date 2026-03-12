"""Tests covering AlertIngressService.process() — the async pipeline entry point.

Covers lines 109-131 of src/alert/ingress.py (previously uncovered).
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from src.alert.ingress import AlertIngressService
from src.alert.models import StructuredAlert


class TestAlertIngressProcess(unittest.TestCase):
    """Test AlertIngressService.process() async pipeline."""

    def setUp(self):
        self.service = AlertIngressService()
        self.mock_agent = MagicMock()
        self.mock_agent.on_anomaly_detected = AsyncMock(return_value=None)
        self.alert = StructuredAlert(
            source="channel",
            title="High CPU",
            alert_id="proc-001",
            severity="critical",
            provider="cloudwatch",
        )

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_process_returns_detect_result(self):
        result = self._run(self.service.process(self.alert, self.mock_agent))
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "channel")
        self.assertEqual(result.severity, "critical")
        self.assertIs(result.alert, self.alert)
        self.mock_agent.on_anomaly_detected.assert_awaited_once_with(result)

    def test_process_skips_duplicate(self):
        # First call succeeds
        result1 = self._run(self.service.process(self.alert, self.mock_agent))
        self.assertIsNotNone(result1)
        # Second call returns None (duplicate)
        result2 = self._run(self.service.process(self.alert, self.mock_agent))
        self.assertIsNone(result2)
        # Agent should only have been called once
        self.assertEqual(self.mock_agent.on_anomaly_detected.await_count, 1)

    def test_process_different_alerts_both_processed(self):
        alert2 = StructuredAlert(
            source="eventbridge", title="Disk Full",
            alert_id="proc-002", severity="warning", provider="grafana",
        )
        r1 = self._run(self.service.process(self.alert, self.mock_agent))
        r2 = self._run(self.service.process(alert2, self.mock_agent))
        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)
        self.assertEqual(self.mock_agent.on_anomaly_detected.await_count, 2)

    def test_process_populates_detect_result_fields(self):
        """Verify DetectResult has correct alert-derived fields."""
        result = self._run(self.service.process(self.alert, self.mock_agent))
        # Should be a DetectResult instance
        from src.detect_agent import DetectResult
        self.assertIsInstance(result, DetectResult)
        self.assertEqual(result.source, self.alert.source)
        self.assertEqual(result.severity, self.alert.severity)


if __name__ == "__main__":
    unittest.main()
