"""
HealthIssue Lifecycle — State Transitions & FixPlan Approval Gates

State machine (Rev 2):
  open → investigating → root_cause_identified → fix_planned →
  fix_approved → fix_executed → resolved ⇄ open (reopen w/ note)

Approval gates by FixPlan risk level:
  L0/L1  → auto-approve
  L2     → human approval required
  L3     → senior approval + double-confirmation required
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import (
    FixPlan,
    FixPlanRiskLevel,
    FixPlanStatus,
    HealthIssue,
    HealthIssueStatus,
    _now_iso,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed state transitions (dict-based, per Reviewer suggestion — Rev 2)
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS = {
    HealthIssueStatus.OPEN: [
        HealthIssueStatus.INVESTIGATING,
        HealthIssueStatus.RESOLVED,
    ],
    HealthIssueStatus.INVESTIGATING: [
        HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
        HealthIssueStatus.OPEN,  # retry / revert
    ],
    HealthIssueStatus.ROOT_CAUSE_IDENTIFIED: [
        HealthIssueStatus.FIX_PLANNED,
        HealthIssueStatus.RESOLVED,  # self-heal
    ],
    HealthIssueStatus.FIX_PLANNED: [
        HealthIssueStatus.FIX_APPROVED,
    ],
    HealthIssueStatus.FIX_APPROVED: [
        HealthIssueStatus.FIX_EXECUTED,
    ],
    HealthIssueStatus.FIX_EXECUTED: [
        HealthIssueStatus.RESOLVED,
        HealthIssueStatus.FIX_PLANNED,  # rollback → re-plan
    ],
    HealthIssueStatus.RESOLVED: [
        HealthIssueStatus.OPEN,  # reopen — requires note
    ],
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _append_timeline(
    health_issue: HealthIssue,
    action: str,
    from_status: str,
    to_status: str,
    *,
    note: Optional[str] = None,
    actor: Optional[str] = None,
) -> None:
    """Append a structured entry to the issue's timeline."""
    entry = {
        "action": action,
        "from": from_status,
        "to": to_status,
        "timestamp": _now_iso(),
    }
    if note:
        entry["note"] = note
    if actor:
        entry["actor"] = actor
    health_issue.timeline.append(entry)


# ---------------------------------------------------------------------------
# Transition helpers
# ---------------------------------------------------------------------------

def can_transition(from_status: HealthIssueStatus, to_status: HealthIssueStatus) -> bool:
    """Return True if *from_status* → *to_status* is a legal transition."""
    return to_status in ALLOWED_TRANSITIONS.get(from_status, [])


def transition(
    health_issue: HealthIssue,
    new_status: HealthIssueStatus,
    *,
    note: Optional[str] = None,
    actor: Optional[str] = None,
) -> HealthIssue:
    """Validate and apply a status transition on *health_issue*.

    For ``RESOLVED → OPEN`` (reopen), a non-empty *note* is **required**.
    Use :func:`reopen` as a convenience wrapper for that case.

    Returns the mutated *health_issue* for convenience.
    Raises ``ValueError`` if the transition is not allowed or preconditions fail.
    """
    if not can_transition(health_issue.status, new_status):
        raise ValueError(
            f"Invalid transition: {health_issue.status.value} → {new_status.value}. "
            f"Allowed targets: {[s.value for s in ALLOWED_TRANSITIONS.get(health_issue.status, [])]}"
        )

    # Reopen guard: RESOLVED → OPEN requires note
    if (
        health_issue.status == HealthIssueStatus.RESOLVED
        and new_status == HealthIssueStatus.OPEN
    ):
        if not note or not note.strip():
            raise ValueError(
                "Reopen (resolved → open) requires a non-empty note explaining the reason."
            )

    old_status = health_issue.status
    health_issue.status = new_status

    if new_status == HealthIssueStatus.RESOLVED:
        health_issue.resolved_at = _now_iso()

    if new_status == HealthIssueStatus.OPEN and old_status == HealthIssueStatus.RESOLVED:
        # Clear resolved_at on reopen
        health_issue.resolved_at = None

    _append_timeline(
        health_issue,
        action="transition",
        from_status=old_status.value,
        to_status=new_status.value,
        note=note,
        actor=actor,
    )

    logger.info(
        "HealthIssue %s transitioned: %s → %s",
        health_issue.id,
        old_status.value,
        new_status.value,
    )
    return health_issue


# ---------------------------------------------------------------------------
# Reopen / Force-close convenience functions
# ---------------------------------------------------------------------------

def reopen(
    health_issue: HealthIssue,
    note: str,
    *,
    actor: Optional[str] = None,
) -> HealthIssue:
    """Reopen a resolved health issue.

    Parameters
    ----------
    note : str
        Mandatory reason for reopening (must be non-empty).
    actor : str, optional
        Who initiated the reopen.

    Raises ``ValueError`` if the issue is not resolved or note is empty.
    """
    if health_issue.status != HealthIssueStatus.RESOLVED:
        raise ValueError(
            f"Cannot reopen: issue is '{health_issue.status.value}', not 'resolved'."
        )
    return transition(health_issue, HealthIssueStatus.OPEN, note=note, actor=actor)


def force_close(
    health_issue: HealthIssue,
    *,
    actor: str,
    note: str = "",
    has_permission: bool = False,
) -> HealthIssue:
    """Force-close a health issue from any state.

    Requires ``has_permission=True`` — intended for admin / senior operators.
    Bypasses normal transition rules and records a ``force_close`` timeline entry.

    Raises ``PermissionError`` if *has_permission* is False.
    """
    if not has_permission:
        raise PermissionError(
            "force_close requires elevated permission (has_permission=True)."
        )

    old_status = health_issue.status
    health_issue.status = HealthIssueStatus.RESOLVED
    health_issue.resolved_at = _now_iso()

    _append_timeline(
        health_issue,
        action="force_close",
        from_status=old_status.value,
        to_status=HealthIssueStatus.RESOLVED.value,
        note=note or "Force-closed by operator",
        actor=actor,
    )

    logger.info(
        "HealthIssue %s force-closed by %s: %s → resolved",
        health_issue.id,
        actor,
        old_status.value,
    )
    return health_issue


# ---------------------------------------------------------------------------
# FixPlan lifecycle
# ---------------------------------------------------------------------------

def create_fix_plan(health_issue: HealthIssue, plan: FixPlan) -> FixPlan:
    """Attach a new FixPlan to a HealthIssue.

    - Links the plan to the issue.
    - For L0/L1 risk levels, auto-approves immediately.
    - For L2/L3, sets status to ``pending_approval``.

    Returns the (potentially updated) FixPlan.
    """
    plan.health_issue_id = health_issue.id

    if plan.risk_level in (FixPlanRiskLevel.L0, FixPlanRiskLevel.L1):
        plan.status = FixPlanStatus.APPROVED
        plan.approved_by = "system:auto_approve"
        plan.approved_at = _now_iso()
        logger.info(
            "FixPlan %s auto-approved (risk=%s)", plan.id, plan.risk_level.value
        )
    else:
        plan.status = FixPlanStatus.PENDING_APPROVAL
        logger.info(
            "FixPlan %s requires approval (risk=%s)", plan.id, plan.risk_level.value
        )

    # Link to health issue
    if plan.id not in health_issue.fix_plan_ids:
        health_issue.fix_plan_ids.append(plan.id)

    return plan


def approve_fix_plan(
    fix_plan: FixPlan,
    approver: str,
    *,
    is_senior: bool = False,
    double_confirmed: bool = False,
) -> FixPlan:
    """Approve a FixPlan.

    For L3 plans, ``is_senior`` **and** ``double_confirmed`` must both be True.
    Raises ``ValueError`` on precondition failures.
    """
    if fix_plan.status != FixPlanStatus.PENDING_APPROVAL:
        raise ValueError(
            f"Cannot approve FixPlan in status '{fix_plan.status.value}'; "
            "expected 'pending_approval'."
        )

    if fix_plan.risk_level == FixPlanRiskLevel.L3:
        if not is_senior:
            raise ValueError("L3 FixPlan requires senior approver.")
        if not double_confirmed:
            raise ValueError("L3 FixPlan requires double confirmation.")

    fix_plan.status = FixPlanStatus.APPROVED
    fix_plan.approved_by = approver
    fix_plan.approved_at = _now_iso()

    logger.info("FixPlan %s approved by %s", fix_plan.id, approver)
    return fix_plan


def reject_fix_plan(fix_plan: FixPlan, reason: str) -> FixPlan:
    """Reject a FixPlan with a reason.

    Raises ``ValueError`` if the plan is not in ``pending_approval``.
    """
    if fix_plan.status != FixPlanStatus.PENDING_APPROVAL:
        raise ValueError(
            f"Cannot reject FixPlan in status '{fix_plan.status.value}'; "
            "expected 'pending_approval'."
        )

    fix_plan.status = FixPlanStatus.REJECTED
    fix_plan.rejected_reason = reason

    logger.info("FixPlan %s rejected: %s", fix_plan.id, reason)
    return fix_plan
