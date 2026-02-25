"""
HealthIssue Data Models

Defines the core data structures for the unified 7-state health issue lifecycle:
  open → investigating → root_cause_identified → fix_planned →
  fix_approved → fix_executed → resolved

Replaces IssueStatus (8 states) + IncidentStatus (9 states).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class HealthIssueStatus(str, Enum):
    """Unified issue lifecycle status (7 states)."""
    OPEN = "open"
    INVESTIGATING = "investigating"
    ROOT_CAUSE_IDENTIFIED = "root_cause_identified"
    FIX_PLANNED = "fix_planned"
    FIX_APPROVED = "fix_approved"
    FIX_EXECUTED = "fix_executed"
    RESOLVED = "resolved"


class FixPlanStatus(str, Enum):
    """FixPlan approval status."""
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class FixPlanRiskLevel(str, Enum):
    """FixPlan risk classification.

    L0 — Read-only verification (auto-approve)
    L1 — Low-risk config change (auto-approve)
    L2 — Service-affecting (requires human approval)
    L3 — High-risk: restart / failover / migration (senior + double-confirm)
    """
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# RCAResult
# ---------------------------------------------------------------------------

@dataclass
class RCAResult:
    """Root-cause analysis result linked to a HealthIssue (1:N)."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    health_issue_id: str = ""
    root_cause: str = ""
    confidence: float = 0.0
    contributing_factors: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    model_id: str = ""
    network_context: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=_now_iso)

    # -- serialisation helpers ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RCAResult":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            health_issue_id=data.get("health_issue_id", ""),
            root_cause=data.get("root_cause", ""),
            confidence=float(data.get("confidence", 0.0)),
            contributing_factors=data.get("contributing_factors", []),
            recommendations=data.get("recommendations", []),
            model_id=data.get("model_id", ""),
            network_context=data.get("network_context"),
            created_at=data.get("created_at", _now_iso()),
        )


# ---------------------------------------------------------------------------
# FixPlan
# ---------------------------------------------------------------------------

@dataclass
class FixPlan:
    """A structured remediation plan linked to a HealthIssue."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    health_issue_id: str = ""
    rca_result_id: str = ""
    title: str = ""
    description: str = ""
    risk_level: FixPlanRiskLevel = FixPlanRiskLevel.L2
    status: FixPlanStatus = FixPlanStatus.DRAFT

    # Structured plan
    steps: List[Dict[str, Any]] = field(default_factory=list)
    pre_checks: List[str] = field(default_factory=list)
    post_checks: List[str] = field(default_factory=list)
    rollback_plan: List[str] = field(default_factory=list)
    estimated_impact: str = ""

    # SOP reference
    sop_id: Optional[str] = None
    sop_name: Optional[str] = None

    # Approval
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_reason: Optional[str] = None

    # Timing
    created_at: str = field(default_factory=_now_iso)
    executed_at: Optional[str] = None

    # -- serialisation helpers ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Store enum values as plain strings
        d["risk_level"] = self.risk_level.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FixPlan":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            health_issue_id=data.get("health_issue_id", ""),
            rca_result_id=data.get("rca_result_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            risk_level=FixPlanRiskLevel(data.get("risk_level", "L2")),
            status=FixPlanStatus(data.get("status", "draft")),
            steps=data.get("steps", []),
            pre_checks=data.get("pre_checks", []),
            post_checks=data.get("post_checks", []),
            rollback_plan=data.get("rollback_plan", []),
            estimated_impact=data.get("estimated_impact", ""),
            sop_id=data.get("sop_id"),
            sop_name=data.get("sop_name"),
            approved_by=data.get("approved_by"),
            approved_at=data.get("approved_at"),
            rejected_reason=data.get("rejected_reason"),
            created_at=data.get("created_at", _now_iso()),
            executed_at=data.get("executed_at"),
        )


# ---------------------------------------------------------------------------
# HealthIssue
# ---------------------------------------------------------------------------

@dataclass
class HealthIssue:
    """Unified health issue entity tracking the full lifecycle."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    resource_id: str = ""
    resource_type: str = ""
    region: str = ""

    severity: str = "medium"  # critical / high / medium / low
    source: str = ""          # cloudwatch_alarm / metric_anomaly / detect_agent / manual
    title: str = ""
    description: str = ""

    status: HealthIssueStatus = HealthIssueStatus.OPEN

    # Related data
    alarm_name: Optional[str] = None
    metric_data: Dict[str, Any] = field(default_factory=dict)
    related_changes: List[Dict[str, Any]] = field(default_factory=list)

    # Linked entities (by ID)
    rca_result_ids: List[str] = field(default_factory=list)
    fix_plan_ids: List[str] = field(default_factory=list)
    incident_id: Optional[str] = None   # Link to legacy IncidentRecord
    issue_id: Optional[str] = None      # Link to legacy Issue (compat)

    # Timing
    detected_at: str = field(default_factory=_now_iso)
    resolved_at: Optional[str] = None

    # Feedback
    user_feedback: Optional[str] = None  # thumbs-up / thumbs-down / comment

    # -- serialisation helpers ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HealthIssue":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            resource_id=data.get("resource_id", ""),
            resource_type=data.get("resource_type", ""),
            region=data.get("region", ""),
            severity=data.get("severity", "medium"),
            source=data.get("source", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=HealthIssueStatus(data.get("status", "open")),
            alarm_name=data.get("alarm_name"),
            metric_data=data.get("metric_data", {}),
            related_changes=data.get("related_changes", []),
            rca_result_ids=data.get("rca_result_ids", []),
            fix_plan_ids=data.get("fix_plan_ids", []),
            incident_id=data.get("incident_id"),
            issue_id=data.get("issue_id"),
            detected_at=data.get("detected_at", _now_iso()),
            resolved_at=data.get("resolved_at"),
            user_feedback=data.get("user_feedback"),
        )

    def is_resolved(self) -> bool:
        return self.status == HealthIssueStatus.RESOLVED
