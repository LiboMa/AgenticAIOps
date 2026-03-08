"""Comprehensive tests for alert parsers — edge cases and coverage.

Phase 1-2 coverage: StructuredAlert model + AlertIngressService + 5 parsers.
"""

import hashlib
import json
import unittest
from datetime import datetime, timezone, timedelta

from src.alert.models import StructuredAlert, normalize_severity
from src.alert.ingress import AlertIngressService
from src.alert.parsers import (
    ALL_PARSERS,
    CloudWatchAlertParser,
    DatadogAlertParser,
    PagerDutyAlertParser,
    GrafanaAlertParser,
    GenericAlertParser,
)


# =====================================================================
# 1. normalize_severity
# =====================================================================

class TestNormalizeSeverity(unittest.TestCase):
    """Test severity normalization mapping."""

    def test_canonical_values(self):
        for s in ("critical", "high", "medium", "low"):
            self.assertEqual(normalize_severity(s), s)

    def test_case_insensitive(self):
        self.assertEqual(normalize_severity("CRITICAL"), "critical")
        self.assertEqual(normalize_severity("Warning"), "medium")
        self.assertEqual(normalize_severity("ERROR"), "high")

    def test_datadog_variants(self):
        self.assertEqual(normalize_severity("error"), "high")
        self.assertEqual(normalize_severity("warning"), "medium")
        self.assertEqual(normalize_severity("info"), "low")

    def test_pagerduty_priorities(self):
        self.assertEqual(normalize_severity("p1"), "critical")
        self.assertEqual(normalize_severity("p2"), "high")
        self.assertEqual(normalize_severity("p3"), "medium")
        self.assertEqual(normalize_severity("p4"), "low")

    def test_emergency_variants(self):
        for s in ("urgent", "fatal", "emergency", "emerg"):
            self.assertEqual(normalize_severity(s), "critical")

    def test_unknown_defaults_medium(self):
        self.assertEqual(normalize_severity("banana"), "medium")
        self.assertEqual(normalize_severity(""), "medium")

    def test_whitespace_stripped(self):
        self.assertEqual(normalize_severity("  critical  "), "critical")


# =====================================================================
# 2. StructuredAlert model
# =====================================================================

class TestStructuredAlertModel(unittest.TestCase):
    """Test StructuredAlert Pydantic model."""

    def test_minimal_creation(self):
        alert = StructuredAlert(source="channel", title="test")
        self.assertEqual(alert.source, "channel")
        self.assertEqual(alert.title, "test")
        self.assertEqual(alert.severity, "medium")
        self.assertIsNotNone(alert.alert_id)

    def test_severity_auto_normalized(self):
        alert = StructuredAlert(source="webhook", title="t", severity="P1")
        self.assertEqual(alert.severity, "critical")

    def test_alert_id_auto_generated(self):
        alert = StructuredAlert(
            source="channel", provider="cloudwatch",
            title="High CPU", resource_hint="i-abc123"
        )
        expected = hashlib.sha256(b"cloudwatch:High CPU:i-abc123").hexdigest()[:16]
        self.assertEqual(alert.alert_id, expected)

    def test_alert_id_explicit(self):
        alert = StructuredAlert(
            source="channel", title="t", alert_id="my-id"
        )
        self.assertEqual(alert.alert_id, "my-id")

    def test_timestamps_set(self):
        alert = StructuredAlert(source="manual", title="t")
        self.assertIsInstance(alert.timestamp, datetime)
        self.assertIsInstance(alert.received_at, datetime)

    def test_all_sources_valid(self):
        for src in ("channel", "eventbridge", "cloudtrail", "webhook", "manual"):
            a = StructuredAlert(source=src, title="t")
            self.assertEqual(a.source, src)

    def test_tags_and_raw_data(self):
        alert = StructuredAlert(
            source="channel", title="t",
            tags={"env": "prod"}, raw_data={"key": "val"}
        )
        self.assertEqual(alert.tags["env"], "prod")
        self.assertEqual(alert.raw_data["key"], "val")


# =====================================================================
# 3. CloudWatch Parser
# =====================================================================

class TestCloudWatchParser(unittest.TestCase):
    """Test CloudWatch alert parser."""

    def setUp(self):
        self.parser = CloudWatchAlertParser()

    def test_can_parse_alarm_text(self):
        self.assertTrue(self.parser.can_parse('ALARM: "High CPU on i-0abc" in us-east-1'))

    def test_can_parse_json_payload(self):
        payload = json.dumps({"AlarmName": "HighCPU", "Region": "us-east-1"})
        self.assertTrue(self.parser.can_parse(payload))

    def test_can_parse_keyword(self):
        self.assertTrue(self.parser.can_parse("cloudwatch alarm triggered"))

    def test_cannot_parse_unrelated(self):
        self.assertFalse(self.parser.can_parse("Hello world"))

    def test_parse_alarm_text(self):
        msg = 'ALARM: "High CPU on i-0abc1230" in ap-southeast-1'
        alert = self.parser.parse(msg, channel_id="C123")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.provider, "cloudwatch")
        self.assertIn("High CPU", alert.title)
        self.assertEqual(alert.region, "ap-southeast-1")
        self.assertEqual(alert.resource_hint, "i-0abc1230")  # 8+ hex chars
        self.assertEqual(alert.channel_id, "C123")

    def test_parse_json_payload(self):
        payload = json.dumps({
            "AlarmName": "RDS-HighConnections",
            "Region": "us-west-2",
            "AlarmDescription": "DB connections above 100",
            "NewStateValue": "ALARM",
        })
        alert = self.parser.parse(payload)
        self.assertIsNotNone(alert)
        self.assertIn("RDS-HighConnections", alert.title)
        self.assertEqual(alert.region, "us-west-2")

    def test_parse_json_ok_state(self):
        payload = json.dumps({
            "AlarmName": "HighCPU",
            "NewStateValue": "OK",
        })
        alert = self.parser.parse(payload)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "low")

    def test_parse_critical_keyword(self):
        msg = 'ALARM: "CRITICAL-DiskFull on i-abc" in us-east-1'
        alert = self.parser.parse(msg)
        self.assertEqual(alert.severity, "critical")

    def test_parse_extracts_arn(self):
        payload = json.dumps({
            "AlarmName": "LambdaErrors",
            "Region": "us-east-1",
            "NewStateValue": "ALARM",
            "Trigger": {"Dimensions": [{"value": "arn:aws:lambda:us-east-1:123456:function:myFunc"}]},
        })
        alert = self.parser.parse(payload)
        self.assertIsNotNone(alert)


# =====================================================================
# 4. Datadog Parser
# =====================================================================

class TestDatadogParser(unittest.TestCase):
    """Test Datadog alert parser."""

    def setUp(self):
        self.parser = DatadogAlertParser()

    def test_can_parse_triggered(self):
        self.assertTrue(self.parser.can_parse("[Triggered] High CPU on web-01"))

    def test_can_parse_keyword(self):
        self.assertTrue(self.parser.can_parse("Datadog monitor triggered"))

    def test_cannot_parse_unrelated(self):
        self.assertFalse(self.parser.can_parse("All systems nominal"))

    def test_parse_triggered(self):
        alert = self.parser.parse("[Triggered] High CPU on web-01 host:web-01.prod")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "high")
        self.assertIn("High CPU", alert.title)
        self.assertEqual(alert.resource_hint, "web-01.prod")

    def test_parse_warn(self):
        alert = self.parser.parse("[Warn] Disk usage above 80%")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "medium")

    def test_parse_recovered(self):
        alert = self.parser.parse("[Recovered] CPU back to normal")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "low")


# =====================================================================
# 5. PagerDuty Parser
# =====================================================================

class TestPagerDutyParser(unittest.TestCase):
    """Test PagerDuty alert parser."""

    def setUp(self):
        self.parser = PagerDutyAlertParser()

    def test_can_parse_pagerduty_keyword(self):
        self.assertTrue(self.parser.can_parse("PagerDuty incident triggered"))

    def test_can_parse_with_service(self):
        self.assertTrue(self.parser.can_parse(
            "Triggered: DB connection pool exhausted\nService: production-db\nUrgency: high"
        ))

    def test_parse_triggered_with_urgency(self):
        msg = "Triggered: DB down\nService: prod-db\nUrgency: high"
        alert = self.parser.parse(msg, channel_id="C456")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "critical")  # high urgency → critical
        self.assertEqual(alert.resource_hint, "prod-db")

    def test_parse_acknowledged(self):
        msg = "PagerDuty\nAcknowledged: Server issue\nService: web"
        alert = self.parser.parse(msg)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "medium")

    def test_parse_resolved(self):
        msg = "PagerDuty\nResolved: Issue fixed\nService: api"
        alert = self.parser.parse(msg)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "low")


# =====================================================================
# 6. Grafana Parser
# =====================================================================

class TestGrafanaParser(unittest.TestCase):
    """Test Grafana alert parser."""

    def setUp(self):
        self.parser = GrafanaAlertParser()

    def test_can_parse_alerting(self):
        self.assertTrue(self.parser.can_parse("[Alerting] High memory usage"))

    def test_can_parse_keyword(self):
        self.assertTrue(self.parser.can_parse("Grafana alerting: CPU spike"))

    def test_cannot_parse_unrelated(self):
        self.assertFalse(self.parser.can_parse("Weekly report"))

    def test_parse_alerting(self):
        msg = "[Alerting] Node memory > 90%"
        alert = self.parser.parse(msg)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "high")

    def test_parse_alerting_with_dashboard_url(self):
        msg = "[Alerting] Node memory > 90% https://monitoring.grafana.example.com/d/abc123"
        alert = self.parser.parse(msg)
        self.assertIsNotNone(alert)
        self.assertIn("dashboard_url", alert.tags)

    def test_parse_ok(self):
        alert = self.parser.parse("[OK] CPU back to normal")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "low")

    def test_parse_no_data(self):
        alert = self.parser.parse("[No Data] Disk metrics missing")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "medium")


# =====================================================================
# 7. Generic Parser
# =====================================================================

class TestGenericParser(unittest.TestCase):
    """Test generic fallback parser."""

    def setUp(self):
        self.parser = GenericAlertParser()

    def test_can_parse_alert_keywords(self):
        self.assertTrue(self.parser.can_parse("Server down"))
        self.assertTrue(self.parser.can_parse("Critical error in production"))
        self.assertTrue(self.parser.can_parse("Warning: disk space low"))

    def test_cannot_parse_no_keywords(self):
        self.assertFalse(self.parser.can_parse("Meeting at 3pm"))

    def test_parse_critical(self):
        alert = self.parser.parse("CRITICAL: Database unreachable")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "critical")

    def test_parse_error(self):
        alert = self.parser.parse("Application failure detected on i-0abc123def")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "high")
        self.assertEqual(alert.resource_hint, "i-0abc123def")

    def test_parse_warning(self):
        alert = self.parser.parse("Warning: Memory usage increasing")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "medium")

    def test_parse_low(self):
        alert = self.parser.parse("Alert: Deployment completed successfully")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "low")

    def test_parse_extracts_pod(self):
        alert = self.parser.parse("crash loop detected on pod/web-frontend-abc123")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.resource_hint, "pod/web-frontend-abc123")


# =====================================================================
# 8. AlertIngressService
# =====================================================================

class TestAlertIngressService(unittest.TestCase):
    """Test AlertIngressService end-to-end."""

    def setUp(self):
        self.service = AlertIngressService()

    def test_parse_routes_to_correct_parser(self):
        # CloudWatch
        alert = self.service.parse_channel_message(
            "C1", 'ALARM: "HighCPU" in us-east-1'
        )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.provider, "cloudwatch")

        # Datadog
        alert = self.service.parse_channel_message("C1", "[Triggered] CPU spike host:web-01")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.provider, "datadog")

        # Grafana
        alert = self.service.parse_channel_message("C1", "[Alerting] Memory high")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.provider, "grafana")

    def test_parse_no_match(self):
        alert = self.service.parse_channel_message("C1", "Good morning team")
        self.assertIsNone(alert)

    def test_dedup_blocks_repeated(self):
        alert = StructuredAlert(
            source="channel", title="test", alert_id="dedup-001"
        )
        self.assertFalse(self.service.is_duplicate(alert))
        self.assertTrue(self.service.is_duplicate(alert))

    def test_dedup_allows_after_window(self):
        alert = StructuredAlert(
            source="channel", title="test", alert_id="dedup-002"
        )
        self.assertFalse(self.service.is_duplicate(alert))
        # Manually expire
        self.service._seen["dedup-002"] = datetime.now(timezone.utc) - timedelta(seconds=400)
        self.assertFalse(self.service.is_duplicate(alert, window_seconds=300))

    def test_dedup_lru_eviction(self):
        """Dedup cache should not grow beyond limit."""
        service = AlertIngressService()
        for i in range(1100):
            alert = StructuredAlert(
                source="channel", title=f"alert-{i}", alert_id=f"id-{i}"
            )
            service.is_duplicate(alert)
        self.assertLessEqual(len(service._seen), 1000)

    def test_parser_priority_order(self):
        """Specific parsers should be tried before generic."""
        parser_types = [type(p).__name__ for p in ALL_PARSERS]
        self.assertEqual(parser_types[-1], "GenericAlertParser")
        self.assertIn("CloudWatchAlertParser", parser_types[:4])


if __name__ == "__main__":
    unittest.main()
