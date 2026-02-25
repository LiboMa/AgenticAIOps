"""
Tests for HealthIssue 7-State Lifecycle Module

Coverage: ~57 tests
  - State transitions: happy path, shortcuts, rollbacks, illegal, reopen
  - FixPlan approval gates: L0-L3, reject, edge cases
  - Store CRUD: create/get/update/list/filter
  - Migration: IssueStatus (8) + IncidentStatus (9) mapping
  - force_close + Timeline
"""

import json
import os
import tempfile
from itertools import product

import pytest

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
    force_close,
    reject_fix_plan,
    reopen,
    transition,
)
from src.health_issue.store import HealthIssueStore
from src.health_issue.migration import (
    INCIDENT_STATUS_MIGRATION,
    ISSUE_STATUS_MIGRATION,
    migrate_incident,
    migrate_issue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_issue(**kwargs) -> HealthIssue:
    defaults = dict(title="test-issue", resource_id="i-123", resource_type="ec2")
    defaults.update(kwargs)
    return HealthIssue(**defaults)


def _walk_to(issue: HealthIssue, target: HealthIssueStatus) -> HealthIssue:
    """Walk an issue through the happy path to *target*."""
    path = {
        HealthIssueStatus.OPEN: [],
        HealthIssueStatus.INVESTIGATING: [HealthIssueStatus.INVESTIGATING],
        HealthIssueStatus.ROOT_CAUSE_IDENTIFIED: [
            HealthIssueStatus.INVESTIGATING,
            HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
        ],
        HealthIssueStatus.FIX_PLANNED: [
            HealthIssueStatus.INVESTIGATING,
            HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
            HealthIssueStatus.FIX_PLANNED,
        ],
        HealthIssueStatus.FIX_APPROVED: [
            HealthIssueStatus.INVESTIGATING,
            HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
            HealthIssueStatus.FIX_PLANNED,
            HealthIssueStatus.FIX_APPROVED,
        ],
        HealthIssueStatus.FIX_EXECUTED: [
            HealthIssueStatus.INVESTIGATING,
            HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
            HealthIssueStatus.FIX_PLANNED,
            HealthIssueStatus.FIX_APPROVED,
            HealthIssueStatus.FIX_EXECUTED,
        ],
        HealthIssueStatus.RESOLVED: [
            HealthIssueStatus.INVESTIGATING,
            HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
            HealthIssueStatus.FIX_PLANNED,
            HealthIssueStatus.FIX_APPROVED,
            HealthIssueStatus.FIX_EXECUTED,
            HealthIssueStatus.RESOLVED,
        ],
    }
    for step in path[target]:
        transition(issue, step)
    return issue


# ============================================================================
# 1. State Transition Tests
# ============================================================================

class TestStateTransitionsHappyPath:
    """7 happy-path transitions through the full lifecycle."""

    @pytest.mark.parametrize(
        "from_s, to_s",
        [
            (HealthIssueStatus.OPEN, HealthIssueStatus.INVESTIGATING),
            (HealthIssueStatus.INVESTIGATING, HealthIssueStatus.ROOT_CAUSE_IDENTIFIED),
            (HealthIssueStatus.ROOT_CAUSE_IDENTIFIED, HealthIssueStatus.FIX_PLANNED),
            (HealthIssueStatus.FIX_PLANNED, HealthIssueStatus.FIX_APPROVED),
            (HealthIssueStatus.FIX_APPROVED, HealthIssueStatus.FIX_EXECUTED),
            (HealthIssueStatus.FIX_EXECUTED, HealthIssueStatus.RESOLVED),
            (HealthIssueStatus.RESOLVED, HealthIssueStatus.OPEN),  # reopen
        ],
    )
    def test_happy_path(self, from_s, to_s):
        issue = _make_issue()
        _walk_to(issue, from_s)
        if from_s == HealthIssueStatus.RESOLVED and to_s == HealthIssueStatus.OPEN:
            transition(issue, to_s, note="recurrence detected")
        else:
            transition(issue, to_s)
        assert issue.status == to_s

    def test_full_lifecycle_open_to_resolved(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.RESOLVED)
        assert issue.status == HealthIssueStatus.RESOLVED
        assert issue.resolved_at is not None


class TestStateTransitionsShortcuts:
    """Shortcut paths: open→resolved, root_cause_identified→resolved."""

    def test_open_to_resolved(self):
        issue = _make_issue()
        transition(issue, HealthIssueStatus.RESOLVED)
        assert issue.status == HealthIssueStatus.RESOLVED
        assert issue.resolved_at is not None

    def test_rci_to_resolved_self_heal(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.ROOT_CAUSE_IDENTIFIED)
        transition(issue, HealthIssueStatus.RESOLVED)
        assert issue.status == HealthIssueStatus.RESOLVED


class TestStateTransitionsRollback:
    """Rollback paths: investigating→open, fix_executed→fix_planned."""

    def test_investigating_to_open(self):
        issue = _make_issue()
        transition(issue, HealthIssueStatus.INVESTIGATING)
        transition(issue, HealthIssueStatus.OPEN)
        assert issue.status == HealthIssueStatus.OPEN

    def test_fix_executed_to_fix_planned(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.FIX_EXECUTED)
        transition(issue, HealthIssueStatus.FIX_PLANNED)
        assert issue.status == HealthIssueStatus.FIX_PLANNED


class TestStateTransitionsIllegal:
    """Parametrised illegal transitions — every (from, to) pair NOT in ALLOWED_TRANSITIONS."""

    @staticmethod
    def _illegal_pairs():
        all_statuses = list(HealthIssueStatus)
        for from_s in all_statuses:
            allowed = ALLOWED_TRANSITIONS.get(from_s, [])
            for to_s in all_statuses:
                if to_s not in allowed and from_s != to_s:
                    yield from_s, to_s

    @pytest.mark.parametrize("from_s, to_s", list(_illegal_pairs.__func__()))
    def test_illegal_transition_raises(self, from_s, to_s):
        issue = _make_issue()
        _walk_to(issue, from_s)
        with pytest.raises(ValueError, match="Invalid transition"):
            if from_s == HealthIssueStatus.RESOLVED and to_s == HealthIssueStatus.OPEN:
                # This is actually legal — skip via allowed check
                pytest.skip("RESOLVED→OPEN is legal")
            transition(issue, to_s)


class TestStateTransitionsReopen:
    """Reopen (RESOLVED → OPEN) with note validation."""

    def test_reopen_with_note(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.RESOLVED)
        reopen(issue, note="issue recurred")
        assert issue.status == HealthIssueStatus.OPEN
        assert issue.resolved_at is None
        reopen_entry = issue.timeline[-1]
        assert reopen_entry["action"] == "transition"
        assert reopen_entry["from"] == "resolved"
        assert reopen_entry["to"] == "open"
        assert reopen_entry["note"] == "issue recurred"

    def test_reopen_empty_note_rejected(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError, match="non-empty note"):
            reopen(issue, note="")

    def test_reopen_none_note_rejected(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError, match="non-empty note"):
            transition(issue, HealthIssueStatus.OPEN, note=None)

    def test_reopen_whitespace_only_rejected(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError, match="non-empty note"):
            reopen(issue, note="   ")

    def test_reopen_not_resolved_raises(self):
        issue = _make_issue()
        transition(issue, HealthIssueStatus.INVESTIGATING)
        with pytest.raises(ValueError, match="not 'resolved'"):
            reopen(issue, note="try reopen")

    def test_reopen_clears_resolved_at(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.RESOLVED)
        assert issue.resolved_at is not None
        reopen(issue, note="came back")
        assert issue.resolved_at is None


class TestForceClose:
    """force_close bypasses normal transitions, requires permission."""

    def test_force_close_with_permission(self):
        issue = _make_issue()
        transition(issue, HealthIssueStatus.INVESTIGATING)
        force_close(issue, actor="admin", note="false alarm", has_permission=True)
        assert issue.status == HealthIssueStatus.RESOLVED
        assert issue.resolved_at is not None
        assert any(e["action"] == "force_close" for e in issue.timeline)

    def test_force_close_without_permission_raises(self):
        issue = _make_issue()
        with pytest.raises(PermissionError, match="elevated permission"):
            force_close(issue, actor="intern", has_permission=False)

    def test_force_close_timeline_entry(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.FIX_EXECUTED)
        force_close(issue, actor="senior-ops", note="stale issue", has_permission=True)
        entry = [e for e in issue.timeline if e["action"] == "force_close"]
        assert len(entry) == 1
        assert entry[0]["actor"] == "senior-ops"
        assert entry[0]["from"] == "fix_executed"
        assert entry[0]["to"] == "resolved"
        assert entry[0]["note"] == "stale issue"


class TestTimeline:
    """Timeline audit trail on every transition."""

    def test_timeline_records_all_transitions(self):
        issue = _make_issue()
        _walk_to(issue, HealthIssueStatus.RESOLVED)
        # open→investigating→rci→fp→fa→fe→resolved = 6 transitions
        assert len(issue.timeline) == 6
        assert issue.timeline[0]["from"] == "open"
        assert issue.timeline[-1]["to"] == "resolved"

    def test_timeline_includes_actor(self):
        issue = _make_issue()
        transition(issue, HealthIssueStatus.INVESTIGATING, actor="agent-1")
        assert issue.timeline[0]["actor"] == "agent-1"

    def test_timeline_survives_serialisation(self):
        issue = _make_issue()
        transition(issue, HealthIssueStatus.INVESTIGATING, note="test")
        d = issue.to_dict()
        restored = HealthIssue.from_dict(d)
        assert len(restored.timeline) == 1
        assert restored.timeline[0]["note"] == "test"


# ============================================================================
# 2. FixPlan Approval Gate Tests
# ============================================================================

class TestFixPlanAutoApproval:
    """L0/L1 auto-approve."""

    @pytest.mark.parametrize("risk", [FixPlanRiskLevel.L0, FixPlanRiskLevel.L1])
    def test_auto_approve(self, risk):
        issue = _make_issue()
        plan = FixPlan(risk_level=risk, title="read-only check")
        create_fix_plan(issue, plan)
        assert plan.status == FixPlanStatus.APPROVED
        assert plan.approved_by == "system:auto_approve"
        assert plan.approved_at is not None
        assert plan.id in issue.fix_plan_ids


class TestFixPlanHumanApproval:
    """L2 human approval."""

    def test_l2_requires_approval(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2, title="config change")
        create_fix_plan(issue, plan)
        assert plan.status == FixPlanStatus.PENDING_APPROVAL

    def test_l2_approve(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(issue, plan)
        approve_fix_plan(plan, "ops-user")
        assert plan.status == FixPlanStatus.APPROVED
        assert plan.approved_by == "ops-user"

    def test_l2_approve_without_senior_ok(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(issue, plan)
        approve_fix_plan(plan, "junior-ops", is_senior=False)
        assert plan.status == FixPlanStatus.APPROVED


class TestFixPlanL3Approval:
    """L3 senior + double confirmation."""

    def test_l3_full_approval(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L3, title="rds failover")
        create_fix_plan(issue, plan)
        approve_fix_plan(plan, "senior-dba", is_senior=True, double_confirmed=True)
        assert plan.status == FixPlanStatus.APPROVED

    def test_l3_no_senior_rejected(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L3)
        create_fix_plan(issue, plan)
        with pytest.raises(ValueError, match="senior approver"):
            approve_fix_plan(plan, "junior", is_senior=False, double_confirmed=True)

    def test_l3_no_double_confirm_rejected(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L3)
        create_fix_plan(issue, plan)
        with pytest.raises(ValueError, match="double confirmation"):
            approve_fix_plan(plan, "senior", is_senior=True, double_confirmed=False)


class TestFixPlanReject:
    """Reject flow."""

    def test_reject_pending(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(issue, plan)
        reject_fix_plan(plan, "too risky")
        assert plan.status == FixPlanStatus.REJECTED
        assert plan.rejected_reason == "too risky"

    def test_reject_already_approved_raises(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L0)
        create_fix_plan(issue, plan)  # auto-approved
        with pytest.raises(ValueError, match="pending_approval"):
            reject_fix_plan(plan, "nope")


class TestFixPlanEdgeCases:
    """Edge cases: empty steps, no rollback, duplicate approve."""

    def test_empty_steps_allowed(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L1, steps=[])
        create_fix_plan(issue, plan)
        assert plan.status == FixPlanStatus.APPROVED

    def test_no_rollback_plan_allowed(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2, rollback_plan=[])
        create_fix_plan(issue, plan)
        assert plan.status == FixPlanStatus.PENDING_APPROVAL

    def test_duplicate_approve_raises(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(issue, plan)
        approve_fix_plan(plan, "ops")
        with pytest.raises(ValueError, match="pending_approval"):
            approve_fix_plan(plan, "ops-again")

    def test_approve_draft_raises(self):
        plan = FixPlan(risk_level=FixPlanRiskLevel.L2)
        # status is DRAFT (not yet passed through create_fix_plan)
        with pytest.raises(ValueError, match="pending_approval"):
            approve_fix_plan(plan, "ops")

    def test_plan_linked_to_issue(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L1)
        create_fix_plan(issue, plan)
        assert plan.health_issue_id == issue.id
        assert plan.id in issue.fix_plan_ids

    def test_duplicate_link_idempotent(self):
        issue = _make_issue()
        plan = FixPlan(risk_level=FixPlanRiskLevel.L1)
        create_fix_plan(issue, plan)
        create_fix_plan(issue, plan)  # second call
        assert issue.fix_plan_ids.count(plan.id) == 1


# ============================================================================
# 3. Store CRUD Tests
# ============================================================================

class TestHealthIssueStore:
    """JSON-backed store CRUD."""

    @pytest.fixture
    def store(self, tmp_path):
        return HealthIssueStore(data_dir=str(tmp_path))

    def test_create_and_get_issue(self, store):
        issue = _make_issue(title="store test")
        store.create_issue(issue)
        got = store.get_issue(issue.id)
        assert got is not None
        assert got.title == "store test"
        assert got.id == issue.id

    def test_update_issue(self, store):
        issue = _make_issue()
        store.create_issue(issue)
        issue.severity = "critical"
        store.update_issue(issue)
        got = store.get_issue(issue.id)
        assert got.severity == "critical"

    def test_list_issues_filter_status(self, store):
        i1 = _make_issue(title="open1")
        i2 = _make_issue(title="resolved1")
        store.create_issue(i1)
        i2.status = HealthIssueStatus.RESOLVED
        store.create_issue(i2)
        open_issues = store.list_issues(status="open")
        assert len(open_issues) == 1
        assert open_issues[0].title == "open1"

    def test_list_issues_filter_severity(self, store):
        i1 = _make_issue(severity="critical")
        i2 = _make_issue(severity="low")
        store.create_issue(i1)
        store.create_issue(i2)
        crit = store.list_issues(severity="critical")
        assert len(crit) == 1

    def test_delete_issue(self, store):
        issue = _make_issue()
        store.create_issue(issue)
        assert store.delete_issue(issue.id) is True
        assert store.get_issue(issue.id) is None

    def test_delete_nonexistent(self, store):
        assert store.delete_issue("no-such-id") is False

    def test_get_nonexistent(self, store):
        assert store.get_issue("no-such-id") is None

    def test_fix_plan_crud(self, store):
        plan = FixPlan(health_issue_id="hi-1", title="restart pod")
        store.create_fix_plan(plan)
        got = store.get_fix_plan(plan.id)
        assert got.title == "restart pod"
        plans = store.list_fix_plans(health_issue_id="hi-1")
        assert len(plans) == 1

    def test_rca_result_crud(self, store):
        rca = RCAResult(health_issue_id="hi-1", root_cause="OOM")
        store.create_rca_result(rca)
        got = store.get_rca_result(rca.id)
        assert got.root_cause == "OOM"
        results = store.list_rca_results(health_issue_id="hi-1")
        assert len(results) == 1

    def test_corrupted_json_returns_empty(self, store):
        # Write corrupted JSON to health_issues file
        path = store._issues_file
        with open(path, "w") as f:
            f.write("{not valid json")
        assert store.list_issues() == []

    def test_missing_fields_handled(self, store):
        # Write minimal JSON
        path = store._issues_file
        with open(path, "w") as f:
            json.dump([{"id": "bare-min"}], f)
        issues = store.list_issues()
        assert len(issues) == 1
        assert issues[0].id == "bare-min"
        assert issues[0].status == HealthIssueStatus.OPEN


# ============================================================================
# 4. Migration Tests
# ============================================================================

class TestMigration:
    """IssueStatus (8) + IncidentStatus (9) → HealthIssueStatus mapping."""

    @pytest.mark.parametrize(
        "old_status, expected",
        list(ISSUE_STATUS_MIGRATION.items()),
    )
    def test_issue_status_migration(self, old_status, expected):
        hi = migrate_issue({"status": old_status, "id": "iss-1"})
        assert hi.status.value == expected
        assert hi.issue_id == "iss-1"

    @pytest.mark.parametrize(
        "old_status, expected",
        list(INCIDENT_STATUS_MIGRATION.items()),
    )
    def test_incident_status_migration(self, old_status, expected):
        hi = migrate_incident({
            "status": old_status,
            "incident_id": "inc-1",
            "trigger_data": {},
        })
        assert hi.status.value == expected
        assert hi.incident_id == "inc-1"

    def test_migrate_issue_carries_fields(self):
        hi = migrate_issue({
            "status": "analyzing",
            "id": "iss-99",
            "pod_name": "web-abc",
            "issue_type": "oom_killed",
            "severity": "high",
            "details": "container OOM",
        })
        assert hi.resource_id == "web-abc"
        assert hi.resource_type == "oom_killed"
        assert hi.severity == "high"
        assert hi.description == "container OOM"

    def test_migrate_incident_carries_rca(self):
        hi = migrate_incident({
            "status": "completed",
            "incident_id": "inc-42",
            "trigger_data": {"alarm_name": "HighCPU"},
            "rca_result": {"id": "rca-7"},
        })
        assert hi.status == HealthIssueStatus.RESOLVED
        assert "rca-7" in hi.rca_result_ids

    def test_unknown_status_defaults_to_open(self):
        hi = migrate_issue({"status": "nonexistent_state"})
        assert hi.status == HealthIssueStatus.OPEN

    def test_migration_map_completeness(self):
        """All 8 IssueStatus values are covered."""
        expected_issue_keys = {
            "detected", "analyzing", "pending_fix", "fixing",
            "fixed", "failed", "acknowledged", "closed",
        }
        assert set(ISSUE_STATUS_MIGRATION.keys()) == expected_issue_keys

        expected_incident_keys = {
            "triggered", "collecting", "analyzing", "sop_matched",
            "safety_check", "executing", "waiting_approval",
            "completed", "failed",
        }
        assert set(INCIDENT_STATUS_MIGRATION.keys()) == expected_incident_keys


# ============================================================================
# 5. Model Serialisation Tests
# ============================================================================

class TestModelSerialisation:
    """to_dict / from_dict round-trip."""

    def test_health_issue_round_trip(self):
        issue = _make_issue(title="round-trip")
        transition(issue, HealthIssueStatus.INVESTIGATING, note="test")
        d = issue.to_dict()
        restored = HealthIssue.from_dict(d)
        assert restored.title == "round-trip"
        assert restored.status == HealthIssueStatus.INVESTIGATING
        assert len(restored.timeline) == 1

    def test_fix_plan_round_trip(self):
        plan = FixPlan(
            title="restart",
            risk_level=FixPlanRiskLevel.L3,
            status=FixPlanStatus.PENDING_APPROVAL,
            steps=[{"action": "kubectl rollout restart"}],
        )
        d = plan.to_dict()
        assert d["risk_level"] == "L3"
        assert d["status"] == "pending_approval"
        restored = FixPlan.from_dict(d)
        assert restored.risk_level == FixPlanRiskLevel.L3
        assert len(restored.steps) == 1

    def test_rca_result_round_trip(self):
        rca = RCAResult(
            root_cause="memory leak",
            confidence=0.92,
            contributing_factors=["high traffic"],
        )
        d = rca.to_dict()
        restored = RCAResult.from_dict(d)
        assert restored.confidence == 0.92
        assert "high traffic" in restored.contributing_factors


# ============================================================================
# 6. can_transition utility
# ============================================================================

class TestCanTransition:
    """Verify can_transition matches ALLOWED_TRANSITIONS dict."""

    def test_all_allowed_return_true(self):
        for from_s, targets in ALLOWED_TRANSITIONS.items():
            for to_s in targets:
                assert can_transition(from_s, to_s), f"{from_s}→{to_s} should be True"

    def test_self_transition_false(self):
        for s in HealthIssueStatus:
            assert not can_transition(s, s), f"{s}→{s} should be False"

    def test_transition_completeness(self):
        """Every HealthIssueStatus has an entry in ALLOWED_TRANSITIONS."""
        for s in HealthIssueStatus:
            assert s in ALLOWED_TRANSITIONS
