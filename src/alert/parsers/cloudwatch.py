"""CloudWatch alert parser — handles SNS-to-Slack alert messages.

Recognizes patterns:
- "ALARM: <name> in <region>"
- JSON payloads from CloudWatch → SNS → Slack integration
- CloudWatch Alarm state change notifications
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .base import AlertParser
from ..models import StructuredAlert, normalize_severity

logger = logging.getLogger(__name__)

# CloudWatch ALARM pattern: "ALARM: "High CPU on i-0abc" in AP-Southeast-1"
_ALARM_PATTERN = re.compile(
    r'ALARM:\s*"?(?P<name>[^"]+)"?\s+in\s+(?P<region>[\w-]+)',
    re.IGNORECASE,
)

# State transition: "State changed to ALARM"
_STATE_PATTERN = re.compile(
    r'State\s+changed\s+to\s+(?P<state>ALARM|OK|INSUFFICIENT_DATA)',
    re.IGNORECASE,
)

# Resource ID patterns
_RESOURCE_PATTERNS = [
    re.compile(r'(i-[0-9a-f]{8,17})'),                    # EC2 instance
    re.compile(r'(arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d+:.+)'),  # ARN
    re.compile(r'(pod/[\w.-]+)'),                           # K8s pod
    re.compile(r'(db-[A-Z0-9]+)'),                          # RDS
]

# Severity from alarm name heuristics
_SEVERITY_KEYWORDS = {
    "critical": ["critical", "emergency", "fatal", "p1"],
    "high": ["high", "error", "p2", "severe"],
    "medium": ["warning", "warn", "p3"],
    "low": ["info", "notice", "p4", "p5"],
}


def _infer_severity(alarm_name: str, description: str = "") -> str:
    """Infer severity from alarm name and description keywords."""
    text = f"{alarm_name} {description}".lower()
    for severity, keywords in _SEVERITY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return severity
    return "medium"


def _extract_resource(text: str) -> str:
    """Extract resource ID from message text."""
    for pattern in _RESOURCE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


class CloudWatchAlertParser(AlertParser):
    """Parse CloudWatch alarm notifications from Slack messages."""

    provider = "cloudwatch"

    def can_parse(self, message: str) -> bool:
        """Recognize CloudWatch alarm messages."""
        if _ALARM_PATTERN.search(message):
            return True
        # JSON payload from SNS
        try:
            data = json.loads(message)
            return data.get("AlarmName") is not None or data.get("source") == "aws.cloudwatch"
        except (json.JSONDecodeError, AttributeError):
            pass
        # Keywords
        return "cloudwatch" in message.lower() and (
            "alarm" in message.lower() or "state changed" in message.lower()
        )

    def parse(self, message: str, channel_id: str = "") -> Optional[StructuredAlert]:
        """Parse CloudWatch alarm message into StructuredAlert."""
        try:
            return self._parse_json(message, channel_id) or self._parse_text(message, channel_id)
        except Exception as e:
            logger.warning("CloudWatch parser failed: %s", e)
            return None

    def _parse_json(self, message: str, channel_id: str) -> Optional[StructuredAlert]:
        """Try parsing as JSON (SNS payload)."""
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return None

        alarm_name = data.get("AlarmName", "")
        if not alarm_name:
            return None

        region = data.get("Region", data.get("region", ""))
        description = data.get("AlarmDescription", data.get("NewStateReason", ""))
        state = data.get("NewStateValue", "ALARM")

        severity = "low" if state == "OK" else _infer_severity(alarm_name, description)

        return StructuredAlert(
            source="channel",
            provider=self.provider,
            severity=severity,
            title=f"CloudWatch: {alarm_name}",
            description=description,
            resource_hint=_extract_resource(str(data)),
            region=region,
            channel_id=channel_id,
            raw_data=data,
            timestamp=datetime.now(timezone.utc),
        )

    def _parse_text(self, message: str, channel_id: str) -> Optional[StructuredAlert]:
        """Parse text-format alarm message."""
        match = _ALARM_PATTERN.search(message)
        if not match:
            return None

        alarm_name = match.group("name").strip()
        region = match.group("region").strip()

        return StructuredAlert(
            source="channel",
            provider=self.provider,
            severity=_infer_severity(alarm_name, message),
            title=f"CloudWatch: {alarm_name}",
            description=message,
            resource_hint=_extract_resource(message),
            region=region,
            channel_id=channel_id,
            raw_data={"raw_message": message},
            timestamp=datetime.now(timezone.utc),
        )
