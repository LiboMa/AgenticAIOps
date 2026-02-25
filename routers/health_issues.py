"""
HealthIssue API Router

7 endpoints:
  GET    /api/health-issues                              — list (status/severity filter)
  GET    /api/health-issues/{id}                         — detail (incl. RCA + FixPlan)
  PATCH  /api/health-issues/{id}/status                  — transition status
  POST   /api/health-issues/{id}/fix-plan                — create FixPlan
  PATCH  /api/health-issues/{id}/fix-plan/{plan_id}/approve — approve
  PATCH  /api/health-issues/{id}/fix-plan/{plan_id}/reject  — reject
  POST   /api/health-issues/{id}/feedback                — user feedback
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.health_issue.lifecycle import (
    ALLOWED_TRANSITIONS,
    approve_fix_plan,
    can_transition,
    create_fix_plan,
    force_close,
    reject_fix_plan,
    reopen,
    transition,
)
from src.health_issue.models import (
    FixPlan,
    FixPlanRiskLevel,
    HealthIssue,
    HealthIssueStatus,
)
from src.health_issue.store import HealthIssueStore

router = APIRouter(prefix="/api/health-issues", tags=["health-issues"])

# Shared store instance (JSON-file backed)
_store = HealthIssueStore()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class StatusTransitionRequest(BaseModel):
    status: str
    note: Optional[str] = None
    actor: Optional[str] = None


class FixPlanCreateRequest(BaseModel):
    title: str = ""
    description: str = ""
    risk_level: str = "L2"
    rca_result_id: str = ""
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    pre_checks: List[str] = Field(default_factory=list)
    post_checks: List[str] = Field(default_factory=list)
    rollback_plan: List[str] = Field(default_factory=list)
    estimated_impact: str = ""
    sop_id: Optional[str] = None
    sop_name: Optional[str] = None


class FixPlanApproveRequest(BaseModel):
    approver: str
    is_senior: bool = False
    double_confirmed: bool = False


class FixPlanRejectRequest(BaseModel):
    reason: str


class FeedbackRequest(BaseModel):
    feedback: str  # thumbs-up / thumbs-down / free-text


class ForceCloseRequest(BaseModel):
    actor: str
    note: str = ""
    has_permission: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_health_issues(
    status: Optional[str] = Query(None, description="Filter by status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    resource_type: Optional[str] = Query(None, description="Filter by resource_type"),
) -> List[Dict[str, Any]]:
    """List all health issues with optional filters."""
    issues = _store.list_issues(
        status=status, severity=severity, resource_type=resource_type
    )
    return [i.to_dict() for i in issues]


@router.get("/{issue_id}")
def get_health_issue(issue_id: str) -> Dict[str, Any]:
    """Get a health issue with its RCA results and fix plans."""
    issue = _store.get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    result = issue.to_dict()
    result["rca_results"] = [
        r.to_dict() for r in _store.list_rca_results(health_issue_id=issue_id)
    ]
    result["fix_plans"] = [
        p.to_dict() for p in _store.list_fix_plans(health_issue_id=issue_id)
    ]
    result["allowed_transitions"] = [
        s.value for s in ALLOWED_TRANSITIONS.get(issue.status, [])
    ]
    return result


@router.patch("/{issue_id}/status")
def transition_status(issue_id: str, body: StatusTransitionRequest) -> Dict[str, Any]:
    """Transition the status of a health issue."""
    issue = _store.get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    try:
        new_status = HealthIssueStatus(body.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Valid: {[s.value for s in HealthIssueStatus]}",
        )

    try:
        transition(issue, new_status, note=body.note, actor=body.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _store.update_issue(issue)
    return issue.to_dict()


@router.post("/{issue_id}/fix-plan")
def create_fix_plan_endpoint(issue_id: str, body: FixPlanCreateRequest) -> Dict[str, Any]:
    """Create a new fix plan for a health issue."""
    issue = _store.get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    try:
        risk_level = FixPlanRiskLevel(body.risk_level)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid risk_level '{body.risk_level}'. Valid: {[r.value for r in FixPlanRiskLevel]}",
        )

    plan = FixPlan(
        health_issue_id=issue_id,
        rca_result_id=body.rca_result_id,
        title=body.title,
        description=body.description,
        risk_level=risk_level,
        steps=body.steps,
        pre_checks=body.pre_checks,
        post_checks=body.post_checks,
        rollback_plan=body.rollback_plan,
        estimated_impact=body.estimated_impact,
        sop_id=body.sop_id,
        sop_name=body.sop_name,
    )

    plan = create_fix_plan(issue, plan)
    _store.create_fix_plan(plan)
    _store.update_issue(issue)
    return plan.to_dict()


@router.patch("/{issue_id}/fix-plan/{plan_id}/approve")
def approve_fix_plan_endpoint(
    issue_id: str, plan_id: str, body: FixPlanApproveRequest
) -> Dict[str, Any]:
    """Approve a fix plan."""
    plan = _store.get_fix_plan(plan_id)
    if plan is None or plan.health_issue_id != issue_id:
        raise HTTPException(status_code=404, detail=f"FixPlan {plan_id} not found")

    try:
        approve_fix_plan(
            plan,
            body.approver,
            is_senior=body.is_senior,
            double_confirmed=body.double_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _store.update_fix_plan(plan)
    return plan.to_dict()


@router.patch("/{issue_id}/fix-plan/{plan_id}/reject")
def reject_fix_plan_endpoint(
    issue_id: str, plan_id: str, body: FixPlanRejectRequest
) -> Dict[str, Any]:
    """Reject a fix plan."""
    plan = _store.get_fix_plan(plan_id)
    if plan is None or plan.health_issue_id != issue_id:
        raise HTTPException(status_code=404, detail=f"FixPlan {plan_id} not found")

    try:
        reject_fix_plan(plan, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _store.update_fix_plan(plan)
    return plan.to_dict()


@router.post("/{issue_id}/feedback")
def submit_feedback(issue_id: str, body: FeedbackRequest) -> Dict[str, Any]:
    """Submit user feedback for a health issue."""
    issue = _store.get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    issue.user_feedback = body.feedback
    _store.update_issue(issue)
    return {"status": "ok", "issue_id": issue_id, "feedback": body.feedback}


@router.post("/{issue_id}/force-close")
def force_close_endpoint(issue_id: str, body: ForceCloseRequest) -> Dict[str, Any]:
    """Force-close a health issue from any state (requires permission)."""
    issue = _store.get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"HealthIssue {issue_id} not found")

    try:
        force_close(
            issue,
            actor=body.actor,
            note=body.note,
            has_permission=body.has_permission,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    _store.update_issue(issue)
    return issue.to_dict()
