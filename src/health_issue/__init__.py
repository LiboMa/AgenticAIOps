"""
HealthIssue 7-State Lifecycle Module

Unified issue lifecycle replacing IssueStatus (8 states) + IncidentStatus (9 states)
with a single 7-state model: open → investigating → root_cause_identified →
fix_planned → fix_approved → fix_executed → resolved.
"""

from .models import (
    HealthIssueStatus,
    FixPlanStatus,
    FixPlanRiskLevel,
    HealthIssue,
    FixPlan,
    RCAResult,
)
from .lifecycle import (
    ALLOWED_TRANSITIONS,
    can_transition,
    transition,
    create_fix_plan,
    approve_fix_plan,
    reject_fix_plan,
)
from .store import HealthIssueStore
from .migration import (
    ISSUE_STATUS_MIGRATION,
    INCIDENT_STATUS_MIGRATION,
    migrate_issue,
    migrate_incident,
)

__all__ = [
    # Models
    "HealthIssueStatus",
    "FixPlanStatus",
    "FixPlanRiskLevel",
    "HealthIssue",
    "FixPlan",
    "RCAResult",
    # Lifecycle
    "ALLOWED_TRANSITIONS",
    "can_transition",
    "transition",
    "create_fix_plan",
    "approve_fix_plan",
    "reject_fix_plan",
    # Store
    "HealthIssueStore",
    # Migration
    "ISSUE_STATUS_MIGRATION",
    "INCIDENT_STATUS_MIGRATION",
    "migrate_issue",
    "migrate_incident",
]
