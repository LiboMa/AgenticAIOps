"""Tests for notifications — Notification, SlackNotifier, NotificationManager."""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.notifications import (
    Notification,
    NotificationLevel,
    SlackNotifier,
    NotificationManager,
    get_notification_manager,
)


class TestNotification:

    def test_defaults(self):
        n = Notification(title="Test", message="Hello")
        assert n.level == NotificationLevel.INFO
        assert n.source == "AgenticAIOps"
        assert n.timestamp is not None

    def test_custom_level(self):
        n = Notification(title="Alert", message="Bad", level=NotificationLevel.CRITICAL)
        assert n.level == NotificationLevel.CRITICAL


class TestSlackNotifier:

    def test_disabled_without_url(self):
        with patch.dict(os.environ, {}, clear=True):
            notifier = SlackNotifier(webhook_url=None)
        assert notifier.enabled is False

    def test_enabled_with_url(self):
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        assert notifier.enabled is True

    def test_send_disabled(self):
        notifier = SlackNotifier(webhook_url=None)
        notifier.enabled = False
        result = notifier.send(Notification(title="T", message="M"))
        assert result["success"] is False
        assert "not configured" in result["error"]

    def test_send_success(self):
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = notifier.send(Notification(title="T", message="M"))
        assert result["success"] is True

    def test_send_with_details(self):
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = notifier.send(Notification(
                title="T", message="M",
                details={"key1": "val1", "key2": "val2"}
            ))
        assert result["success"] is True

    def test_send_network_error(self):
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            result = notifier.send(Notification(title="T", message="M"))
        assert result["success"] is False

    def test_get_color(self):
        notifier = SlackNotifier()
        assert notifier._get_color(NotificationLevel.CRITICAL) == "#ff0000"
        assert notifier._get_color(NotificationLevel.INFO) == "#36a64f"

    def test_get_emoji(self):
        notifier = SlackNotifier()
        assert "🚨" in notifier._get_emoji(NotificationLevel.CRITICAL)
        assert "ℹ" in notifier._get_emoji(NotificationLevel.INFO)

    def test_send_alert_convenience(self):
        notifier = SlackNotifier(webhook_url=None)
        notifier.enabled = False
        result = notifier.send_alert("Title", "Msg", level="warning")
        assert result["success"] is False


class TestNotificationManager:

    def test_no_channels_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            mgr = NotificationManager()
        assert mgr.is_configured() is False

    def test_get_status(self):
        with patch.dict(os.environ, {}, clear=True):
            mgr = NotificationManager()
        status = mgr.get_status()
        assert "enabled" in status
        assert "channels" in status

    def test_send_no_channels(self):
        with patch.dict(os.environ, {}, clear=True):
            mgr = NotificationManager()
        result = mgr.send(Notification(title="T", message="M"))
        assert result["success"] is False
        assert "No notification channels" in result["error"]

    def test_send_with_slack(self):
        mgr = NotificationManager()
        mgr.slack = MagicMock()
        mgr.slack.enabled = True
        mgr.slack.send.return_value = {"success": True}
        mgr._handlers = [("slack", mgr.slack.send)]

        result = mgr.send(Notification(title="T", message="M"))
        assert result["success"] is True

    def test_send_alert(self):
        with patch.dict(os.environ, {}, clear=True):
            mgr = NotificationManager()
        result = mgr.send_alert("Title", "Msg", level="error")
        assert result["success"] is False

    def test_send_anomaly_alert_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            mgr = NotificationManager()
        result = mgr.send_anomaly_alert([])
        assert result["success"] is True

    def test_send_anomaly_alert_with_data(self):
        mgr = NotificationManager()
        mgr._handlers = [("slack", MagicMock(return_value={"success": True}))]

        anomalies = [
            {"type": "cpu", "resource": "i-123", "severity": "critical"},
            {"type": "mem", "resource": "i-456", "severity": "high"},
        ]
        result = mgr.send_anomaly_alert(anomalies)
        assert result["success"] is True

    def test_send_anomaly_alert_many(self):
        mgr = NotificationManager()
        mgr._handlers = [("slack", MagicMock(return_value={"success": True}))]

        anomalies = [{"type": f"t{i}", "resource": f"r{i}", "severity": "warning"} for i in range(10)]
        result = mgr.send_anomaly_alert(anomalies)
        assert result["success"] is True

    def test_send_health_alert(self):
        mgr = NotificationManager()
        mgr._handlers = [("slack", MagicMock(return_value={"success": True}))]

        result = mgr.send_health_alert("EC2", "unhealthy", ["Instance unreachable"])
        assert result["success"] is True

    def test_handler_exception_caught(self):
        mgr = NotificationManager()
        mgr._handlers = [("slack", MagicMock(side_effect=RuntimeError("boom")))]

        result = mgr.send(Notification(title="T", message="M"))
        assert result["channels"]["slack"]["success"] is False


class TestSingleton:

    def test_get_notification_manager(self):
        import src.notifications as mod
        old = mod._manager
        mod._manager = None

        with patch.dict(os.environ, {}, clear=True):
            m1 = get_notification_manager()
            m2 = get_notification_manager()
        assert m1 is m2

        mod._manager = old
