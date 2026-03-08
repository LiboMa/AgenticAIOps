"""AlertIngressService — unified alert ingestion from all sources.

Handles:
1. Channel messages → parse → StructuredAlert → DetectResult → RCA
2. EventBridge/CloudTrail events → StructuredAlert → existing pipeline

Design: ADR-009 §3.2
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional, List

from .models import StructuredAlert
from .parsers import ALL_PARSERS, AlertParser

logger = logging.getLogger(__name__)

# Dedup cache: alert_id → timestamp (LRU, max 1000)
_DEDUP_MAX = 1000


class AlertIngressService:
    """Unified alert ingestion — Channel + Events Driven.

    Usage::

        service = AlertIngressService()
        # From channel message:
        alert = service.parse_channel_message(channel_id, message_text)
        if alert:
            detect_result = await service.process(alert, detect_agent)

        # From EventBridge/webhook:
        alert = StructuredAlert(source="eventbridge", ...)
        detect_result = await service.process(alert, detect_agent)
    """

    def __init__(self, parsers: Optional[List[AlertParser]] = None):
        self.parsers = parsers or ALL_PARSERS
        self._seen: OrderedDict[str, datetime] = OrderedDict()

    def parse_channel_message(
        self, channel_id: str, message: str
    ) -> Optional[StructuredAlert]:
        """Try all parsers in priority order to extract an alert.

        Args:
            channel_id: Source channel ID.
            message: Raw message text.

        Returns:
            StructuredAlert if any parser succeeds, None if no parser matches.
        """
        for parser in self.parsers:
            if parser.can_parse(message):
                alert = parser.parse(message, channel_id=channel_id)
                if alert is not None:
                    logger.info(
                        "Alert parsed by %s: %s (severity=%s)",
                        parser.provider,
                        alert.title,
                        alert.severity,
                    )
                    return alert
        return None

    def is_duplicate(self, alert: StructuredAlert, window_seconds: int = 300) -> bool:
        """Check if alert_id was seen within the dedup window.

        Args:
            alert: The alert to check.
            window_seconds: Dedup window in seconds (default 5 min).

        Returns:
            True if duplicate (should skip).
        """
        now = datetime.now(timezone.utc)
        last_seen = self._seen.get(alert.alert_id)
        if last_seen and (now - last_seen).total_seconds() < window_seconds:
            logger.debug("Duplicate alert suppressed: %s", alert.alert_id)
            return True

        # Record and maintain LRU size
        self._seen[alert.alert_id] = now
        self._seen.move_to_end(alert.alert_id)
        while len(self._seen) > _DEDUP_MAX:
            self._seen.popitem(last=False)

        return False

    async def process(self, alert: StructuredAlert, detect_agent) -> Optional[object]:
        """Process an alert through the detection pipeline.

        1. Dedup check
        2. Create DetectResult (with historical cases if KB available)
        3. Trigger RCA via detect_agent

        Args:
            alert: Parsed StructuredAlert.
            detect_agent: DetectAgent instance.

        Returns:
            DetectResult if processed, None if skipped (duplicate).
        """
        if self.is_duplicate(alert):
            return None

        logger.info(
            "Processing alert: %s [%s] from %s via %s",
            alert.title,
            alert.severity,
            alert.provider,
            alert.source,
        )

        # Create a DetectResult from the alert
        # Import here to avoid circular deps
        from src.detect_agent import DetectResult

        detect_result = DetectResult()
        detect_result.source = alert.source
        detect_result.severity = alert.severity
        detect_result.alert = alert

        # Trigger the detection/RCA pipeline
        await detect_agent.on_anomaly_detected(detect_result)
        return detect_result
