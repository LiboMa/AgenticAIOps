"""Generic alert parser — LLM-assisted fallback for unrecognized formats.

This parser always returns True from can_parse() and attempts to extract
structured alert data from any message using heuristics. Falls back to
treating the entire message as a low-severity alert.

In Phase 2, this can be enhanced with LLM-based extraction.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .base import AlertParser
from ..models import StructuredAlert, normalize_severity

logger = logging.getLogger(__name__)

# Common alert keywords
_ALERT_KEYWORDS = re.compile(
    r'\b(alert|alarm|error|critical|warning|incident|outage|down|failure|failed|crash)\b',
    re.IGNORECASE,
)

# Resource patterns (reused)
_RESOURCE_PATTERNS = [
    re.compile(r'(i-[0-9a-f]{8,17})'),
    re.compile(r'(arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d+:.+?)[\s,\]]'),
    re.compile(r'(pod/[\w.-]+)'),
    re.compile(r'(db-[A-Z0-9]+)'),
]


class GenericAlertParser(AlertParser):
    """Fallback parser for unrecognized alert formats.

    Always matches (lowest priority in parser chain).
    Uses heuristics to extract what it can.
    """

    provider = "generic"

    def can_parse(self, message: str) -> bool:
        """Always returns True — this is the fallback parser."""
        return bool(_ALERT_KEYWORDS.search(message))

    def parse(self, message: str, channel_id: str = "") -> Optional[StructuredAlert]:
        try:
            # Infer severity from keywords
            lower = message.lower()
            if any(kw in lower for kw in ["critical", "emergency", "fatal", "p1"]):
                severity = "critical"
            elif any(kw in lower for kw in ["error", "failure", "failed", "down", "outage"]):
                severity = "high"
            elif any(kw in lower for kw in ["warning", "warn"]):
                severity = "medium"
            else:
                severity = "low"

            # Extract resource
            resource = ""
            for pattern in _RESOURCE_PATTERNS:
                match = pattern.search(message)
                if match:
                    resource = match.group(1)
                    break

            # Title: first line or first 100 chars
            title = message.split("\n")[0][:100].strip()

            return StructuredAlert(
                source="channel",
                provider=self.provider,
                severity=severity,
                title=title,
                description=message,
                resource_hint=resource,
                channel_id=channel_id,
                raw_data={"raw_message": message},
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.warning("Generic parser failed: %s", e)
            return None
