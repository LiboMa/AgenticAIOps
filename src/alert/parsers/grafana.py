"""Grafana alert parser — handles Grafana Slack integration messages.

Recognizes patterns:
- "[Alerting]" / "[OK]" state prefixes
- Grafana rule name + dashboard link
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .base import AlertParser
from ..models import StructuredAlert

logger = logging.getLogger(__name__)

_GRAFANA_PATTERN = re.compile(
    r'\[(?P<state>Alerting|OK|No Data|Pending)\]\s*(?P<title>.+)',
    re.IGNORECASE,
)

_STATE_TO_SEVERITY = {
    "alerting": "high",
    "no data": "medium",
    "pending": "low",
    "ok": "low",
}


class GrafanaAlertParser(AlertParser):
    """Parse Grafana alert notifications from Slack messages."""

    provider = "grafana"

    def can_parse(self, message: str) -> bool:
        if _GRAFANA_PATTERN.search(message):
            return True
        lower = message.lower()
        return "grafana" in lower and ("alerting" in lower or "firing" in lower)

    def parse(self, message: str, channel_id: str = "") -> Optional[StructuredAlert]:
        try:
            match = _GRAFANA_PATTERN.search(message)
            if match:
                state = match.group("state").lower()
                title = match.group("title").strip()
                severity = _STATE_TO_SEVERITY.get(state, "medium")
            else:
                title = "Grafana Alert"
                severity = "medium"

            # Extract dashboard link (strip Slack angle brackets <url>)
            link_match = re.search(r'(https?://[^\s<>]+grafana[^\s<>]*)', message)
            tags = {}
            if link_match:
                tags["dashboard_url"] = link_match.group(1)

            return StructuredAlert(
                source="channel",
                provider=self.provider,
                severity=severity,
                title=f"Grafana: {title}",
                description=message,
                channel_id=channel_id,
                tags=tags,
                raw_data={"raw_message": message},
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.warning("Grafana parser failed: %s", e)
            return None
