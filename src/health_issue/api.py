"""
HealthIssue API — FastAPI router for health issue lifecycle management.

Endpoints:
  GET    /api/health-issues                              — List (filter by status/severity)
  POST   /api/health-issues                              — Create new issue
  GET    /api/health-issues/{id}                         — Detail (with RCA + FixPlan)
  PATCH  /api/health-issues/{id}/status                  — Transition status
  POST   /api/health-issues/{id}/fix-plan                — Create FixPlan
  PATCH  /api/health-issues/{id}/fix-plan/{plan_id}/approve — Approve FixPlan
  PATCH  /api/health-issues/{id}/fix-plan/{plan_id}/reject  — Reject FixPlan
  POST   /api/health-issues/{id}/feedback                — User feedback
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .lifecycle import (
    ALLOWED_TRANSITIONS,
    approve_fix_plan,
    can_transition,
    create_fix_plan,
    reject_fix_plan,
    transition,
)
from .models import (
    FixPlan,
    FixPlanRiskLevel,
    HealthIssue,
    HealthIssueStatus,
    RCAResult,
)
from .store import HealthIssueStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health-issues", tags=["health-issues"])

# Singleton store (JSON-backed, swap to SQLAlchemy later)
_store = HealthIssueStore()


def get_store() -> HealthIssueStore:
    """Return the module-level store (testable via monkey-patch)."""
    return _store


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CreateIssueRequest(BaseModel):
    resource_id: str = ""
    resource_type: str = ""
    region: str = ""
    severity: str = "medium"
    source: str = ""
    title: str = ""
    description: str = ""
    alarm_name: Optional[str] = None
    metric_data: Dict[str, Any] = Field(default_factory=dict)


class TransitionRequest(BaseModel):
    status: str  # target HealthIssueStatus value


class CreateFixPlanRequest(BaseModel):
    title: str = ""
    description: str = ""
    risk_level: str = "L2"
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    pre_checks: List[str] = Field(default_factory=list)
    post_checks: List[str] = Field(default_factory=list)
    rollback_plan: List[str] = Field(default_factory=list)
    estimated_impact: str = ""
    sop_id: Optional[str] = None
    sop_name: Optional[str] = None
    rca_result_id: str = ""


class ApproveRequest(BaseModel):
    approver: str
    is_senior: bool = False
    double_confirmed: bool = False


class RejectRequest(BaseModel):
    reason: str


class FeedbackRequest(BaseModel):
    feedback: str  # e.g. "thumbs-up", "thumbs-down", free text


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_health_issues(
    status: Optional[str] = Query(None, description="Filter by status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
) -> Dict[str, Any]:
    """List health issues with optional filters."""
    store = get_store()
    issues = store.list_issues(
        status=status,
        severity=severity,
        resource_type=resource_type,
    )
    return {
        "count": len(issues),
        "items": [i.to_dict() for i in issues],
    }


@router.post("", status_code=201)
def create_health_issue(req: CreateIssueRequest) -> Dict[str, Any]:
    """Create a new health issue (status=OPEN)."""
    store = get_store()
    issue = HealthIssue(
        resource_id=req.resource_id,
        resource_type=req.resource_type,
        region=req.region,
        severity=req.severity,
        source=req.source,
        title=req.title,
        description=req.description,
        alarm_name=req.alarm_name,
        metric_data=req.metric_data,
    )
    store.create_issue(issue)
    logger.info("Created HealthIssue %s: %s", issue.id, issue.title)
    return issue.to_dict()


@router.get("/{issue_id}")
def get_health_issue(issue_id: str) -> Dict[str, Any]:
    """Get health issue detail with linked RCA results and fix plans."""
    store = get_store()
    issue = store.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    result = issue.to_dict()

    # Embed linked RCA results
    rca_results = store.list_rca_results(health_issue_id=issue_id)
    result["rca_results"] = [r.to_dict() for r in rca_results]

    # Embed linked fix plans
    fix_plans = store.list_fix_plans(health_issue_id=issue_id)
    result["fix_plans"] = [p.to_dict() for p in fix_plans]

    # Include allowed transitions
    current = issue.status
    result["allowed_transitions"] = [
        s.value for s in ALLOWED_TRANSITIONS.get(current, [])
    ]

    return result


@router.patch("/{issue_id}/status")
def transition_status(issue_id: str, req: TransitionRequest) -> Dict[str, Any]:
    """Transition a health issue to a new status."""
    store = get_store()
    issue = store.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    try:
        new_status = HealthIssueStatus(req.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{req.status}'. "
            f"Valid values: {[s.value for s in HealthIssueStatus]}",
        )

    if not can_transition(issue.status, new_status):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition from '{issue.status.value}' to '{new_status.value}'. "
            f"Allowed: {[s.value for s in ALLOWED_TRANSITIONS.get(issue.status, [])]}",
        )

    transition(issue, new_status)
    store.update_issue(issue)

    return {
        "id": issue.id,
        "status": issue.status.value,
        "resolved_at": issue.resolved_at,
    }


@router.post("/{issue_id}/fix-plan", status_code=201)
def create_issue_fix_plan(issue_id: str, req: CreateFixPlanRequest) -> Dict[str, Any]:
    """Create and attach a FixPlan to a health issue."""
    store = get_store()
    issue = store.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    try:
        risk = FixPlanRiskLevel(req.risk_level)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid risk_level '{req.risk_level}'. "
            f"Valid: {[r.value for r in FixPlanRiskLevel]}",
        )

    plan = FixPlan(
        health_issue_id=issue_id,
        rca_result_id=req.rca_result_id,
        title=req.title,
        description=req.description,
        risk_level=risk,
        steps=req.steps,
        pre_checks=req.pre_checks,
        post_checks=req.post_checks,
        rollback_plan=req.rollback_plan,
        estimated_impact=req.estimated_impact,
        sop_id=req.sop_id,
        sop_name=req.sop_name,
    )

    # Lifecycle: auto-approve L0/L1, set pending for L2/L3
    create_fix_plan(issue, plan)

    # Persist
    store.create_fix_plan(plan)
    store.update_issue(issue)

    return plan.to_dict()


@router.patch("/{issue_id}/fix-plan/{plan_id}/approve")
def approve_issue_fix_plan(
    issue_id: str, plan_id: str, req: ApproveRequest
) -> Dict[str, Any]:
    """Approve a pending FixPlan."""
    store = get_store()
    issue = store.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    plan = store.get_fix_plan(plan_id)
    if not plan or plan.health_issue_id != issue_id:
        raise HTTPException(status_code=404, detail=f"FixPlan {plan_id} not found")

    try:
        approve_fix_plan(
            plan,
            approver=req.approver,
            is_senior=req.is_senior,
            double_confirmed=req.double_confirmed,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    store.update_fix_plan(plan)
    return plan.to_dict()


@router.patch("/{issue_id}/fix-plan/{plan_id}/reject")
def reject_issue_fix_plan(
    issue_id: str, plan_id: str, req: RejectRequest
) -> Dict[str, Any]:
    """Reject a pending FixPlan with reason."""
    store = get_store()
    issue = store.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    plan = store.get_fix_plan(plan_id)
    if not plan or plan.health_issue_id != issue_id:
        raise HTTPException(status_code=404, detail=f"FixPlan {plan_id} not found")

    try:
        reject_fix_plan(plan, reason=req.reason)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    store.update_fix_plan(plan)
    return plan.to_dict()


@router.post("/{issue_id}/feedback")
def submit_feedback(issue_id: str, req: FeedbackRequest) -> Dict[str, Any]:
    """Submit user feedback on a health issue."""
    store = get_store()
    issue = store.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    issue.user_feedback = req.feedback
    store.update_issue(issue)

    logger.info("Feedback for HealthIssue %s: %s", issue_id, req.feedback)
    return {"id": issue_id, "feedback": req.feedback}
