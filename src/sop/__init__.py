"""SOP models and lifecycle management.

Design: ADR-009 §9.4 — SOPDocument + lifecycle
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SOPStep(BaseModel):
    """Single step in a diagnostic or remediation plan."""

    order: int
    description: str
    command: Optional[str] = None
    expected_output: Optional[str] = None
    skill_tool: Optional[str] = None  # e.g. "kubernetes.get_pod_logs"


class RemediationPlan(BaseModel):
    """A remediation plan within an SOP."""

    name: str  # e.g. "Quick Fix", "Root Cause Fix"
    steps: list[SOPStep]
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_approval: bool = False


class SOPDocument(BaseModel):
    """Standardized SOP document — Harness output must conform to this schema.

    Lifecycle: draft → active → stable / review_needed
    Thresholds (Researcher): 1 / 3 / 5 successes
    """

    # Identity
    sop_id: str = ""
    title: str
    service: str  # e.g. "eks", "ec2", "rds"
    alert_type: str  # e.g. "pod_crash_loop", "high_cpu"

    # Trigger conditions
    trigger_conditions: list[str] = Field(default_factory=list)

    # Diagnostic steps
    diagnostic_steps: list[SOPStep] = Field(default_factory=list)

    # Remediation plans (multiple)
    remediation_plans: list[RemediationPlan] = Field(default_factory=list)

    # Lifecycle
    status: Literal["draft", "active", "stable", "review_needed"] = "draft"
    confidence: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0

    # Provenance
    created_from_incident: str = ""
    updated_from_incidents: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context) -> None:
        if not self.sop_id:
            raw = f"{self.service}:{self.alert_type}:{self.title}"
            self.sop_id = f"sop-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"

    @property
    def s3_key(self) -> str:
        """S3 storage path: sop/{service}/{alert_type}/{sop_id}.md"""
        return f"sop/{self.service}/{self.alert_type}/{self.sop_id}.md"

    # ── Lifecycle transitions ────────────────────────────────

    # Thresholds (Researcher recommendation: 1/3/5)
    _ACTIVE_THRESHOLD = 1
    _STABLE_THRESHOLD = 3
    _HIGH_CONFIDENCE_THRESHOLD = 5
    _FAILURE_DOWNGRADE_THRESHOLD = 2

    def record_success(self) -> None:
        """Record a successful use of this SOP."""
        self.success_count += 1
        self.consecutive_failures = 0
        self.updated_at = datetime.now(timezone.utc)
        self._update_lifecycle()

    def record_failure(self) -> None:
        """Record a failed use of this SOP."""
        self.failure_count += 1
        self.consecutive_failures += 1
        self.updated_at = datetime.now(timezone.utc)
        self._update_lifecycle()

    def _update_lifecycle(self) -> None:
        """Transition lifecycle state based on counts."""
        # Downgrade on consecutive failures
        if self.consecutive_failures >= self._FAILURE_DOWNGRADE_THRESHOLD:
            self.status = "review_needed"
            return

        # Upgrade path
        if self.success_count >= self._HIGH_CONFIDENCE_THRESHOLD:
            self.status = "stable"
            self.confidence = min(1.0, self.success_count / (self.success_count + self.failure_count))
        elif self.success_count >= self._STABLE_THRESHOLD:
            self.status = "stable"
            self.confidence = self.success_count / (self.success_count + self.failure_count)
        elif self.success_count >= self._ACTIVE_THRESHOLD:
            if self.status == "draft":
                self.status = "active"
            self.confidence = self.success_count / (self.success_count + self.failure_count)

    def to_markdown(self) -> str:
        """Render SOP as Markdown for S3 storage."""
        lines = [
            f"# SOP: {self.title}",
            f"",
            f"**SOP ID**: {self.sop_id}",
            f"**Service**: {self.service}",
            f"**Alert Type**: {self.alert_type}",
            f"**Status**: {self.status}",
            f"**Confidence**: {self.confidence:.2f}",
            f"",
            f"## Trigger Conditions",
        ]
        for tc in self.trigger_conditions:
            lines.append(f"- {tc}")

        lines.extend(["", "## Diagnostic Steps"])
        for step in self.diagnostic_steps:
            lines.append(f"{step.order}. {step.description}")
            if step.command:
                lines.append(f"   ```\n   {step.command}\n   ```")
            if step.expected_output:
                lines.append(f"   Expected: {step.expected_output}")

        for plan in self.remediation_plans:
            lines.extend([
                "",
                f"## Remediation: {plan.name}",
                f"Risk: {plan.risk_level} | Approval: {'required' if plan.requires_approval else 'not required'}",
            ])
            for step in plan.steps:
                lines.append(f"{step.order}. {step.description}")
                if step.command:
                    lines.append(f"   ```\n   {step.command}\n   ```")

        lines.extend([
            "",
            "## History",
            f"- Created: {self.created_at.isoformat()} (Incident: {self.created_from_incident})",
        ])
        for inc_id in self.updated_from_incidents:
            lines.append(f"- Updated from: {inc_id}")

        lines.extend([
            "",
            f"## Metrics",
            f"- Success: {self.success_count} | Failure: {self.failure_count}",
        ])

        return "\n".join(lines) + "\n"
