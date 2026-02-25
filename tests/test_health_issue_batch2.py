"""
HealthIssue Batch 2 Tests — Migration + API Endpoints + force_close + reopen

Covers:
  - migration.py: ISSUE_STATUS_MIGRATION (8→7), INCIDENT_STATUS_MIGRATION (9→7)
  - routers/health_issues.py: 9 API endpoints via TestClient
  - lifecycle.py: reopen() convenience + force_close() with permission gate
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Migration imports (now safe — migration.py exists)
# ---------------------------------------------------------------------------
from src.health_issue import (
    ALLOWED_TRANSITIONS,
    INCIDENT_STATUS_MIGRATION,
    ISSUE_STATUS_MIGRATION,
    HealthIssue,
    HealthIssueStatus,
    FixPlan,
    FixPlanRiskLevel,
    FixPlanStatus,
    migrate_incident,
    migrate_issue,
    reopen,
    force_close,
    transition,
)

# ---------------------------------------------------------------------------
# API TestClient — mount router on isolated FastAPI app with patched store
# ---------------------------------------------------------------------------
from fastapi import FastAPI
from routers.health_issues import router
from src.health_issue.store import HealthIssueStore


@pytest.fixture(autouse=True)
def _patch_store(tmp_path, monkeypatch):
    """Patch the router module's _store to use a temp directory."""
    store = HealthIssueStore(data_dir=str(tmp_path))
    monkeypatch.setattr("routers.health_issues._store", store)
    return store


@pytest.fixture
def api_client():
    _app = FastAPI()
    _app.include_router(router)
    return TestClient(_app)

# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def issue() -> HealthIssue:
    return HealthIssue(
        id=str(uuid.uuid4()),
        resource_id="i-test123",
        resource_type="ec2",
        region="us-east-1",
        severity="high",
        title="Test issue",
    )


@pytest.fixture
def resolved_issue() -> HealthIssue:
    hi = HealthIssue(id=str(uuid.uuid4()), title="Resolved issue")
    transition(hi, HealthIssueStatus.RESOLVED)
    return hi


# ===================================================================
# 1. Migration Tests — ISSUE_STATUS_MIGRATION
# ===================================================================

class TestIssueStatusMigration:
    """IssueStatus (8 states) → HealthIssueStatus (7 states)."""

    @pytest.mark.parametrize("old_status,expected", list(ISSUE_STATUS_MIGRATION.items()),
                             ids=[f"issue:{k}" for k in ISSUE_STATUS_MIGRATION])
    def test_all_mappings(self, old_status, expected):
        """Every legacy IssueStatus should map to a valid HealthIssueStatus."""
        result = migrate_issue({"status": old_status, "resource_id": "test-pod"})
        assert result.status == HealthIssueStatus(expected)

    def test_unknown_status_defaults_to_open(self):
        result = migrate_issue({"status": "some_unknown_status"})
        assert result.status == HealthIssueStatus.OPEN

    def test_missing_status_defaults_to_open(self):
        result = migrate_issue({})
        assert result.status == HealthIssueStatus.OPEN

    def test_carries_resource_fields(self):
        result = migrate_issue({
            "status": "analyzing",
            "resource_id": "i-abc123",
            "resource_type": "ec2",
            "region": "us-west-2",
            "title": "High CPU",
            "description": "CPU at 99%",
        })
        assert result.resource_id == "i-abc123"
        assert result.resource_type == "ec2"
        assert result.region == "us-west-2"
        assert result.title == "High CPU"

    def test_pod_name_fallback(self):
        """Legacy issues may have pod_name instead of resource_id."""
        result = migrate_issue({"status": "detected", "pod_name": "nginx-abc"})
        assert result.resource_id == "nginx-abc"

    def test_resolved_carries_resolved_at(self):
        result = migrate_issue({"status": "fixed", "resolved_at": "2026-01-01T00:00:00Z"})
        assert result.status == HealthIssueStatus.RESOLVED
        assert result.resolved_at == "2026-01-01T00:00:00Z"

    def test_issue_id_linked(self):
        result = migrate_issue({"status": "detected", "id": "legacy-123"})
        assert result.issue_id == "legacy-123"


class TestIncidentStatusMigration:
    """IncidentStatus (9 states) → HealthIssueStatus (7 states)."""

    @pytest.mark.parametrize("old_status,expected", list(INCIDENT_STATUS_MIGRATION.items()),
                             ids=[f"incident:{k}" for k in INCIDENT_STATUS_MIGRATION])
    def test_all_mappings(self, old_status, expected):
        result = migrate_incident({"status": old_status})
        assert result.status == HealthIssueStatus(expected)

    def test_unknown_status_defaults_to_open(self):
        result = migrate_incident({"status": "garbage"})
        assert result.status == HealthIssueStatus.OPEN

    def test_trigger_data_carried(self):
        result = migrate_incident({
            "status": "analyzing",
            "trigger_data": {
                "resource_id": "i-xyz",
                "resource_type": "rds",
                "alarm_name": "HighCPU",
                "severity": "critical",
            },
        })
        assert result.resource_id == "i-xyz"
        assert result.resource_type == "rds"
        assert result.alarm_name == "HighCPU"
        assert result.severity == "critical"

    def test_incident_id_linked(self):
        result = migrate_incident({"status": "triggered", "incident_id": "inc-456"})
        assert result.incident_id == "inc-456"

    def test_rca_result_carried(self):
        result = migrate_incident({
            "status": "completed",
            "rca_result": {"id": "rca-789", "root_cause": "OOM"},
        })
        assert "rca-789" in result.rca_result_ids


class TestSeverityMapping:
    """_map_severity handles various inputs."""

    def test_numeric_severity_1_is_critical(self):
        result = migrate_issue({"status": "detected", "severity": "1"})
        assert result.severity == "critical"

    def test_numeric_severity_2_is_high(self):
        result = migrate_issue({"status": "detected", "severity": "2"})
        assert result.severity == "high"

    def test_numeric_severity_4_is_low(self):
        result = migrate_issue({"status": "detected", "severity": "4"})
        assert result.severity == "low"

    def test_none_severity_defaults_medium(self):
        result = migrate_issue({"status": "detected", "severity": None})
        assert result.severity == "medium"


# ===================================================================
# 2. Reopen Convenience Function
# ===================================================================

class TestReopenFunction:
    """reopen() convenience wrapper."""

    def test_reopen_resolved_issue(self, resolved_issue):
        reopen(resolved_issue, note="Recurrence detected")
        assert resolved_issue.status == HealthIssueStatus.OPEN
        assert resolved_issue.resolved_at is None

    def test_reopen_non_resolved_raises(self, issue):
        with pytest.raises(ValueError, match="not 'resolved'"):
            reopen(issue, note="Trying to reopen OPEN issue")

    def test_reopen_with_actor(self, resolved_issue):
        reopen(resolved_issue, note="Recurred", actor="oncall@team")
        entry = resolved_issue.timeline[-1]
        assert entry["actor"] == "oncall@team"


# ===================================================================
# 3. Force Close
# ===================================================================

class TestForceClose:
    """force_close() bypasses transition rules."""

    def test_force_close_from_open(self, issue):
        force_close(issue, actor="admin", has_permission=True)
        assert issue.status == HealthIssueStatus.RESOLVED
        assert issue.resolved_at is not None

    def test_force_close_from_investigating(self, issue):
        transition(issue, HealthIssueStatus.INVESTIGATING)
        force_close(issue, actor="admin", has_permission=True, note="False alarm")
        assert issue.status == HealthIssueStatus.RESOLVED
        entry = issue.timeline[-1]
        assert entry["action"] == "force_close"
        assert entry["note"] == "False alarm"

    def test_force_close_from_fix_planned(self, issue):
        for s in [HealthIssueStatus.INVESTIGATING, HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
                  HealthIssueStatus.FIX_PLANNED]:
            transition(issue, s)
        force_close(issue, actor="admin", has_permission=True)
        assert issue.status == HealthIssueStatus.RESOLVED

    def test_force_close_no_permission_raises(self, issue):
        with pytest.raises(PermissionError, match="has_permission"):
            force_close(issue, actor="junior", has_permission=False)
        assert issue.status == HealthIssueStatus.OPEN  # unchanged

    def test_force_close_default_note(self, issue):
        force_close(issue, actor="admin", has_permission=True)
        entry = issue.timeline[-1]
        assert entry["note"] == "Force-closed by operator"

    @pytest.mark.parametrize("status", [
        HealthIssueStatus.OPEN,
        HealthIssueStatus.INVESTIGATING,
        HealthIssueStatus.ROOT_CAUSE_IDENTIFIED,
        HealthIssueStatus.FIX_PLANNED,
        HealthIssueStatus.FIX_APPROVED,
        HealthIssueStatus.FIX_EXECUTED,
        HealthIssueStatus.RESOLVED,
    ], ids=[s.value for s in HealthIssueStatus])
    def test_force_close_from_any_state(self, status):
        """force_close should work from every state."""
        hi = HealthIssue(status=status)
        if status == HealthIssueStatus.RESOLVED:
            hi.resolved_at = "2026-01-01T00:00:00+00:00"
        force_close(hi, actor="admin", has_permission=True)
        assert hi.status == HealthIssueStatus.RESOLVED


# ===================================================================
# 4. API Endpoint Tests (TestClient)
# ===================================================================

class TestAPIListIssues:
    """GET /api/health-issues."""

    def test_list_empty(self, api_client):
        resp = api_client.get("/api/health-issues")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "items" in data


class TestAPICreateIssue:
    """POST /api/health-issues."""

    def test_create_returns_201(self, api_client):
        resp = api_client.post("/api/health-issues", json={
            "resource_id": "i-test",
            "resource_type": "ec2",
            "title": "API Test Issue",
            "severity": "high",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "open"
        assert data["title"] == "API Test Issue"
        assert "id" in data

    def test_create_minimal_body(self, api_client):
        resp = api_client.post("/api/health-issues", json={})
        assert resp.status_code == 201
        assert resp.json()["status"] == "open"


class TestAPIGetIssue:
    """GET /api/health-issues/{id}."""

    def test_get_existing(self, api_client):
        # Create first
        create_resp = api_client.post("/api/health-issues", json={"title": "Get Test"})
        issue_id = create_resp.json()["id"]

        resp = api_client.get(f"/api/health-issues/{issue_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == issue_id
        assert "rca_results" in data
        assert "fix_plans" in data
        assert "allowed_transitions" in data

    def test_get_nonexistent_returns_404(self, api_client):
        resp = api_client.get("/api/health-issues/nonexistent-id-12345")
        assert resp.status_code == 404


class TestAPITransitionStatus:
    """PATCH /api/health-issues/{id}/status."""

    def _create_issue(self, api_client, title="Transition Test") -> str:
        resp = api_client.post("/api/health-issues", json={"title": title})
        return resp.json()["id"]

    def test_valid_transition(self, api_client):
        issue_id = self._create_issue(api_client)
        resp = api_client.patch(f"/api/health-issues/{issue_id}/status", json={
            "status": "investigating",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "investigating"

    def test_invalid_transition_returns_409(self, api_client):
        issue_id = self._create_issue(api_client)
        resp = api_client.patch(f"/api/health-issues/{issue_id}/status", json={
            "status": "fix_approved",
        })
        assert resp.status_code == 409

    def test_invalid_status_value_returns_400(self, api_client):
        issue_id = self._create_issue(api_client)
        resp = api_client.patch(f"/api/health-issues/{issue_id}/status", json={
            "status": "bogus_status",
        })
        assert resp.status_code == 400

    def test_transition_not_found_returns_404(self, api_client):
        resp = api_client.patch("/api/health-issues/ghost-id/status", json={
            "status": "investigating",
        })
        assert resp.status_code == 404

    def test_reopen_via_api(self, api_client):
        issue_id = self._create_issue(api_client)
        # open → resolved
        api_client.patch(f"/api/health-issues/{issue_id}/status", json={"status": "resolved"})
        # resolved → open (reopen with note)
        resp = api_client.patch(f"/api/health-issues/{issue_id}/status", json={
            "status": "open",
            "note": "Issue recurred",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "open"

    def test_reopen_without_note_returns_400(self, api_client):
        issue_id = self._create_issue(api_client)
        api_client.patch(f"/api/health-issues/{issue_id}/status", json={"status": "resolved"})
        resp = api_client.patch(f"/api/health-issues/{issue_id}/status", json={
            "status": "open",
        })
        assert resp.status_code == 400


class TestAPIFixPlan:
    """POST /api/health-issues/{id}/fix-plan."""

    def _create_issue_at_fix_planned(self, api_client) -> str:
        resp = api_client.post("/api/health-issues", json={"title": "FixPlan Test"})
        issue_id = resp.json()["id"]
        for status in ["investigating", "root_cause_identified", "fix_planned"]:
            api_client.patch(f"/api/health-issues/{issue_id}/status", json={"status": status})
        return issue_id

    def test_create_fix_plan_l0_auto_approved(self, api_client):
        resp = api_client.post("/api/health-issues", json={"title": "FP Test"})
        issue_id = resp.json()["id"]
        resp = api_client.post(f"/api/health-issues/{issue_id}/fix-plan", json={
            "title": "Read-only check",
            "risk_level": "L0",
        })
        assert resp.status_code == 201
        assert resp.json()["status"] == "approved"

    def test_create_fix_plan_l2_pending(self, api_client):
        resp = api_client.post("/api/health-issues", json={"title": "FP Test L2"})
        issue_id = resp.json()["id"]
        resp = api_client.post(f"/api/health-issues/{issue_id}/fix-plan", json={
            "title": "Restart service",
            "risk_level": "L2",
            "steps": [{"action": "restart", "target": "nginx"}],
        })
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending_approval"

    def test_create_fix_plan_invalid_risk_returns_400(self, api_client):
        resp = api_client.post("/api/health-issues", json={"title": "FP Bad Risk"})
        issue_id = resp.json()["id"]
        resp = api_client.post(f"/api/health-issues/{issue_id}/fix-plan", json={
            "title": "Bad",
            "risk_level": "L99",
        })
        assert resp.status_code == 400

    def test_create_fix_plan_issue_not_found(self, api_client):
        resp = api_client.post("/api/health-issues/ghost/fix-plan", json={
            "title": "Ghost",
            "risk_level": "L0",
        })
        assert resp.status_code == 404


class TestAPIApproveReject:
    """PATCH approve/reject endpoints."""

    def _create_issue_with_l2_plan(self, api_client):
        resp = api_client.post("/api/health-issues", json={"title": "Approve Test"})
        issue_id = resp.json()["id"]
        plan_resp = api_client.post(f"/api/health-issues/{issue_id}/fix-plan", json={
            "title": "L2 Plan",
            "risk_level": "L2",
        })
        plan_id = plan_resp.json()["id"]
        return issue_id, plan_id

    def test_approve_l2(self, api_client):
        issue_id, plan_id = self._create_issue_with_l2_plan(api_client)
        resp = api_client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/approve",
            json={"approver": "engineer@team"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_approve_already_approved_returns_409(self, api_client):
        issue_id, plan_id = self._create_issue_with_l2_plan(api_client)
        api_client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/approve",
            json={"approver": "eng1"},
        )
        resp = api_client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/approve",
            json={"approver": "eng2"},
        )
        assert resp.status_code == 409

    def test_reject(self, api_client):
        issue_id, plan_id = self._create_issue_with_l2_plan(api_client)
        resp = api_client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/reject",
            json={"reason": "Too risky"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        assert resp.json()["rejected_reason"] == "Too risky"

    def test_reject_already_rejected_returns_409(self, api_client):
        issue_id, plan_id = self._create_issue_with_l2_plan(api_client)
        api_client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/reject",
            json={"reason": "First reject"},
        )
        resp = api_client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/reject",
            json={"reason": "Second reject"},
        )
        assert resp.status_code == 409

    def test_approve_nonexistent_plan_returns_404(self, api_client):
        resp = api_client.post("/api/health-issues", json={"title": "No Plan"})
        issue_id = resp.json()["id"]
        resp = api_client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/ghost-plan/approve",
            json={"approver": "x"},
        )
        assert resp.status_code == 404


class TestAPIFeedback:
    """POST /api/health-issues/{id}/feedback."""

    def test_submit_feedback(self, api_client):
        resp = api_client.post("/api/health-issues", json={"title": "Feedback Test"})
        issue_id = resp.json()["id"]
        resp = api_client.post(f"/api/health-issues/{issue_id}/feedback", json={
            "feedback": "thumbs-up",
        })
        assert resp.status_code == 200
        assert resp.json()["feedback"] == "thumbs-up"

    def test_feedback_not_found(self, api_client):
        resp = api_client.post("/api/health-issues/ghost/feedback", json={
            "feedback": "thumbs-down",
        })
        assert resp.status_code == 404


class TestAPIForceClose:
    """POST /api/health-issues/{id}/force-close."""

    def test_force_close_with_permission(self, api_client):
        resp = api_client.post("/api/health-issues", json={"title": "Force Close Test"})
        issue_id = resp.json()["id"]
        resp = api_client.post(f"/api/health-issues/{issue_id}/force-close", json={
            "actor": "admin",
            "has_permission": True,
            "note": "False alarm",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"

    def test_force_close_without_permission_returns_403(self, api_client):
        resp = api_client.post("/api/health-issues", json={"title": "No Perm"})
        issue_id = resp.json()["id"]
        resp = api_client.post(f"/api/health-issues/{issue_id}/force-close", json={
            "actor": "junior",
            "has_permission": False,
        })
        assert resp.status_code == 403

    def test_force_close_not_found(self, api_client):
        resp = api_client.post("/api/health-issues/ghost/force-close", json={
            "actor": "admin",
            "has_permission": True,
        })
        assert resp.status_code == 404


# ===================================================================
# 5. E2E API Flow — Full lifecycle through REST
# ===================================================================

class TestAPIE2EFlow:
    """Walk full lifecycle through REST API."""

    def test_full_lifecycle_via_api(self, api_client):
        # 1. Create
        resp = api_client.post("/api/health-issues", json={
            "title": "E2E Test",
            "resource_id": "i-e2e",
            "severity": "critical",
        })
        assert resp.status_code == 201
        issue_id = resp.json()["id"]

        # 2. Transition: open → investigating → rca → fix_planned
        for status in ["investigating", "root_cause_identified", "fix_planned"]:
            resp = api_client.patch(f"/api/health-issues/{issue_id}/status",
                                json={"status": status})
            assert resp.status_code == 200

        # 3. Create L2 FixPlan
        resp = api_client.post(f"/api/health-issues/{issue_id}/fix-plan", json={
            "title": "Scale up ASG",
            "risk_level": "L2",
            "steps": [{"action": "scale", "asg": "web-asg", "desired": 4}],
            "rollback_plan": ["Scale down to 2"],
        })
        assert resp.status_code == 201
        plan_id = resp.json()["id"]
        assert resp.json()["status"] == "pending_approval"

        # 4. Approve
        resp = api_client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/approve",
            json={"approver": "oncall-lead"},
        )
        assert resp.status_code == 200

        # 5. Transition: fix_planned → fix_approved → fix_executed → resolved
        for status in ["fix_approved", "fix_executed", "resolved"]:
            resp = api_client.patch(f"/api/health-issues/{issue_id}/status",
                                json={"status": status})
            assert resp.status_code == 200

        # 6. Verify resolved
        resp = api_client.get(f"/api/health-issues/{issue_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"
        assert resp.json()["resolved_at"] is not None

        # 7. Feedback
        resp = api_client.post(f"/api/health-issues/{issue_id}/feedback",
                           json={"feedback": "thumbs-up"})
        assert resp.status_code == 200

        # 8. Reopen
        resp = api_client.patch(f"/api/health-issues/{issue_id}/status", json={
            "status": "open",
            "note": "Issue recurred after deploy",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "open"
