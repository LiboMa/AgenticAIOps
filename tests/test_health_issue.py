"""
Tests for src/health_issue/ — HealthIssue 7-state lifecycle

Covers: models, lifecycle (transitions + approval gates), store, migration.
"""
import json
import os
import tempfile
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
    reject_fix_plan,
    transition,
)
from src.health_issue.store import HealthIssueStore
from src.health_issue.migration import (
    INCIDENT_STATUS_MIGRATION,
    ISSUE_STATUS_MIGRATION,
    migrate_incident,
    migrate_issue,
    _map_severity,
)


# ── Models ───────────────────────────────────────────────────


class TestHealthIssueModels:

    def test_health_issue_defaults(self):
        hi = HealthIssue()
        assert hi.status == HealthIssueStatus.OPEN
        assert hi.severity == "medium"
        assert hi.id  # UUID generated
        assert hi.detected_at  # timestamp set

    def test_health_issue_custom(self):
        hi = HealthIssue(
            resource_id="i-12345",
            resource_type="ec2",
            severity="critical",
            title="CPU spike",
        )
        assert hi.resource_id == "i-12345"
        assert hi.severity == "critical"

    def test_health_issue_to_dict(self):
        hi = HealthIssue(title="test")
        d = hi.to_dict()
        assert d["status"] == "open"
        assert d["title"] == "test"
        assert isinstance(d, dict)

    def test_health_issue_from_dict(self):
        d = {"id": "hi-001", "status": "investigating", "title": "test issue"}
        hi = HealthIssue.from_dict(d)
        assert hi.id == "hi-001"
        assert hi.status == HealthIssueStatus.INVESTIGATING

    def test_health_issue_roundtrip(self):
        hi = HealthIssue(title="roundtrip", severity="high")
        d = hi.to_dict()
        hi2 = HealthIssue.from_dict(d)
        assert hi2.title == hi.title
        assert hi2.severity == hi.severity
        assert hi2.id == hi.id

    def test_health_issue_is_resolved(self):
        hi = HealthIssue()
        assert hi.is_resolved() is False
        hi.status = HealthIssueStatus.RESOLVED
        assert hi.is_resolved() is True

    def test_health_issue_status_values(self):
        assert len(HealthIssueStatus) == 7
        assert HealthIssueStatus.OPEN.value == "open"
        assert HealthIssueStatus.RESOLVED.value == "resolved"

    def test_fix_plan_defaults(self):
        fp = FixPlan()
        assert fp.risk_level == FixPlanRiskLevel.L2
        assert fp.status == FixPlanStatus.DRAFT
        assert fp.id  # UUID generated

    def test_fix_plan_to_dict(self):
        fp = FixPlan(title="restart pod", risk_level=FixPlanRiskLevel.L1)
        d = fp.to_dict()
        assert d["risk_level"] == "L1"
        assert d["status"] == "draft"

    def test_fix_plan_from_dict(self):
        d = {"id": "fp-001", "risk_level": "L3", "status": "pending_approval"}
        fp = FixPlan.from_dict(d)
        assert fp.risk_level == FixPlanRiskLevel.L3
        assert fp.status == FixPlanStatus.PENDING_APPROVAL

    def test_fix_plan_roundtrip(self):
        fp = FixPlan(title="scale up", steps=[{"action": "kubectl scale"}])
        d = fp.to_dict()
        fp2 = FixPlan.from_dict(d)
        assert fp2.title == fp.title
        assert fp2.steps == fp.steps

    def test_rca_result_defaults(self):
        rca = RCAResult()
        assert rca.confidence == 0.0
        assert rca.id

    def test_rca_result_roundtrip(self):
        rca = RCAResult(
            root_cause="OOM kill",
            confidence=0.85,
            network_context={"anomalies": 2},
        )
        d = rca.to_dict()
        rca2 = RCAResult.from_dict(d)
        assert rca2.root_cause == "OOM kill"
        assert rca2.confidence == 0.85
        assert rca2.network_context == {"anomalies": 2}


# ── Lifecycle: State Transitions ─────────────────────────────


class TestLifecycleTransitions:

    def test_full_happy_path(self):
        """open → investigating → rci → fix_planned → fix_approved → fix_executed → resolved"""
        hi = HealthIssue()
        assert hi.status == HealthIssueStatus.OPEN

        transition(hi, HealthIssueStatus.INVESTIGATING)
        assert hi.status == HealthIssueStatus.INVESTIGATING

        transition(hi, HealthIssueStatus.ROOT_CAUSE_IDENTIFIED)
        assert hi.status == HealthIssueStatus.ROOT_CAUSE_IDENTIFIED

        transition(hi, HealthIssueStatus.FIX_PLANNED)
        assert hi.status == HealthIssueStatus.FIX_PLANNED

        transition(hi, HealthIssueStatus.FIX_APPROVED)
        assert hi.status == HealthIssueStatus.FIX_APPROVED

        transition(hi, HealthIssueStatus.FIX_EXECUTED)
        assert hi.status == HealthIssueStatus.FIX_EXECUTED

        transition(hi, HealthIssueStatus.RESOLVED)
        assert hi.status == HealthIssueStatus.RESOLVED
        assert hi.resolved_at is not None

    def test_open_to_investigating(self):
        hi = HealthIssue()
        assert can_transition(hi.status, HealthIssueStatus.INVESTIGATING) is True
        transition(hi, HealthIssueStatus.INVESTIGATING)
        assert hi.status == HealthIssueStatus.INVESTIGATING

    def test_open_to_resolved_direct(self):
        """Self-healed or false alarm"""
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.RESOLVED)
        assert hi.status == HealthIssueStatus.RESOLVED

    def test_investigating_to_open_retry(self):
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.INVESTIGATING)
        transition(hi, HealthIssueStatus.OPEN)
        assert hi.status == HealthIssueStatus.OPEN

    def test_root_cause_to_resolved_self_heal(self):
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.INVESTIGATING)
        transition(hi, HealthIssueStatus.ROOT_CAUSE_IDENTIFIED)
        transition(hi, HealthIssueStatus.RESOLVED)
        assert hi.status == HealthIssueStatus.RESOLVED

    def test_fix_executed_to_fix_planned_rollback(self):
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.INVESTIGATING)
        transition(hi, HealthIssueStatus.ROOT_CAUSE_IDENTIFIED)
        transition(hi, HealthIssueStatus.FIX_PLANNED)
        transition(hi, HealthIssueStatus.FIX_APPROVED)
        transition(hi, HealthIssueStatus.FIX_EXECUTED)
        # Rollback → re-plan
        transition(hi, HealthIssueStatus.FIX_PLANNED)
        assert hi.status == HealthIssueStatus.FIX_PLANNED

    def test_resolved_allows_reopen(self):
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.RESOLVED)
        # Rev 2: RESOLVED is no longer terminal — allows reopen to OPEN
        assert ALLOWED_TRANSITIONS[HealthIssueStatus.RESOLVED] == [HealthIssueStatus.OPEN]

    # ── Invalid transitions ──

    def test_open_to_fix_approved_invalid(self):
        hi = HealthIssue()
        assert can_transition(hi.status, HealthIssueStatus.FIX_APPROVED) is False
        with pytest.raises(ValueError, match="Invalid transition"):
            transition(hi, HealthIssueStatus.FIX_APPROVED)

    def test_open_to_fix_executed_invalid(self):
        hi = HealthIssue()
        with pytest.raises(ValueError):
            transition(hi, HealthIssueStatus.FIX_EXECUTED)

    def test_investigating_to_fix_planned_invalid(self):
        """Must go through root_cause_identified first"""
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.INVESTIGATING)
        with pytest.raises(ValueError):
            transition(hi, HealthIssueStatus.FIX_PLANNED)

    def test_fix_planned_to_resolved_invalid(self):
        """Must go through fix_approved → fix_executed first"""
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.INVESTIGATING)
        transition(hi, HealthIssueStatus.ROOT_CAUSE_IDENTIFIED)
        transition(hi, HealthIssueStatus.FIX_PLANNED)
        with pytest.raises(ValueError):
            transition(hi, HealthIssueStatus.RESOLVED)

    def test_resolved_to_open_invalid(self):
        """resolved is terminal"""
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError):
            transition(hi, HealthIssueStatus.OPEN)

    def test_can_transition_all_valid(self):
        """Verify every ALLOWED_TRANSITIONS entry works"""
        for from_s, targets in ALLOWED_TRANSITIONS.items():
            for to_s in targets:
                assert can_transition(from_s, to_s) is True

    def test_transition_sets_resolved_at(self):
        hi = HealthIssue()
        assert hi.resolved_at is None
        transition(hi, HealthIssueStatus.RESOLVED)
        assert hi.resolved_at is not None


# ── Lifecycle: FixPlan Approval Gates ────────────────────────


class TestFixPlanApproval:

    def test_l0_auto_approve(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L0, title="check status")
        result = create_fix_plan(hi, fp)
        assert result.status == FixPlanStatus.APPROVED
        assert result.approved_by == "system:auto_approve"
        assert result.approved_at is not None

    def test_l1_auto_approve(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L1, title="config change")
        result = create_fix_plan(hi, fp)
        assert result.status == FixPlanStatus.APPROVED

    def test_l2_requires_approval(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L2, title="restart service")
        result = create_fix_plan(hi, fp)
        assert result.status == FixPlanStatus.PENDING_APPROVAL

    def test_l3_requires_approval(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L3, title="failover")
        result = create_fix_plan(hi, fp)
        assert result.status == FixPlanStatus.PENDING_APPROVAL

    def test_l2_approve_success(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(hi, fp)
        approve_fix_plan(fp, "admin")
        assert fp.status == FixPlanStatus.APPROVED
        assert fp.approved_by == "admin"

    def test_l3_approve_success(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L3)
        create_fix_plan(hi, fp)
        approve_fix_plan(fp, "senior_admin", is_senior=True, double_confirmed=True)
        assert fp.status == FixPlanStatus.APPROVED

    def test_l3_approve_not_senior_fails(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L3)
        create_fix_plan(hi, fp)
        with pytest.raises(ValueError, match="senior"):
            approve_fix_plan(fp, "junior", is_senior=False, double_confirmed=True)

    def test_l3_approve_not_double_confirmed_fails(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L3)
        create_fix_plan(hi, fp)
        with pytest.raises(ValueError, match="double confirmation"):
            approve_fix_plan(fp, "senior_admin", is_senior=True, double_confirmed=False)

    def test_approve_already_approved_fails(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L0)
        create_fix_plan(hi, fp)  # auto-approved
        with pytest.raises(ValueError, match="pending_approval"):
            approve_fix_plan(fp, "admin")

    def test_reject_fix_plan(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(hi, fp)
        reject_fix_plan(fp, "too risky")
        assert fp.status == FixPlanStatus.REJECTED
        assert fp.rejected_reason == "too risky"

    def test_reject_non_pending_fails(self):
        fp = FixPlan(status=FixPlanStatus.DRAFT)
        with pytest.raises(ValueError, match="pending_approval"):
            reject_fix_plan(fp, "reason")

    def test_create_fix_plan_links_to_issue(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(hi, fp)
        assert fp.health_issue_id == hi.id
        assert fp.id in hi.fix_plan_ids

    def test_create_fix_plan_no_duplicate_link(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(hi, fp)
        create_fix_plan(hi, fp)  # call again
        assert hi.fix_plan_ids.count(fp.id) == 1


# ── Store ────────────────────────────────────────────────────


class TestStore:

    @pytest.fixture
    def store(self, tmp_path):
        return HealthIssueStore(data_dir=str(tmp_path))

    def test_create_and_get_issue(self, store):
        hi = HealthIssue(title="test issue")
        store.create_issue(hi)
        loaded = store.get_issue(hi.id)
        assert loaded is not None
        assert loaded.title == "test issue"
        assert loaded.id == hi.id

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_issue("nope") is None

    def test_update_issue(self, store):
        hi = HealthIssue(title="v1")
        store.create_issue(hi)
        hi.title = "v2"
        hi.status = HealthIssueStatus.INVESTIGATING
        store.update_issue(hi)
        loaded = store.get_issue(hi.id)
        assert loaded.title == "v2"
        assert loaded.status == HealthIssueStatus.INVESTIGATING

    def test_update_nonexistent_raises(self, store):
        hi = HealthIssue(id="ghost")
        with pytest.raises(KeyError):
            store.update_issue(hi)

    def test_delete_issue(self, store):
        hi = HealthIssue()
        store.create_issue(hi)
        assert store.delete_issue(hi.id) is True
        assert store.get_issue(hi.id) is None

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete_issue("nope") is False

    def test_list_issues_no_filter(self, store):
        store.create_issue(HealthIssue(title="a"))
        store.create_issue(HealthIssue(title="b"))
        issues = store.list_issues()
        assert len(issues) == 2

    def test_list_issues_filter_status(self, store):
        hi1 = HealthIssue(title="open issue")
        hi2 = HealthIssue(title="resolved issue")
        hi2.status = HealthIssueStatus.RESOLVED
        store.create_issue(hi1)
        store.create_issue(hi2)
        open_issues = store.list_issues(status="open")
        assert len(open_issues) == 1
        assert open_issues[0].title == "open issue"

    def test_list_issues_filter_severity(self, store):
        store.create_issue(HealthIssue(severity="critical"))
        store.create_issue(HealthIssue(severity="low"))
        critical = store.list_issues(severity="critical")
        assert len(critical) == 1

    def test_fix_plan_crud(self, store):
        fp = FixPlan(title="restart")
        store.create_fix_plan(fp)
        loaded = store.get_fix_plan(fp.id)
        assert loaded.title == "restart"

        fp.title = "restart v2"
        store.update_fix_plan(fp)
        loaded2 = store.get_fix_plan(fp.id)
        assert loaded2.title == "restart v2"

    def test_list_fix_plans_by_issue(self, store):
        fp1 = FixPlan(health_issue_id="hi-001", title="plan A")
        fp2 = FixPlan(health_issue_id="hi-002", title="plan B")
        store.create_fix_plan(fp1)
        store.create_fix_plan(fp2)
        plans = store.list_fix_plans(health_issue_id="hi-001")
        assert len(plans) == 1
        assert plans[0].title == "plan A"

    def test_rca_result_crud(self, store):
        rca = RCAResult(root_cause="memory leak", confidence=0.9)
        store.create_rca_result(rca)
        loaded = store.get_rca_result(rca.id)
        assert loaded.root_cause == "memory leak"
        assert loaded.confidence == 0.9

    def test_list_rca_results_by_issue(self, store):
        rca1 = RCAResult(health_issue_id="hi-001", root_cause="cause A")
        rca2 = RCAResult(health_issue_id="hi-002", root_cause="cause B")
        store.create_rca_result(rca1)
        store.create_rca_result(rca2)
        results = store.list_rca_results(health_issue_id="hi-001")
        assert len(results) == 1
        assert results[0].root_cause == "cause A"

    def test_corrupted_file_returns_empty(self, store):
        """Graceful handling of corrupted JSON"""
        store._issues_file.write_text("not json", encoding="utf-8")
        issues = store.list_issues()
        assert issues == []


# ── Migration ────────────────────────────────────────────────


class TestMigration:

    def test_issue_status_mapping_complete(self):
        """All 8 IssueStatus values have a mapping"""
        expected_keys = {"detected", "analyzing", "pending_fix", "fixing",
                         "fixed", "failed", "acknowledged", "closed"}
        assert set(ISSUE_STATUS_MIGRATION.keys()) == expected_keys

    def test_incident_status_mapping_complete(self):
        """All 9 IncidentStatus values have a mapping"""
        expected_keys = {"triggered", "collecting", "analyzing", "sop_matched",
                         "safety_check", "executing", "waiting_approval",
                         "completed", "failed"}
        assert set(INCIDENT_STATUS_MIGRATION.keys()) == expected_keys

    def test_migrate_issue_detected(self):
        hi = migrate_issue({"status": "detected", "pod_name": "web-1"})
        assert hi.status == HealthIssueStatus.OPEN
        assert hi.resource_id == "web-1"

    def test_migrate_issue_analyzing(self):
        hi = migrate_issue({"status": "analyzing"})
        assert hi.status == HealthIssueStatus.INVESTIGATING

    def test_migrate_issue_fixed(self):
        hi = migrate_issue({"status": "fixed", "resolved_at": "2026-02-25T00:00:00Z"})
        assert hi.status == HealthIssueStatus.RESOLVED
        assert hi.resolved_at == "2026-02-25T00:00:00Z"

    def test_migrate_issue_failed_reopens(self):
        hi = migrate_issue({"status": "failed"})
        assert hi.status == HealthIssueStatus.OPEN

    def test_migrate_issue_unknown_status(self):
        hi = migrate_issue({"status": "unknown_garbage"})
        assert hi.status == HealthIssueStatus.OPEN  # fallback

    def test_migrate_incident_triggered(self):
        hi = migrate_incident({
            "status": "triggered",
            "trigger_type": "cloudwatch_alarm",
            "trigger_data": {"alarm_name": "CPU-High", "resource_id": "i-123"},
        })
        assert hi.status == HealthIssueStatus.OPEN
        assert hi.alarm_name == "CPU-High"
        assert hi.resource_id == "i-123"

    def test_migrate_incident_sop_matched(self):
        hi = migrate_incident({"status": "sop_matched"})
        assert hi.status == HealthIssueStatus.ROOT_CAUSE_IDENTIFIED

    def test_migrate_incident_waiting_approval(self):
        hi = migrate_incident({"status": "waiting_approval"})
        assert hi.status == HealthIssueStatus.FIX_PLANNED

    def test_migrate_incident_completed(self):
        hi = migrate_incident({
            "status": "completed",
            "completed_at": "2026-02-25T12:00:00Z",
        })
        assert hi.status == HealthIssueStatus.RESOLVED
        assert hi.resolved_at == "2026-02-25T12:00:00Z"

    def test_migrate_incident_with_rca(self):
        hi = migrate_incident({
            "status": "analyzing",
            "rca_result": {"id": "rca-001", "root_cause": "OOM"},
        })
        assert "rca-001" in hi.rca_result_ids

    def test_map_severity_valid(self):
        assert _map_severity("critical") == "critical"
        assert _map_severity("HIGH") == "high"
        assert _map_severity("Medium") == "medium"
        assert _map_severity("low") == "low"

    def test_map_severity_numeric(self):
        assert _map_severity("1") == "critical"
        assert _map_severity("2") == "high"
        assert _map_severity("3") == "medium"
        assert _map_severity("4") == "low"

    def test_map_severity_none_default(self):
        assert _map_severity(None) == "medium"
        assert _map_severity("") == "medium"
        assert _map_severity("unknown") == "medium"
