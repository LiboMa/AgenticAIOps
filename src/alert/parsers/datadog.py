"""Datadog alert parser — handles Datadog Slack integration messages.

Recognizes patterns:
- Datadog bot messages with severity badges
- "[Triggered]" / "[Recovered]" prefixes
- Monitor name + resource tags
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .base import AlertParser
from ..models import StructuredAlert, normalize_severity

logger = logging.getLogger(__name__)

# Datadog patterns
_TRIGGERED_PATTERN = re.compile(
    r'\[(?P<state>Triggered|Recovered|Warn|No Data)\]\s*(?P<title>.+)',
    re.IGNORECASE,
)

_MONITOR_PATTERN = re.compile(r'Monitor:\s*(?P<name>.+)', re.IGNORECASE)

_STATE_TO_SEVERITY = {
    "triggered": "high",
    "warn": "medium",
    "recovered": "low",
    "no data": "medium",
}


class DatadogAlertParser(AlertParser):
    """Parse Datadog monitor notifications from Slack messages."""

    provider = "datadog"

    def can_parse(self, message: str) -> bool:
        if _TRIGGERED_PATTERN.search(message):
            return True
        lower = message.lower()
        return "datadog" in lower and ("triggered" in lower or "monitor" in lower)

    def parse(self, message: str, channel_id: str = "") -> Optional[StructuredAlert]:
        try:
            match = _TRIGGERED_PATTERN.search(message)
            if match:
                state = match.group("state").lower()
                title = match.group("title").strip()
                severity = _STATE_TO_SEVERITY.get(state, "medium")
            else:
                monitor_match = _MONITOR_PATTERN.search(message)
                title = monitor_match.group("name").strip() if monitor_match else "Datadog Alert"
                severity = "medium"

            # Extract host/resource from tags
            resource = ""
            host_match = re.search(r'host:(\S+)', message)
            if host_match:
                resource = host_match.group(1)

            return StructuredAlert(
                source="channel",
                provider=self.provider,
                severity=severity,
                title=f"Datadog: {title}",
                description=message,
                resource_hint=resource,
                channel_id=channel_id,
                raw_data={"raw_message": message},
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.warning("Datadog parser failed: %s", e)
            return None
