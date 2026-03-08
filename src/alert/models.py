"""StructuredAlert — unified alert model for all ingestion sources.

Design: ADR-009 §3.1
Reference: agenticops-chat AlertPayload + severity normalization
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── Severity normalization ──────────────────────────────────────────
# Directly adapted from agenticops-chat/src/agenticops/integrations/parsers.py

_SEVERITY_MAP: dict[str, str] = {
    # Canonical
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    # Datadog / PagerDuty / Grafana variants
    "error": "high",
    "warning": "medium",
    "warn": "medium",
    "info": "low",
    "informational": "low",
    "normal": "low",
    "urgent": "critical",
    "fatal": "critical",
    "emergency": "critical",
    "emerg": "critical",
    "alert": "high",
    "notice": "low",
    "debug": "low",
    # PagerDuty priority levels
    "p1": "critical",
    "p2": "high",
    "p3": "medium",
    "p4": "low",
    "p5": "low",
}


def normalize_severity(severity: str) -> str:
    """Map arbitrary severity string to canonical: critical, high, medium, low.

    Case-insensitive. Returns 'medium' for unrecognized values.
    """
    if not severity:
        return "medium"
    return _SEVERITY_MAP.get(severity.strip().lower(), "medium")


# ── StructuredAlert ─────────────────────────────────────────────────

class StructuredAlert(BaseModel):
    """Unified alert model — all ingestion paths normalize to this.

    Extends agenticops-chat's AlertPayload with:
    - Pydantic validation
    - Channel source metadata
    - Resource type classification
    - Dedup via alert_id
    """

    # Source
    source: Literal["channel", "eventbridge", "cloudtrail", "webhook", "manual"]
    provider: str = ""  # cloudwatch, datadog, pagerduty, grafana, generic

    # Alert content
    alert_id: str = ""  # Dedup key; auto-generated from title+resource if empty
    severity: str = "medium"  # Normalized by validator
    title: str
    description: str = ""

    # Resource identification
    resource_hint: str = ""  # i-xxx, arn:..., pod/name
    resource_type: str = ""  # ec2, pod, rds, lambda, node, service
    region: str = ""

    # Metadata
    tags: dict[str, str] = Field(default_factory=dict)
    raw_data: dict = Field(default_factory=dict)

    # Channel source (populated when source="channel")
    channel_id: Optional[str] = None
    message_id: Optional[str] = None

    # Timestamps
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, v: str) -> str:
        return normalize_severity(v)

    def model_post_init(self, __context) -> None:
        """Auto-generate alert_id if not provided."""
        if not self.alert_id:
            raw = f"{self.provider}:{self.title}:{self.resource_hint}"
            self.alert_id = hashlib.sha256(raw.encode()).hexdigest()[:16]
