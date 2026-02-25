"""
HealthIssue Lifecycle Tests — State Transitions + FixPlan Approval Gates

Test plan v2 (~57 tests):
  - State transitions: happy path, shortcuts, rollbacks, illegal (parametrized)
  - Reopen: resolved → open with/without note
  - FixPlan: L0-L3 approval gates, reject flow, edge cases
  - Store: CRUD + filters + corrupted JSON
  - Models: serialisation round-trip

Note: We import directly from sub-modules to bypass __init__.py (which
currently fails because migration.py is missing).
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from itertools import product

import pytest

# Import from sub-modules directly (avoid __init__.py migration import error)
from src.health_issue.models import (
    FixPlan,
    FixPlanRiskLevel,
    FixPlanStatus,
    HealthIssue,
    HealthIssueStatus,
    RCAResult,
)
from src.health_issue.lifecycle import (
    ALLOWED_TRANSITIONS,
    approve_fix_plan,
    can_transition,
    create_fix_plan,
    reject_fix_plan,
    transition,
)
from src.health_issue.store import HealthIssueStore


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def issue() -> HealthIssue:
    """Fresh OPEN issue."""
    return HealthIssue(
        id=str(uuid.uuid4()),
        resource_id="i-abc123",
        resource_type="ec2",
        region="us-east-1",
        severity="high",
        source="cloudwatch_alarm",
        title="High CPU on i-abc123",
    )


@pytest.fixture
def tmp_store(tmp_path) -> HealthIssueStore:
    """Store backed by a temporary directory."""
    return HealthIssueStore(data_dir=str(tmp_path))


# ===================================================================
# 1. State Transition Tests — Parametrized from ALLOWED_TRANSITIONS
# ===================================================================

# Build (from, to, expected) tuples from the single source of truth
ALL_STATUSES = list(HealthIssueStatus)

_legal_pairs = []
for src, targets in ALLOWED_TRANSITIONS.items():
    for tgt in targets:
        _legal_pairs.append((src, tgt))

_illegal_pairs = []
for src in ALL_STATUSES:
    legal_targets = set(ALLOWED_TRANSITIONS.get(src, []))
    for tgt in ALL_STATUSES:
        if tgt != src and tgt not in legal_targets:
            _illegal_pairs.append((src, tgt))


class TestLegalTransitions:
    """Every entry in ALLOWED_TRANSITIONS should succeed."""

    @pytest.mark.parametrize("from_status,to_status", _legal_pairs,
                             ids=[f"{a.value}->{b.value}" for a, b in _legal_pairs])
    def test_can_transition_returns_true(self, from_status, to_status):
        assert can_transition(from_status, to_status) is True

    @pytest.mark.parametrize("from_status,to_status", _legal_pairs,
                             ids=[f"{a.value}->{b.value}" for a, b in _legal_pairs])
    def test_transition_succeeds(self, from_status, to_status):
        hi = HealthIssue(status=from_status)
        # Reopen requires note
        kwargs = {}
        if from_status == HealthIssueStatus.RESOLVED and to_status == HealthIssueStatus.OPEN:
            kwargs["note"] = "Issue recurred"
        result = transition(hi, to_status, **kwargs)
        assert result.status == to_status
        assert result is hi  # mutates in place


class TestIllegalTransitions:
    """Every pair NOT in ALLOWED_TRANSITIONS should be rejected."""

    @pytest.mark.parametrize("from_status,to_status", _illegal_pairs,
                             ids=[f"{a.value}->/{b.value}" for a, b in _illegal_pairs])
    def test_can_transition_returns_false(self, from_status, to_status):
        assert can_transition(from_status, to_status) is False

    @pytest.mark.parametrize("from_status,to_status", _illegal_pairs,
                             ids=[f"{a.value}->/{b.value}" for a, b in _illegal_pairs])
    def test_transition_raises(self, from_status, to_status):
        hi = HealthIssue(status=from_status)
        with pytest.raises(ValueError, match="Invalid transition"):
            transition(hi, to_status)


class TestSelfTransition:
    """Transitioning to the same status should be illegal."""

    @pytest.mark.parametrize("status", ALL_STATUSES, ids=[s.value for s in ALL_STATUSES])
    def test_self_transition_rejected(self, status):
        assert can_transition(status, status) is False


# ===================================================================
# 2. Happy Path — Full lifecycle walk-through
# ===================================================================

class TestHappyPath:
    """Walk the full lifecycle: open → ... → resolved."""

    def test_full_lifecycle(self, issue):
        path = [
            HealthIssueStatus.INVESTIGATING,
            HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
            HealthIssueStatus.FIX_PLANNED,
            HealthIssueStatus.FIX_APPROVED,
            HealthIssueStatus.FIX_EXECUTED,
            HealthIssueStatus.RESOLVED,
        ]
        for step in path:
            transition(issue, step)
        assert issue.status == HealthIssueStatus.RESOLVED
        assert issue.resolved_at is not None

    def test_shortcut_open_to_resolved(self, issue):
        """Self-healing or false alarm: open → resolved directly."""
        transition(issue, HealthIssueStatus.RESOLVED)
        assert issue.status == HealthIssueStatus.RESOLVED
        assert issue.resolved_at is not None

    def test_shortcut_rca_to_resolved(self, issue):
        """Self-heal after RCA: root_cause_identified → resolved."""
        transition(issue, HealthIssueStatus.INVESTIGATING)
        transition(issue, HealthIssueStatus.ROOT_CAUSE_IDENTIFIED)
        transition(issue, HealthIssueStatus.RESOLVED)
        assert issue.status == HealthIssueStatus.RESOLVED

    def test_rollback_fix_executed_to_fix_planned(self, issue):
        """Rollback scenario: fix_executed → fix_planned."""
        for s in [
            HealthIssueStatus.INVESTIGATING,
            HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
            HealthIssueStatus.FIX_PLANNED,
            HealthIssueStatus.FIX_APPROVED,
            HealthIssueStatus.FIX_EXECUTED,
        ]:
            transition(issue, s)
        transition(issue, HealthIssueStatus.FIX_PLANNED)
        assert issue.status == HealthIssueStatus.FIX_PLANNED

    def test_retry_investigating_to_open(self, issue):
        """Investigating reveals false lead → revert to open."""
        transition(issue, HealthIssueStatus.INVESTIGATING)
        transition(issue, HealthIssueStatus.OPEN)
        assert issue.status == HealthIssueStatus.OPEN


# ===================================================================
# 3. Reopen (RESOLVED → OPEN) — Rev 2 Design
# ===================================================================
#
# NOTE: Current lifecycle.py has RESOLVED: [] (terminal).
# These tests document the EXPECTED Rev 2 behavior.
# They are marked xfail until Developer implements reopen.
# ===================================================================

class TestReopen:
    """RESOLVED → OPEN reopen path (Rev 2 requirement)."""

    def test_reopen_with_note_succeeds(self, issue):
        transition(issue, HealthIssueStatus.RESOLVED)
        transition(issue, HealthIssueStatus.OPEN, note="Issue recurred after deploy")
        assert issue.status == HealthIssueStatus.OPEN
        assert issue.resolved_at is None  # cleared on reopen

    def test_reopen_without_note_rejected(self, issue):
        transition(issue, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError, match="note"):
            transition(issue, HealthIssueStatus.OPEN)  # no note → should fail

    def test_reopen_empty_note_rejected(self, issue):
        transition(issue, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError, match="note"):
            transition(issue, HealthIssueStatus.OPEN, note="")

    def test_reopen_whitespace_only_note_rejected(self, issue):
        """Whitespace-only note should also be rejected."""
        transition(issue, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError, match="note"):
            transition(issue, HealthIssueStatus.OPEN, note="   ")

    def test_reopen_records_timeline(self, issue):
        """Reopen should leave a timeline entry with the note."""
        transition(issue, HealthIssueStatus.RESOLVED)
        transition(issue, HealthIssueStatus.OPEN, note="Recurrence detected")
        reopen_entries = [e for e in issue.timeline if e.get("to") == "open"
                          and e.get("from") == "resolved"]
        assert len(reopen_entries) >= 1
        assert reopen_entries[-1].get("note") == "Recurrence detected"

    def test_resolved_to_investigating_illegal(self, issue):
        transition(issue, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError):
            transition(issue, HealthIssueStatus.INVESTIGATING)

    def test_resolved_to_fix_planned_illegal(self, issue):
        transition(issue, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError):
            transition(issue, HealthIssueStatus.FIX_PLANNED)


# ===================================================================
# 4. Resolved-at timestamp
# ===================================================================

class TestResolvedTimestamp:
    """resolved_at is set only when entering RESOLVED."""

    def test_resolved_at_set_on_resolve(self, issue):
        assert issue.resolved_at is None
        transition(issue, HealthIssueStatus.RESOLVED)
        assert issue.resolved_at is not None

    def test_resolved_at_not_set_on_other(self, issue):
        transition(issue, HealthIssueStatus.INVESTIGATING)
        assert issue.resolved_at is None


# ===================================================================
# 5. FixPlan Approval Gates
# ===================================================================

class TestFixPlanAutoApprove:
    """L0 and L1 risk levels auto-approve."""

    @pytest.mark.parametrize("risk", [FixPlanRiskLevel.L0, FixPlanRiskLevel.L1])
    def test_auto_approve(self, issue, risk):
        plan = FixPlan(risk_level=risk, title="Verify metrics")
        result = create_fix_plan(issue, plan)
        assert result.status == FixPlanStatus.APPROVED
        assert result.approved_by == "system:auto_approve"
        assert result.approved_at is not None
        assert plan.id in issue.fix_plan_ids

    @pytest.mark.parametrize("risk", [FixPlanRiskLevel.L2, FixPlanRiskLevel.L3])
    def test_manual_approval_required(self, issue, risk):
        plan = FixPlan(risk_level=risk, title="Restart service")
        result = create_fix_plan(issue, plan)
        assert result.status == FixPlanStatus.PENDING_APPROVAL
        assert result.approved_by is None


class TestFixPlanApproval:
    """Manual approval flow for L2/L3."""

    def test_l2_approve(self):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2, status=FixPlanStatus.PENDING_APPROVAL)
        result = approve_fix_plan(plan, "engineer@team")
        assert result.status == FixPlanStatus.APPROVED
        assert result.approved_by == "engineer@team"
        assert result.approved_at is not None

    def test_l3_approve_senior_and_double_confirm(self):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L3, status=FixPlanStatus.PENDING_APPROVAL)
        result = approve_fix_plan(plan, "senior@team", is_senior=True, double_confirmed=True)
        assert result.status == FixPlanStatus.APPROVED

    def test_l3_reject_not_senior(self):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L3, status=FixPlanStatus.PENDING_APPROVAL)
        with pytest.raises(ValueError, match="senior"):
            approve_fix_plan(plan, "junior@team", is_senior=False, double_confirmed=True)

    def test_l3_reject_no_double_confirm(self):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L3, status=FixPlanStatus.PENDING_APPROVAL)
        with pytest.raises(ValueError, match="double confirmation"):
            approve_fix_plan(plan, "senior@team", is_senior=True, double_confirmed=False)

    def test_approve_non_pending_raises(self):
        plan = FixPlan(status=FixPlanStatus.DRAFT)
        with pytest.raises(ValueError, match="pending_approval"):
            approve_fix_plan(plan, "someone")

    def test_approve_already_approved_raises(self):
        plan = FixPlan(status=FixPlanStatus.APPROVED)
        with pytest.raises(ValueError, match="pending_approval"):
            approve_fix_plan(plan, "someone")


class TestFixPlanReject:
    """Rejection flow."""

    def test_reject_with_reason(self):
        plan = FixPlan(status=FixPlanStatus.PENDING_APPROVAL)
        result = reject_fix_plan(plan, "Too risky for maintenance window")
        assert result.status == FixPlanStatus.REJECTED
        assert result.rejected_reason == "Too risky for maintenance window"

    def test_reject_non_pending_raises(self):
        plan = FixPlan(status=FixPlanStatus.DRAFT)
        with pytest.raises(ValueError, match="pending_approval"):
            reject_fix_plan(plan, "reason")


class TestFixPlanEdgeCases:
    """Edge cases for FixPlan creation."""

    def test_empty_steps(self, issue):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2, steps=[])
        result = create_fix_plan(issue, plan)
        assert result.status == FixPlanStatus.PENDING_APPROVAL
        assert result.steps == []

    def test_no_rollback_plan(self, issue):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2, rollback_plan=[])
        result = create_fix_plan(issue, plan)
        assert result.rollback_plan == []

    def test_duplicate_plan_not_duplicated_in_ids(self, issue):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L0)
        create_fix_plan(issue, plan)
        create_fix_plan(issue, plan)  # same plan again
        assert issue.fix_plan_ids.count(plan.id) == 1

    def test_plan_linked_to_issue(self, issue):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L1)
        result = create_fix_plan(issue, plan)
        assert result.health_issue_id == issue.id


# ===================================================================
# 6. Store CRUD + Filters
# ===================================================================

class TestStoreCRUD:
    """HealthIssueStore basic operations."""

    def test_create_and_get(self, tmp_store):
        hi = HealthIssue(title="Test issue")
        tmp_store.create_issue(hi)
        loaded = tmp_store.get_issue(hi.id)
        assert loaded is not None
        assert loaded.id == hi.id
        assert loaded.title == "Test issue"

    def test_get_nonexistent_returns_none(self, tmp_store):
        assert tmp_store.get_issue("nonexistent-id") is None

    def test_update(self, tmp_store):
        hi = HealthIssue(title="Original")
        tmp_store.create_issue(hi)
        hi.title = "Updated"
        hi.status = HealthIssueStatus.INVESTIGATING
        tmp_store.update_issue(hi)
        loaded = tmp_store.get_issue(hi.id)
        assert loaded.title == "Updated"
        assert loaded.status == HealthIssueStatus.INVESTIGATING

    def test_update_nonexistent_raises(self, tmp_store):
        hi = HealthIssue(id="ghost")
        with pytest.raises(KeyError):
            tmp_store.update_issue(hi)

    def test_delete(self, tmp_store):
        hi = HealthIssue()
        tmp_store.create_issue(hi)
        assert tmp_store.delete_issue(hi.id) is True
        assert tmp_store.get_issue(hi.id) is None

    def test_delete_nonexistent_returns_false(self, tmp_store):
        assert tmp_store.delete_issue("nope") is False

    def test_list_all(self, tmp_store):
        for i in range(3):
            tmp_store.create_issue(HealthIssue(title=f"issue-{i}"))
        assert len(tmp_store.list_issues()) == 3

    def test_list_filter_status(self, tmp_store):
        hi1 = HealthIssue(status=HealthIssueStatus.OPEN)
        hi2 = HealthIssue(status=HealthIssueStatus.RESOLVED)
        tmp_store.create_issue(hi1)
        tmp_store.create_issue(hi2)
        open_list = tmp_store.list_issues(status="open")
        assert len(open_list) == 1
        assert open_list[0].status == HealthIssueStatus.OPEN

    def test_list_filter_severity(self, tmp_store):
        tmp_store.create_issue(HealthIssue(severity="critical"))
        tmp_store.create_issue(HealthIssue(severity="low"))
        crit = tmp_store.list_issues(severity="critical")
        assert len(crit) == 1
        assert crit[0].severity == "critical"

    def test_list_filter_resource_type(self, tmp_store):
        tmp_store.create_issue(HealthIssue(resource_type="ec2"))
        tmp_store.create_issue(HealthIssue(resource_type="rds"))
        ec2_list = tmp_store.list_issues(resource_type="ec2")
        assert len(ec2_list) == 1


class TestStoreFixPlan:
    """FixPlan store operations."""

    def test_create_and_get_fix_plan(self, tmp_store):
        fp = FixPlan(title="Restart nginx")
        tmp_store.create_fix_plan(fp)
        loaded = tmp_store.get_fix_plan(fp.id)
        assert loaded is not None
        assert loaded.title == "Restart nginx"

    def test_list_fix_plans_by_issue(self, tmp_store):
        fp1 = FixPlan(health_issue_id="issue-1")
        fp2 = FixPlan(health_issue_id="issue-2")
        tmp_store.create_fix_plan(fp1)
        tmp_store.create_fix_plan(fp2)
        plans = tmp_store.list_fix_plans(health_issue_id="issue-1")
        assert len(plans) == 1
        assert plans[0].health_issue_id == "issue-1"


class TestStoreRCAResult:
    """RCAResult store operations."""

    def test_create_and_get_rca(self, tmp_store):
        rca = RCAResult(root_cause="Memory leak in worker pool")
        tmp_store.create_rca_result(rca)
        loaded = tmp_store.get_rca_result(rca.id)
        assert loaded is not None
        assert loaded.root_cause == "Memory leak in worker pool"

    def test_list_rca_by_issue(self, tmp_store):
        rca1 = RCAResult(health_issue_id="issue-A")
        rca2 = RCAResult(health_issue_id="issue-B")
        tmp_store.create_rca_result(rca1)
        tmp_store.create_rca_result(rca2)
        results = tmp_store.list_rca_results(health_issue_id="issue-A")
        assert len(results) == 1


class TestStoreCorruptedJSON:
    """Store should handle corrupted files gracefully."""

    def test_corrupted_json_returns_empty(self, tmp_path):
        store = HealthIssueStore(data_dir=str(tmp_path))
        # Write garbage to the file
        (tmp_path / "health_issues.json").write_text("{{{invalid json")
        assert store.list_issues() == []

    def test_non_list_json_returns_empty(self, tmp_path):
        store = HealthIssueStore(data_dir=str(tmp_path))
        (tmp_path / "health_issues.json").write_text('{"not": "a list"}')
        assert store.list_issues() == []


# ===================================================================
# 7. Model Serialisation Round-Trip
# ===================================================================

class TestModelSerialisation:
    """to_dict / from_dict round-trip."""

    def test_health_issue_round_trip(self):
        original = HealthIssue(
            resource_id="i-123",
            resource_type="ec2",
            severity="critical",
            status=HealthIssueStatus.INVESTIGATING,
            timeline=[{"event": "created", "ts": "2026-01-01T00:00:00+00:00"}],
        )
        restored = HealthIssue.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.status == HealthIssueStatus.INVESTIGATING
        assert restored.severity == "critical"
        assert len(restored.timeline) == 1

    def test_fix_plan_round_trip(self):
        original = FixPlan(
            risk_level=FixPlanRiskLevel.L3,
            status=FixPlanStatus.APPROVED,
            steps=[{"action": "restart", "target": "nginx"}],
        )
        restored = FixPlan.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.risk_level == FixPlanRiskLevel.L3
        assert restored.status == FixPlanStatus.APPROVED
        assert len(restored.steps) == 1

    def test_rca_result_round_trip(self):
        original = RCAResult(
            root_cause="OOM",
            confidence=0.95,
            contributing_factors=["memory_leak", "traffic_spike"],
            network_context={"vpc_id": "vpc-123"},
        )
        restored = RCAResult.from_dict(original.to_dict())
        assert restored.root_cause == "OOM"
        assert restored.confidence == 0.95
        assert restored.network_context == {"vpc_id": "vpc-123"}

    def test_health_issue_is_resolved(self):
        hi = HealthIssue(status=HealthIssueStatus.RESOLVED)
        assert hi.is_resolved() is True
        hi2 = HealthIssue(status=HealthIssueStatus.OPEN)
        assert hi2.is_resolved() is False
