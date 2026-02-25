"""[tester] HealthIssue 7-state lifecycle tests.

Covers: models, state transitions, FixPlan approval gates, store persistence,
migration from legacy IssueStatus/IncidentStatus, and API endpoints.
"""
import json
import os
import tempfile

import pytest

from src.health_issue.models import (
    FixPlan, FixPlanRiskLevel, FixPlanStatus,
    HealthIssue, HealthIssueStatus, RCAResult,
)
from src.health_issue.lifecycle import (
    ALLOWED_TRANSITIONS, approve_fix_plan, can_transition,
    create_fix_plan, reject_fix_plan, transition,
)
from src.health_issue.store import HealthIssueStore
from src.health_issue.migration import (
    INCIDENT_STATUS_MIGRATION, ISSUE_STATUS_MIGRATION,
    migrate_incident, migrate_issue, _map_severity,
)


# ── Model tests ─────────────────────────────────────────────────────


class TestModels:
    def test_health_issue_defaults(self):
        hi = HealthIssue()
        assert hi.status == HealthIssueStatus.OPEN
        assert hi.severity == "medium"
        assert hi.rca_result_ids == []
        assert hi.fix_plan_ids == []
        assert hi.id  # UUID generated
        assert hi.detected_at  # timestamp generated

    def test_health_issue_to_dict_roundtrip(self):
        hi = HealthIssue(resource_id="i-123", title="CPU spike", severity="high")
        d = hi.to_dict()
        assert d["status"] == "open"
        assert d["resource_id"] == "i-123"
        restored = HealthIssue.from_dict(d)
        assert restored.resource_id == "i-123"
        assert restored.status == HealthIssueStatus.OPEN

    def test_health_issue_is_resolved(self):
        hi = HealthIssue()
        assert hi.is_resolved() is False
        hi.status = HealthIssueStatus.RESOLVED
        assert hi.is_resolved() is True

    def test_fix_plan_defaults(self):
        fp = FixPlan()
        assert fp.status == FixPlanStatus.DRAFT
        assert fp.risk_level == FixPlanRiskLevel.L2
        assert fp.steps == []
        assert fp.approved_by is None

    def test_fix_plan_to_dict_roundtrip(self):
        fp = FixPlan(title="Restart pod", risk_level=FixPlanRiskLevel.L1)
        d = fp.to_dict()
        assert d["risk_level"] == "L1"
        restored = FixPlan.from_dict(d)
        assert restored.risk_level == FixPlanRiskLevel.L1
        assert restored.title == "Restart pod"

    def test_rca_result_defaults(self):
        rca = RCAResult(root_cause="OOM killer")
        assert rca.confidence == 0.0
        assert rca.network_context is None
        assert rca.id  # UUID generated

    def test_rca_result_roundtrip(self):
        rca = RCAResult(root_cause="Disk full", confidence=0.95,
                        contributing_factors=["log rotation disabled"],
                        network_context={"vpc_id": "vpc-001"})
        d = rca.to_dict()
        restored = RCAResult.from_dict(d)
        assert restored.root_cause == "Disk full"
        assert restored.confidence == 0.95
        assert restored.network_context == {"vpc_id": "vpc-001"}


# ── State transition tests ──────────────────────────────────────────


class TestStateTransitions:
    """Test the 7-state lifecycle state machine."""

    def test_full_happy_path(self):
        """open → investigating → rci → fix_planned → fix_approved → fix_executed → resolved"""
        hi = HealthIssue()
        path = [
            HealthIssueStatus.INVESTIGATING,
            HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
            HealthIssueStatus.FIX_PLANNED,
            HealthIssueStatus.FIX_APPROVED,
            HealthIssueStatus.FIX_EXECUTED,
            HealthIssueStatus.RESOLVED,
        ]
        for status in path:
            transition(hi, status)
        assert hi.status == HealthIssueStatus.RESOLVED
        assert hi.resolved_at is not None

    def test_open_to_investigating(self):
        hi = HealthIssue()
        assert can_transition(hi.status, HealthIssueStatus.INVESTIGATING) is True
        transition(hi, HealthIssueStatus.INVESTIGATING)
        assert hi.status == HealthIssueStatus.INVESTIGATING

    def test_open_to_resolved_direct(self):
        """Self-heal: open → resolved directly."""
        hi = HealthIssue()
        transition(hi, HealthIssueStatus.RESOLVED)
        assert hi.is_resolved()

    def test_investigating_to_open_retry(self):
        """Retry: investigating → open."""
        hi = HealthIssue(status=HealthIssueStatus.INVESTIGATING)
        transition(hi, HealthIssueStatus.OPEN)
        assert hi.status == HealthIssueStatus.OPEN

    def test_rci_to_resolved_self_heal(self):
        """Self-heal after RCA: root_cause_identified → resolved."""
        hi = HealthIssue(status=HealthIssueStatus.ROOT_CAUSE_IDENTIFIED)
        transition(hi, HealthIssueStatus.RESOLVED)
        assert hi.is_resolved()

    def test_fix_executed_to_fix_planned_rollback(self):
        """Rollback: fix_executed → fix_planned (re-plan)."""
        hi = HealthIssue(status=HealthIssueStatus.FIX_EXECUTED)
        transition(hi, HealthIssueStatus.FIX_PLANNED)
        assert hi.status == HealthIssueStatus.FIX_PLANNED

    def test_resolved_is_terminal(self):
        """No transitions from resolved."""
        hi = HealthIssue(status=HealthIssueStatus.RESOLVED)
        assert ALLOWED_TRANSITIONS[HealthIssueStatus.RESOLVED] == []
        assert can_transition(hi.status, HealthIssueStatus.OPEN) is False

    # Invalid transitions
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
        """Must go through root_cause_identified first."""
        hi = HealthIssue(status=HealthIssueStatus.INVESTIGATING)
        with pytest.raises(ValueError):
            transition(hi, HealthIssueStatus.FIX_PLANNED)

    def test_fix_planned_to_resolved_invalid(self):
        """Must go through approved → executed first."""
        hi = HealthIssue(status=HealthIssueStatus.FIX_PLANNED)
        with pytest.raises(ValueError):
            transition(hi, HealthIssueStatus.RESOLVED)

    def test_fix_approved_to_open_invalid(self):
        hi = HealthIssue(status=HealthIssueStatus.FIX_APPROVED)
        with pytest.raises(ValueError):
            transition(hi, HealthIssueStatus.OPEN)

    def test_resolved_at_set_on_resolve(self):
        hi = HealthIssue()
        assert hi.resolved_at is None
        transition(hi, HealthIssueStatus.RESOLVED)
        assert hi.resolved_at is not None


# ── FixPlan approval gate tests ─────────────────────────────────────


class TestFixPlanApproval:
    def test_l0_auto_approve(self):
        hi = HealthIssue()
        fp = FixPlan(title="Check logs", risk_level=FixPlanRiskLevel.L0)
        result = create_fix_plan(hi, fp)
        assert result.status == FixPlanStatus.APPROVED
        assert result.approved_by == "system:auto_approve"
        assert result.approved_at is not None

    def test_l1_auto_approve(self):
        hi = HealthIssue()
        fp = FixPlan(title="Scale ASG", risk_level=FixPlanRiskLevel.L1)
        result = create_fix_plan(hi, fp)
        assert result.status == FixPlanStatus.APPROVED

    def test_l2_requires_human(self):
        hi = HealthIssue()
        fp = FixPlan(title="Restart service", risk_level=FixPlanRiskLevel.L2)
        result = create_fix_plan(hi, fp)
        assert result.status == FixPlanStatus.PENDING_APPROVAL

    def test_l3_requires_human(self):
        hi = HealthIssue()
        fp = FixPlan(title="Failover DB", risk_level=FixPlanRiskLevel.L3)
        result = create_fix_plan(hi, fp)
        assert result.status == FixPlanStatus.PENDING_APPROVAL

    def test_l2_approve_by_human(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(hi, fp)
        approve_fix_plan(fp, approver="ops-engineer")
        assert fp.status == FixPlanStatus.APPROVED
        assert fp.approved_by == "ops-engineer"

    def test_l3_approve_needs_senior_and_double_confirm(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L3)
        create_fix_plan(hi, fp)
        approve_fix_plan(fp, approver="senior-eng", is_senior=True, double_confirmed=True)
        assert fp.status == FixPlanStatus.APPROVED

    def test_l3_reject_no_senior(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L3)
        create_fix_plan(hi, fp)
        with pytest.raises(ValueError, match="senior"):
            approve_fix_plan(fp, approver="junior", is_senior=False, double_confirmed=True)

    def test_l3_reject_no_double_confirm(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L3)
        create_fix_plan(hi, fp)
        with pytest.raises(ValueError, match="double confirmation"):
            approve_fix_plan(fp, approver="senior", is_senior=True, double_confirmed=False)

    def test_reject_fix_plan(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L2)
        create_fix_plan(hi, fp)
        reject_fix_plan(fp, reason="Too risky")
        assert fp.status == FixPlanStatus.REJECTED
        assert fp.rejected_reason == "Too risky"

    def test_reject_already_approved_fails(self):
        fp = FixPlan(status=FixPlanStatus.APPROVED)
        with pytest.raises(ValueError, match="pending_approval"):
            reject_fix_plan(fp, "nope")

    def test_approve_already_approved_fails(self):
        fp = FixPlan(status=FixPlanStatus.APPROVED)
        with pytest.raises(ValueError, match="pending_approval"):
            approve_fix_plan(fp, "user")

    def test_create_fix_plan_links_to_issue(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L0)
        create_fix_plan(hi, fp)
        assert fp.health_issue_id == hi.id
        assert fp.id in hi.fix_plan_ids

    def test_create_fix_plan_no_duplicate_link(self):
        hi = HealthIssue()
        fp = FixPlan(risk_level=FixPlanRiskLevel.L0)
        hi.fix_plan_ids.append(fp.id)  # pre-add
        create_fix_plan(hi, fp)
        assert hi.fix_plan_ids.count(fp.id) == 1


# ── Store persistence tests ─────────────────────────────────────────


class TestStore:
    @pytest.fixture
    def store(self, tmp_path):
        return HealthIssueStore(data_dir=str(tmp_path))

    def test_create_and_get_issue(self, store):
        hi = HealthIssue(resource_id="i-abc", title="Test issue")
        store.create_issue(hi)
        loaded = store.get_issue(hi.id)
        assert loaded is not None
        assert loaded.resource_id == "i-abc"
        assert loaded.status == HealthIssueStatus.OPEN

    def test_update_issue(self, store):
        hi = HealthIssue(title="Before")
        store.create_issue(hi)
        hi.title = "After"
        hi.status = HealthIssueStatus.INVESTIGATING
        store.update_issue(hi)
        loaded = store.get_issue(hi.id)
        assert loaded.title == "After"
        assert loaded.status == HealthIssueStatus.INVESTIGATING

    def test_delete_issue(self, store):
        hi = HealthIssue()
        store.create_issue(hi)
        assert store.delete_issue(hi.id) is True
        assert store.get_issue(hi.id) is None
        assert store.delete_issue("nonexistent") is False

    def test_list_issues_filter_status(self, store):
        store.create_issue(HealthIssue(status=HealthIssueStatus.OPEN))
        store.create_issue(HealthIssue(status=HealthIssueStatus.RESOLVED))
        store.create_issue(HealthIssue(status=HealthIssueStatus.OPEN))
        open_issues = store.list_issues(status="open")
        assert len(open_issues) == 2

    def test_list_issues_filter_severity(self, store):
        store.create_issue(HealthIssue(severity="critical"))
        store.create_issue(HealthIssue(severity="low"))
        critical = store.list_issues(severity="critical")
        assert len(critical) == 1

    def test_fix_plan_crud(self, store):
        fp = FixPlan(title="Restart", health_issue_id="hi-1")
        store.create_fix_plan(fp)
        loaded = store.get_fix_plan(fp.id)
        assert loaded.title == "Restart"
        fp.status = FixPlanStatus.APPROVED
        store.update_fix_plan(fp)
        loaded = store.get_fix_plan(fp.id)
        assert loaded.status == FixPlanStatus.APPROVED

    def test_list_fix_plans_by_issue(self, store):
        store.create_fix_plan(FixPlan(health_issue_id="hi-1"))
        store.create_fix_plan(FixPlan(health_issue_id="hi-2"))
        store.create_fix_plan(FixPlan(health_issue_id="hi-1"))
        plans = store.list_fix_plans(health_issue_id="hi-1")
        assert len(plans) == 2

    def test_rca_result_crud(self, store):
        rca = RCAResult(root_cause="OOM", health_issue_id="hi-1")
        store.create_rca_result(rca)
        loaded = store.get_rca_result(rca.id)
        assert loaded.root_cause == "OOM"

    def test_list_rca_results_by_issue(self, store):
        store.create_rca_result(RCAResult(health_issue_id="hi-1"))
        store.create_rca_result(RCAResult(health_issue_id="hi-2"))
        results = store.list_rca_results(health_issue_id="hi-1")
        assert len(results) == 1

    def test_update_nonexistent_raises(self, store):
        hi = HealthIssue(id="nonexistent")
        with pytest.raises(KeyError):
            store.update_issue(hi)

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_issue("nope") is None
        assert store.get_fix_plan("nope") is None
        assert store.get_rca_result("nope") is None


# ── Migration tests ─────────────────────────────────────────────────


class TestMigration:
    def test_issue_status_mapping_complete(self):
        """All 8 legacy IssueStatus values have a mapping."""
        expected = {"detected", "analyzing", "pending_fix", "fixing",
                    "fixed", "failed", "acknowledged", "closed"}
        assert set(ISSUE_STATUS_MIGRATION.keys()) == expected

    def test_incident_status_mapping_complete(self):
        """All 9 legacy IncidentStatus values have a mapping."""
        expected = {"triggered", "collecting", "analyzing", "sop_matched",
                    "safety_check", "executing", "waiting_approval",
                    "completed", "failed"}
        assert set(INCIDENT_STATUS_MIGRATION.keys()) == expected

    def test_migrate_issue_detected(self):
        hi = migrate_issue({"status": "detected", "pod_name": "nginx-abc"})
        assert hi.status == HealthIssueStatus.OPEN
        assert hi.resource_id == "nginx-abc"

    def test_migrate_issue_fixed(self):
        hi = migrate_issue({"status": "fixed", "resolved_at": "2026-01-01T00:00:00Z"})
        assert hi.status == HealthIssueStatus.RESOLVED
        assert hi.resolved_at == "2026-01-01T00:00:00Z"

    def test_migrate_issue_failed_reopens(self):
        hi = migrate_issue({"status": "failed"})
        assert hi.status == HealthIssueStatus.OPEN

    def test_migrate_incident_completed(self):
        hi = migrate_incident({
            "status": "completed",
            "trigger_data": {"alarm_name": "High CPU", "severity": "high"},
            "completed_at": "2026-01-01",
        })
        assert hi.status == HealthIssueStatus.RESOLVED
        assert hi.alarm_name == "High CPU"
        assert hi.severity == "high"

    def test_migrate_incident_waiting_approval(self):
        hi = migrate_incident({"status": "waiting_approval", "trigger_data": {}})
        assert hi.status == HealthIssueStatus.FIX_PLANNED

    def test_migrate_incident_with_rca(self):
        hi = migrate_incident({
            "status": "triggered",
            "trigger_data": {},
            "rca_result": {"id": "rca-123"},
        })
        assert "rca-123" in hi.rca_result_ids

    def test_migrate_incident_unknown_status_defaults_open(self):
        hi = migrate_incident({"status": "unknown_status", "trigger_data": {}})
        assert hi.status == HealthIssueStatus.OPEN

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

    def test_map_severity_none(self):
        assert _map_severity(None) == "medium"

    def test_map_severity_unknown(self):
        assert _map_severity("banana") == "medium"




# ── API endpoint tests ──────────────────────────────────────────────


class TestHealthIssueAPI:
    """Test all 8 FastAPI endpoints with TestClient and tmp store."""

    @pytest.fixture(autouse=True)
    def setup_api(self, tmp_path):
        import unittest.mock as mock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.health_issue.api import router, get_store
        from src.health_issue.store import HealthIssueStore

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.store = HealthIssueStore(data_dir=str(tmp_path))
        self._patcher = mock.patch("src.health_issue.api.get_store", return_value=self.store)
        self._patcher.start()
        yield
        self._patcher.stop()

    def test_create_issue(self):
        resp = self.client.post("/api/health-issues", json={
            "resource_id": "i-abc", "title": "CPU high", "severity": "high"
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "open"
        assert data["title"] == "CPU high"
        self._issue_id = data["id"]

    def test_list_issues(self):
        self.client.post("/api/health-issues", json={"title": "A", "severity": "high"})
        self.client.post("/api/health-issues", json={"title": "B", "severity": "low"})
        resp = self.client.get("/api/health-issues")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_list_issues_filter(self):
        self.client.post("/api/health-issues", json={"severity": "critical"})
        self.client.post("/api/health-issues", json={"severity": "low"})
        resp = self.client.get("/api/health-issues?severity=critical")
        assert resp.json()["count"] == 1

    def test_get_issue_detail(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "X"})
        issue_id = create_resp.json()["id"]
        resp = self.client.get(f"/api/health-issues/{issue_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == issue_id
        assert "allowed_transitions" in data
        assert "investigating" in data["allowed_transitions"]

    def test_get_issue_404(self):
        resp = self.client.get("/api/health-issues/nonexistent")
        assert resp.status_code == 404

    def test_transition_status(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "Trans"})
        issue_id = create_resp.json()["id"]
        resp = self.client.patch(f"/api/health-issues/{issue_id}/status",
                                 json={"status": "investigating"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "investigating"

    def test_transition_invalid_status(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "X"})
        issue_id = create_resp.json()["id"]
        resp = self.client.patch(f"/api/health-issues/{issue_id}/status",
                                 json={"status": "fix_approved"})
        assert resp.status_code == 409

    def test_transition_bad_status_value(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "X"})
        issue_id = create_resp.json()["id"]
        resp = self.client.patch(f"/api/health-issues/{issue_id}/status",
                                 json={"status": "banana"})
        assert resp.status_code == 400

    def test_create_fix_plan_l0_auto(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "FP"})
        issue_id = create_resp.json()["id"]
        resp = self.client.post(f"/api/health-issues/{issue_id}/fix-plan",
                                json={"title": "Check", "risk_level": "L0"})
        assert resp.status_code == 201
        assert resp.json()["status"] == "approved"

    def test_create_fix_plan_l2_pending(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "FP"})
        issue_id = create_resp.json()["id"]
        resp = self.client.post(f"/api/health-issues/{issue_id}/fix-plan",
                                json={"title": "Restart", "risk_level": "L2"})
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending_approval"

    def test_create_fix_plan_invalid_risk(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "FP"})
        issue_id = create_resp.json()["id"]
        resp = self.client.post(f"/api/health-issues/{issue_id}/fix-plan",
                                json={"title": "Bad", "risk_level": "L9"})
        assert resp.status_code == 400

    def test_approve_fix_plan(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "A"})
        issue_id = create_resp.json()["id"]
        plan_resp = self.client.post(f"/api/health-issues/{issue_id}/fix-plan",
                                     json={"title": "P", "risk_level": "L2"})
        plan_id = plan_resp.json()["id"]
        resp = self.client.patch(f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/approve",
                                 json={"approver": "ops-eng"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_fix_plan(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "R"})
        issue_id = create_resp.json()["id"]
        plan_resp = self.client.post(f"/api/health-issues/{issue_id}/fix-plan",
                                     json={"title": "P", "risk_level": "L2"})
        plan_id = plan_resp.json()["id"]
        resp = self.client.patch(f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/reject",
                                 json={"reason": "Not safe"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_submit_feedback(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "FB"})
        issue_id = create_resp.json()["id"]
        resp = self.client.post(f"/api/health-issues/{issue_id}/feedback",
                                json={"feedback": "thumbs-up"})
        assert resp.status_code == 200
        assert resp.json()["feedback"] == "thumbs-up"

    def test_feedback_404(self):
        resp = self.client.post("/api/health-issues/nonexistent/feedback",
                                json={"feedback": "nope"})
        assert resp.status_code == 404

    def test_approve_nonexistent_plan_404(self):
        create_resp = self.client.post("/api/health-issues", json={"title": "A"})
        issue_id = create_resp.json()["id"]
        resp = self.client.patch(f"/api/health-issues/{issue_id}/fix-plan/bad-id/approve",
                                 json={"approver": "x"})
        assert resp.status_code == 404

    def test_full_lifecycle_via_api(self):
        """E2E: create → investigating → rci → fix_plan → approve → execute → resolve"""
        # Create
        r = self.client.post("/api/health-issues", json={"title": "E2E", "severity": "high"})
        iid = r.json()["id"]

        # Transitions
        for status in ["investigating", "root_cause_identified", "fix_planned"]:
            r = self.client.patch(f"/api/health-issues/{iid}/status", json={"status": status})
            assert r.status_code == 200

        # Create + approve fix plan
        r = self.client.post(f"/api/health-issues/{iid}/fix-plan",
                             json={"title": "Fix it", "risk_level": "L2"})
        pid = r.json()["id"]
        r = self.client.patch(f"/api/health-issues/{iid}/fix-plan/{pid}/approve",
                              json={"approver": "lead"})
        assert r.status_code == 200

        # Continue transitions
        for status in ["fix_approved", "fix_executed", "resolved"]:
            r = self.client.patch(f"/api/health-issues/{iid}/status", json={"status": status})
            assert r.status_code == 200

        # Verify final state
        r = self.client.get(f"/api/health-issues/{iid}")
        assert r.json()["status"] == "resolved"
        assert r.json()["resolved_at"] is not None


