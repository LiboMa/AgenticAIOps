"""AlertParser ABC — base class for all channel alert parsers.

Design: ADR-009 §3.3
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import StructuredAlert


class AlertParser(ABC):
    """Base class for channel alert parsers.

    Each monitoring system (CloudWatch, Datadog, PagerDuty, Grafana) has a
    specific message format when posting to Slack. Parsers extract structured
    alert data from these messages.
    """

    provider: str = "unknown"

    @abstractmethod
    def can_parse(self, message: str) -> bool:
        """Check if this parser can handle the given message.

        Args:
            message: Raw Slack message text.

        Returns:
            True if this parser recognizes the message format.
        """
        ...

    @abstractmethod
    def parse(self, message: str, channel_id: str = "") -> Optional[StructuredAlert]:
        """Parse a channel message into a StructuredAlert.

        Args:
            message: Raw Slack message text.
            channel_id: Slack channel ID where the message was received.

        Returns:
            StructuredAlert if parsing succeeds, None otherwise.
        """
        ...
