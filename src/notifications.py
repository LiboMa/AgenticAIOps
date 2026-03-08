"""
Notification Module - Alert notifications via Slack, Email, etc.

Provides unified notification interface for:
- Anomaly alerts
- Health check failures
- Security issues
- Custom notifications
"""

import os
import logging
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class NotificationLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Notification:
    """Notification data structure."""
    title: str
    message: str
    level: NotificationLevel = NotificationLevel.INFO
    source: str = "AgenticAIOps"
    timestamp: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class SlackNotifier:
    """
    Slack notification handler using webhooks.
    
    Set SLACK_WEBHOOK_URL environment variable to enable.
    """
    
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.environ.get('SLACK_WEBHOOK_URL')
        self.enabled = bool(self.webhook_url)
    
    def _get_color(self, level: NotificationLevel) -> str:
        """Get Slack attachment color based on level."""
        colors = {
            NotificationLevel.INFO: "#36a64f",      # Green
            NotificationLevel.WARNING: "#ffcc00",   # Yellow
            NotificationLevel.ERROR: "#ff6600",     # Orange
            NotificationLevel.CRITICAL: "#ff0000",  # Red
        }
        return colors.get(level, "#808080")
    
    def _get_emoji(self, level: NotificationLevel) -> str:
        """Get emoji based on level."""
        emojis = {
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "🔴",
            NotificationLevel.CRITICAL: "🚨",
        }
        return emojis.get(level, "📢")
    
    def send(self, notification: Notification) -> Dict[str, Any]:
        """Send notification to Slack."""
        if not self.enabled:
            return {"success": False, "error": "Slack webhook not configured"}
        
        try:
            import urllib.request
            
            emoji = self._get_emoji(notification.level)
            
            # Build Slack message
            payload = {
                "attachments": [
                    {
                        "color": self._get_color(notification.level),
                        "title": f"{emoji} {notification.title}",
                        "text": notification.message,
                        "footer": notification.source,
                        "ts": int(datetime.fromisoformat(notification.timestamp).timestamp()),
                        "fields": []
                    }
                ]
            }
            
            # Add details as fields
            if notification.details:
                for key, value in list(notification.details.items())[:5]:
                    payload["attachments"][0]["fields"].append({
                        "title": key,
                        "value": str(value)[:100],
                        "short": True
                    })
            
            # Send to Slack
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                return {"success": True, "status_code": response.status}
                
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return {"success": False, "error": str(e)}
    
    def send_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Convenience method to send an alert."""
        level_enum = NotificationLevel(level.lower()) if isinstance(level, str) else level
        notification = Notification(
            title=title,
            message=message,
            level=level_enum,
            details=details
        )
        return self.send(notification)


class NotificationManager:
    """
    Unified notification manager.
    
    Supports multiple notification channels.
    """
    
    def __init__(self):
        self.slack = SlackNotifier()
        self._handlers = []
        
        if self.slack.enabled:
            self._handlers.append(("slack", self.slack.send))
    
    def is_configured(self) -> bool:
        """Check if any notification channel is configured."""
        return len(self._handlers) > 0
    
    def get_status(self) -> Dict[str, Any]:
        """Get notification system status."""
        return {
            "enabled": self.is_configured(),
            "channels": {
                "slack": self.slack.enabled,
            },
        }
    
    def send(self, notification: Notification) -> Dict[str, Any]:
        """Send notification to all configured channels."""
        results = {}
        
        for name, handler in self._handlers:
            try:
                results[name] = handler(notification)
            except Exception as e:
                results[name] = {"success": False, "error": str(e)}
        
        if not results:
            return {"success": False, "error": "No notification channels configured"}
        
        return {
            "success": any(r.get("success") for r in results.values()),
            "channels": results,
        }
    
    def send_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send alert to all channels."""
        level_enum = NotificationLevel(level.lower()) if isinstance(level, str) else level
        notification = Notification(
            title=title,
            message=message,
            level=level_enum,
            details=details
        )
        return self.send(notification)
    
    def send_anomaly_alert(self, anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send anomaly detection alert."""
        if not anomalies:
            return {"success": True, "message": "No anomalies to report"}
        
        # Group by severity
        critical = [a for a in anomalies if a.get('severity') == 'critical']
        high = [a for a in anomalies if a.get('severity') == 'high']
        
        level = NotificationLevel.CRITICAL if critical else NotificationLevel.WARNING if high else NotificationLevel.INFO
        
        message = f"**{len(anomalies)} anomalies detected:**\n"
        for a in anomalies[:5]:
            message += f"• {a.get('type', 'Unknown')}: {a.get('resource', 'N/A')} ({a.get('severity', 'unknown')})\n"
        
        if len(anomalies) > 5:
            message += f"... and {len(anomalies) - 5} more"
        
        notification = Notification(
            title="AWS Anomaly Detection Alert",
            message=message,
            level=level,
            details={
                "Total Anomalies": len(anomalies),
                "Critical": len(critical),
                "High": len(high),
            }
        )
        
        return self.send(notification)
    
    def send_health_alert(self, service: str, status: str, issues: List[str]) -> Dict[str, Any]:
        """Send health check failure alert."""
        level = NotificationLevel.CRITICAL if status == "unhealthy" else NotificationLevel.WARNING
        
        message = f"**{service} Health Check: {status.upper()}**\n\n"
        message += "Issues found:\n"
        for issue in issues[:5]:
            message += f"• {issue}\n"
        
        notification = Notification(
            title=f"{service} Health Alert",
            message=message,
            level=level,
            details={
                "Service": service,
                "Status": status,
                "Issues Count": len(issues),
            }
        )
        
        return self.send(notification)


# Singleton instance
_manager: Optional[NotificationManager] = None


def get_notification_manager() -> NotificationManager:
    """Get or create notification manager instance."""
    global _manager
    if _manager is None:
        _manager = NotificationManager()
    return _manager
