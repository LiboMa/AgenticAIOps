"""
HealthIssue Migration — IssueStatus / IncidentStatus → HealthIssueStatus

Maps legacy 8-state IssueStatus and 9-state IncidentStatus to the unified
7-state HealthIssueStatus model.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .models import HealthIssue, HealthIssueStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IssueStatus (8 states) → HealthIssueStatus (7 states)
# ---------------------------------------------------------------------------

ISSUE_STATUS_MIGRATION: Dict[str, str] = {
    "detected": "open",
    "analyzing": "investigating",
    "pending_fix": "fix_planned",
    "fixing": "fix_executed",
    "fixed": "resolved",
    "failed": "open",            # re-open for retry
    "acknowledged": "investigating",
    "closed": "resolved",
}

# ---------------------------------------------------------------------------
# IncidentStatus (9 states) → HealthIssueStatus (7 states)
# ---------------------------------------------------------------------------

INCIDENT_STATUS_MIGRATION: Dict[str, str] = {
    "triggered": "open",
    "collecting": "investigating",
    "analyzing": "investigating",
    "sop_matched": "root_cause_identified",
    "safety_check": "fix_planned",
    "executing": "fix_executed",
    "waiting_approval": "fix_planned",
    "completed": "resolved",
    "failed": "open",            # re-open for retry
}


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

def migrate_issue(issue_dict: Dict[str, Any]) -> HealthIssue:
    """Convert a legacy Issue dict to a HealthIssue.

    Maps ``status`` through ``ISSUE_STATUS_MIGRATION``.
    Carries over resource identifiers and timing where available.

    Parameters
    ----------
    issue_dict : dict
        Serialised legacy ``Issue`` (from ``src/issues/models.py``).

    Returns
    -------
    HealthIssue
        A new HealthIssue with the mapped status and copied fields.
    """
    old_status = str(issue_dict.get("status", "detected")).lower()
    new_status_str = ISSUE_STATUS_MIGRATION.get(old_status, "open")
    new_status = HealthIssueStatus(new_status_str)

    hi = HealthIssue(
        resource_id=issue_dict.get("resource_id", issue_dict.get("pod_name", "")),
        resource_type=issue_dict.get("resource_type", issue_dict.get("issue_type", "")),
        region=issue_dict.get("region", ""),
        severity=_map_severity(issue_dict.get("severity", "medium")),
        source="detect_agent",
        title=issue_dict.get("title", issue_dict.get("issue_type", "")),
        description=issue_dict.get("description", issue_dict.get("details", "")),
        status=new_status,
        issue_id=issue_dict.get("id", issue_dict.get("issue_id")),
        detected_at=issue_dict.get("detected_at", issue_dict.get("created_at", "")),
    )

    if new_status == HealthIssueStatus.RESOLVED:
        hi.resolved_at = issue_dict.get("resolved_at", issue_dict.get("updated_at"))

    logger.info(
        "Migrated Issue %s: %s → %s",
        hi.issue_id,
        old_status,
        new_status.value,
    )
    return hi


def migrate_incident(incident_dict: Dict[str, Any]) -> HealthIssue:
    """Convert a legacy IncidentRecord dict to a HealthIssue.

    Maps ``status`` through ``INCIDENT_STATUS_MIGRATION``.

    Parameters
    ----------
    incident_dict : dict
        Serialised ``IncidentRecord`` (from ``src/incident_orchestrator.py``).

    Returns
    -------
    HealthIssue
        A new HealthIssue with the mapped status and copied fields.
    """
    old_status = str(incident_dict.get("status", "triggered")).lower()
    new_status_str = INCIDENT_STATUS_MIGRATION.get(old_status, "open")
    new_status = HealthIssueStatus(new_status_str)

    trigger_data = incident_dict.get("trigger_data", {})

    hi = HealthIssue(
        resource_id=trigger_data.get("resource_id", ""),
        resource_type=trigger_data.get("resource_type", ""),
        region=incident_dict.get("region", ""),
        severity=_map_severity(trigger_data.get("severity", "medium")),
        source=incident_dict.get("trigger_type", "cloudwatch_alarm"),
        title=trigger_data.get("alarm_name", trigger_data.get("title", "")),
        description=trigger_data.get("description", ""),
        status=new_status,
        alarm_name=trigger_data.get("alarm_name"),
        metric_data=trigger_data.get("metric_data", {}),
        incident_id=incident_dict.get("incident_id"),
        detected_at=incident_dict.get("created_at", ""),
    )

    if new_status == HealthIssueStatus.RESOLVED:
        hi.resolved_at = incident_dict.get("completed_at")

    # Carry over RCA if present
    rca_data = incident_dict.get("rca_result")
    if rca_data and isinstance(rca_data, dict):
        rca_id = rca_data.get("id")
        if rca_id:
            hi.rca_result_ids.append(rca_id)

    logger.info(
        "Migrated Incident %s: %s → %s",
        hi.incident_id,
        old_status,
        new_status.value,
    )
    return hi


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _map_severity(severity: Optional[str]) -> str:
    """Normalise severity to one of critical/high/medium/low."""
    if not severity:
        return "medium"
    s = str(severity).lower().strip()
    if s in ("critical", "high", "medium", "low"):
        return s
    # Legacy numeric mapping (1=critical, 4=low)
    try:
        n = int(s)
        return {1: "critical", 2: "high", 3: "medium"}.get(n, "low")
    except (ValueError, TypeError):
        return "medium"
