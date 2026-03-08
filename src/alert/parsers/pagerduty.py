"""PagerDuty alert parser — handles PagerDuty Slack integration messages.

Recognizes patterns:
- PagerDuty incident triggers/resolves
- Service name + urgency
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .base import AlertParser
from ..models import StructuredAlert, normalize_severity

logger = logging.getLogger(__name__)

_PD_PATTERN = re.compile(
    r'(?P<action>Triggered|Acknowledged|Resolved)\s*:?\s*(?P<title>.+)',
    re.IGNORECASE,
)

_SERVICE_PATTERN = re.compile(r'Service:\s*(?P<service>.+)', re.IGNORECASE)
_URGENCY_PATTERN = re.compile(r'Urgency:\s*(?P<urgency>\w+)', re.IGNORECASE)

_URGENCY_TO_SEVERITY = {
    "high": "critical",
    "low": "low",
}

_ACTION_TO_SEVERITY = {
    "triggered": "high",
    "acknowledged": "medium",
    "resolved": "low",
}


class PagerDutyAlertParser(AlertParser):
    """Parse PagerDuty incident notifications from Slack messages."""

    provider = "pagerduty"

    def can_parse(self, message: str) -> bool:
        lower = message.lower()
        return "pagerduty" in lower or (
            _PD_PATTERN.search(message) is not None
            and any(kw in lower for kw in ["incident", "service", "urgency"])
        )

    def parse(self, message: str, channel_id: str = "") -> Optional[StructuredAlert]:
        try:
            match = _PD_PATTERN.search(message)
            if match:
                action = match.group("action").lower()
                title = match.group("title").strip()
            else:
                title = message[:100]
                action = "triggered"

            # Urgency overrides action-based severity
            urgency_match = _URGENCY_PATTERN.search(message)
            if urgency_match:
                urgency = urgency_match.group("urgency").lower()
                severity = _URGENCY_TO_SEVERITY.get(urgency, _ACTION_TO_SEVERITY.get(action, "medium"))
            else:
                severity = _ACTION_TO_SEVERITY.get(action, "medium")

            # Service name
            service_match = _SERVICE_PATTERN.search(message)
            resource = service_match.group("service").strip() if service_match else ""

            return StructuredAlert(
                source="channel",
                provider=self.provider,
                severity=severity,
                title=f"PagerDuty: {title}",
                description=message,
                resource_hint=resource,
                channel_id=channel_id,
                raw_data={"raw_message": message},
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.warning("PagerDuty parser failed: %s", e)
            return None
