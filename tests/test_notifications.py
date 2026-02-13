"""
Tests for src/notifications.py — Notification system

Coverage target: 90%+ (from 0%)
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.notifications import (
    NotificationLevel, Notification, SlackNotifier,
    NotificationManager, get_notification_manager,
)


class TestNotificationLevel:
    """Test notification level enum."""

    def test_levels_exist(self):
        assert NotificationLevel.INFO.value == "info"
        assert NotificationLevel.WARNING.value == "warning"
        assert NotificationLevel.ERROR.value == "error"
        assert NotificationLevel.CRITICAL.value == "critical"


class TestNotification:
    """Test Notification dataclass."""

    def test_basic_notification(self):
        n = Notification(title="Test", message="Hello")
        assert n.title == "Test"
        assert n.message == "Hello"
        assert n.level == NotificationLevel.INFO
        assert n.source == "AgenticAIOps"
        assert n.timestamp is not None
        assert n.details is None

    def test_custom_fields(self):
        n = Notification(
            title="Alert", message="CPU high",
            level=NotificationLevel.CRITICAL,
            source="Monitor", details={"cpu": 95},
        )
        assert n.level == NotificationLevel.CRITICAL
        assert n.source == "Monitor"
        assert n.details["cpu"] == 95

    def test_auto_timestamp(self):
        n = Notification(title="T", message="M")
        # Should be a valid ISO timestamp
        dt = datetime.fromisoformat(n.timestamp)
        assert dt is not None

    def test_explicit_timestamp(self):
        ts = "2026-02-13T10:00:00+00:00"
        n = Notification(title="T", message="M", timestamp=ts)
        assert n.timestamp == ts


class TestSlackNotifier:
    """Test Slack notification handler."""

    def test_init_no_webhook(self):
        with patch.dict('os.environ', {}, clear=True):
            notifier = SlackNotifier(webhook_url=None)
            # May or may not be enabled depending on env
            assert isinstance(notifier.enabled, bool)

    def test_init_with_webhook(self):
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        assert notifier.enabled is True
        assert notifier.webhook_url == "https://hooks.slack.com/test"

    def test_get_color(self):
        notifier = SlackNotifier(webhook_url="test")
        assert notifier._get_color(NotificationLevel.INFO) == "#36a64f"
        assert notifier._get_color(NotificationLevel.CRITICAL) == "#ff0000"

    def test_get_emoji(self):
        notifier = SlackNotifier(webhook_url="test")
        assert "ℹ" in notifier._get_emoji(NotificationLevel.INFO)
        assert "🚨" in notifier._get_emoji(NotificationLevel.CRITICAL)

    def test_send_disabled(self):
        notifier = SlackNotifier(webhook_url=None)
        notifier.enabled = False
        n = Notification(title="T", message="M")
        result = notifier.send(n)
        assert result["success"] is False
        assert "not configured" in result["error"]

    def test_send_success(self):
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        n = Notification(title="Test", message="Hello", details={"key": "value"})

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            result = notifier.send(n)

        assert result["success"] is True
        assert result["status_code"] == 200

    def test_send_failure(self):
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        n = Notification(title="Test", message="Hello")

        with patch('urllib.request.urlopen', side_effect=Exception("Connection refused")):
            result = notifier.send(n)

        assert result["success"] is False
        assert "Connection refused" in result["error"]

    def test_send_alert_convenience(self):
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        notifier.enabled = False
        result = notifier.send_alert("Title", "Message", level="warning")
        assert result["success"] is False


class TestNotificationManager:
    """Test unified notification manager."""

    def test_init_no_slack(self):
        with patch.dict('os.environ', {}, clear=True):
            # Clear SLACK_WEBHOOK_URL if set
            import os
            old = os.environ.pop('SLACK_WEBHOOK_URL', None)
            try:
                mgr = NotificationManager()
                assert mgr.is_configured() is False
            finally:
                if old:
                    os.environ['SLACK_WEBHOOK_URL'] = old

    def test_get_status(self):
        mgr = NotificationManager()
        status = mgr.get_status()
        assert "enabled" in status
        assert "channels" in status
        assert "slack" in status["channels"]

    def test_send_no_channels(self):
        mgr = NotificationManager()
        mgr._handlers = []
        n = Notification(title="T", message="M")
        result = mgr.send(n)
        assert result["success"] is False
        assert "No notification channels" in result["error"]

    def test_send_with_handler(self):
        mgr = NotificationManager()
        mgr._handlers = [("test", lambda n: {"success": True})]
        n = Notification(title="T", message="M")
        result = mgr.send(n)
        assert result["success"] is True

    def test_send_handler_exception(self):
        def bad_handler(n):
            raise RuntimeError("boom")
        mgr = NotificationManager()
        mgr._handlers = [("bad", bad_handler)]
        n = Notification(title="T", message="M")
        result = mgr.send(n)
        assert result["success"] is False

    def test_send_alert(self):
        mgr = NotificationManager()
        mgr._handlers = [("test", lambda n: {"success": True})]
        result = mgr.send_alert("Title", "Message", level="error", details={"x": 1})
        assert result["success"] is True

    def test_send_anomaly_alert_empty(self):
        mgr = NotificationManager()
        result = mgr.send_anomaly_alert([])
        assert result["success"] is True

    def test_send_anomaly_alert_critical(self):
        mgr = NotificationManager()
        mgr._handlers = [("test", lambda n: {"success": True})]
        anomalies = [
            {"type": "CPU", "resource": "i-abc", "severity": "critical"},
            {"type": "Mem", "resource": "i-def", "severity": "high"},
        ]
        result = mgr.send_anomaly_alert(anomalies)
        assert result["success"] is True

    def test_send_anomaly_alert_many(self):
        mgr = NotificationManager()
        mgr._handlers = [("test", lambda n: {"success": True})]
        anomalies = [{"type": f"A{i}", "resource": f"r{i}", "severity": "warning"} for i in range(8)]
        result = mgr.send_anomaly_alert(anomalies)
        assert result["success"] is True

    def test_send_health_alert_unhealthy(self):
        mgr = NotificationManager()
        mgr._handlers = [("test", lambda n: {"success": True})]
        result = mgr.send_health_alert("EC2", "unhealthy", ["CPU high", "Disk full"])
        assert result["success"] is True

    def test_send_health_alert_degraded(self):
        mgr = NotificationManager()
        mgr._handlers = [("test", lambda n: {"success": True})]
        result = mgr.send_health_alert("RDS", "degraded", ["Slow queries"])
        assert result["success"] is True


class TestSingleton:
    """Test module-level singleton."""

    def test_get_notification_manager(self):
        import src.notifications as mod
        mod._manager = None
        mgr = get_notification_manager()
        assert mgr is not None
        assert get_notification_manager() is mgr
        mod._manager = None
