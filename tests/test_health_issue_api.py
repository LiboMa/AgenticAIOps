"""
HealthIssue API Endpoint Tests — FastAPI TestClient

Covers all 7 endpoints + error paths + lifecycle convenience functions
(reopen, force_close) that are uncovered in the existing test suite.

Target: api.py 0% → ~95%, lifecycle.py 85% → 100%.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import from sub-modules directly
from src.health_issue.api import router, get_store
from src.health_issue.models import (
    FixPlan,
    FixPlanRiskLevel,
    FixPlanStatus,
    HealthIssue,
    HealthIssueStatus,
    RCAResult,
)
from src.health_issue.lifecycle import (
    reopen,
    force_close,
    transition,
)
from src.health_issue.store import HealthIssueStore


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(autouse=True)
def _patch_store(tmp_path, monkeypatch):
    """Patch the API module's get_store() to use a temp directory."""
    store = HealthIssueStore(data_dir=str(tmp_path))
    monkeypatch.setattr("src.health_issue.api._store", store)
    return store


@pytest.fixture
def store(_patch_store):
    return _patch_store


@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def seed_issue(store) -> HealthIssue:
    """Create and persist a sample issue."""
    issue = HealthIssue(
        id="issue-001",
        resource_id="i-abc123",
        resource_type="ec2",
        region="us-east-1",
        severity="high",
        source="cloudwatch_alarm",
        title="High CPU on i-abc123",
        description="CPU > 90% for 5 minutes",
    )
    store.create_issue(issue)
    return issue


@pytest.fixture
def seed_issue_with_plan(store, seed_issue) -> tuple:
    """Create issue + L2 pending-approval FixPlan."""
    plan = FixPlan(
        id="plan-001",
        health_issue_id=seed_issue.id,
        title="Restart instance",
        risk_level=FixPlanRiskLevel.L2,
        status=FixPlanStatus.PENDING_APPROVAL,
        steps=[{"action": "restart", "target": "i-abc123"}],
    )
    store.create_fix_plan(plan)
    seed_issue.fix_plan_ids.append(plan.id)
    store.update_issue(seed_issue)
    return seed_issue, plan


# ===================================================================
# GET /api/health-issues — List
# ===================================================================

class TestListEndpoint:
    def test_list_empty(self, client):
        resp = client.get("/api/health-issues")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["items"] == []

    def test_list_returns_created_issues(self, client, seed_issue):
        resp = client.get("/api/health-issues")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["items"][0]["id"] == "issue-001"

    def test_list_filter_by_status(self, client, store):
        for i, status in enumerate(["open", "investigating", "open"]):
            issue = HealthIssue(
                id=f"i-{i}",
                status=HealthIssueStatus(status),
                title=f"Issue {i}",
            )
            store.create_issue(issue)
        resp = client.get("/api/health-issues?status=open")
        assert resp.json()["count"] == 2

    def test_list_filter_by_severity(self, client, store):
        for sev in ["high", "low", "high"]:
            store.create_issue(HealthIssue(severity=sev))
        resp = client.get("/api/health-issues?severity=high")
        assert resp.json()["count"] == 2

    def test_list_filter_by_resource_type(self, client, seed_issue):
        resp = client.get("/api/health-issues?resource_type=ec2")
        assert resp.json()["count"] == 1
        resp2 = client.get("/api/health-issues?resource_type=rds")
        assert resp2.json()["count"] == 0


# ===================================================================
# POST /api/health-issues — Create
# ===================================================================

class TestCreateEndpoint:
    def test_create_minimal(self, client):
        resp = client.post("/api/health-issues", json={})
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "open"
        assert "id" in body

    def test_create_full(self, client):
        payload = {
            "resource_id": "i-xyz",
            "resource_type": "ec2",
            "region": "ap-southeast-1",
            "severity": "critical",
            "source": "detect_agent",
            "title": "Disk full",
            "description": "Root volume 100%",
            "alarm_name": "DiskSpaceLow",
            "metric_data": {"disk_usage_pct": 100},
        }
        resp = client.post("/api/health-issues", json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["resource_id"] == "i-xyz"
        assert body["severity"] == "critical"
        assert body["alarm_name"] == "DiskSpaceLow"

    def test_create_persists(self, client, store):
        client.post("/api/health-issues", json={"title": "Persisted"})
        issues = store.list_issues()
        assert len(issues) == 1
        assert issues[0].title == "Persisted"


# ===================================================================
# GET /api/health-issues/{id} — Detail
# ===================================================================

class TestGetDetailEndpoint:
    def test_get_existing(self, client, seed_issue):
        resp = client.get(f"/api/health-issues/{seed_issue.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == seed_issue.id
        assert "rca_results" in body
        assert "fix_plans" in body
        assert "allowed_transitions" in body

    def test_get_nonexistent_404(self, client):
        resp = client.get("/api/health-issues/nonexistent")
        assert resp.status_code == 404

    def test_get_includes_linked_rca_and_plans(self, client, seed_issue_with_plan, store):
        issue, plan = seed_issue_with_plan
        rca = RCAResult(
            health_issue_id=issue.id,
            root_cause="Memory leak",
            confidence=0.85,
        )
        store.create_rca_result(rca)

        resp = client.get(f"/api/health-issues/{issue.id}")
        body = resp.json()
        assert len(body["rca_results"]) == 1
        assert body["rca_results"][0]["root_cause"] == "Memory leak"
        assert len(body["fix_plans"]) == 1
        assert body["fix_plans"][0]["id"] == plan.id

    def test_get_allowed_transitions(self, client, seed_issue):
        resp = client.get(f"/api/health-issues/{seed_issue.id}")
        body = resp.json()
        assert "investigating" in body["allowed_transitions"]
        assert "resolved" in body["allowed_transitions"]


# ===================================================================
# PATCH /api/health-issues/{id}/status — Transition
# ===================================================================

class TestTransitionEndpoint:
    def test_transition_happy_path(self, client, seed_issue):
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/status",
            json={"status": "investigating"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "investigating"

    def test_transition_nonexistent_404(self, client):
        resp = client.patch(
            "/api/health-issues/nope/status",
            json={"status": "investigating"},
        )
        assert resp.status_code == 404

    def test_transition_invalid_status_400(self, client, seed_issue):
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/status",
            json={"status": "banana"},
        )
        assert resp.status_code == 400
        assert "Invalid status" in resp.json()["detail"]

    def test_transition_illegal_409(self, client, seed_issue):
        # open → fix_planned is not allowed
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/status",
            json={"status": "fix_planned"},
        )
        assert resp.status_code == 409
        assert "Cannot transition" in resp.json()["detail"]

    def test_transition_to_resolved_sets_resolved_at(self, client, seed_issue):
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/status",
            json={"status": "resolved"},
        )
        assert resp.status_code == 200
        assert resp.json()["resolved_at"] is not None

    def test_full_happy_path_lifecycle(self, client, seed_issue):
        """Walk through the entire 7-state lifecycle via API."""
        transitions = [
            "investigating",
            "root_cause_identified",
            "fix_planned",
            "fix_approved",
            "fix_executed",
            "resolved",
        ]
        for status in transitions:
            resp = client.patch(
                f"/api/health-issues/{seed_issue.id}/status",
                json={"status": status},
            )
            assert resp.status_code == 200, f"Failed at {status}: {resp.json()}"
            assert resp.json()["status"] == status


# ===================================================================
# POST /api/health-issues/{id}/fix-plan — Create FixPlan
# ===================================================================

class TestCreateFixPlanEndpoint:
    def test_create_l0_auto_approve(self, client, seed_issue):
        resp = client.post(
            f"/api/health-issues/{seed_issue.id}/fix-plan",
            json={
                "title": "Read-only check",
                "risk_level": "L0",
                "steps": [{"action": "describe_instances"}],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "approved"
        assert body["approved_by"] == "system:auto_approve"

    def test_create_l1_auto_approve(self, client, seed_issue):
        resp = client.post(
            f"/api/health-issues/{seed_issue.id}/fix-plan",
            json={"title": "Config change", "risk_level": "L1"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "approved"

    def test_create_l2_pending(self, client, seed_issue):
        resp = client.post(
            f"/api/health-issues/{seed_issue.id}/fix-plan",
            json={"title": "Restart", "risk_level": "L2"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending_approval"

    def test_create_l3_pending(self, client, seed_issue):
        resp = client.post(
            f"/api/health-issues/{seed_issue.id}/fix-plan",
            json={"title": "Failover", "risk_level": "L3"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending_approval"

    def test_create_fixplan_nonexistent_issue_404(self, client):
        resp = client.post(
            "/api/health-issues/nope/fix-plan",
            json={"title": "X", "risk_level": "L0"},
        )
        assert resp.status_code == 404

    def test_create_fixplan_invalid_risk_400(self, client, seed_issue):
        resp = client.post(
            f"/api/health-issues/{seed_issue.id}/fix-plan",
            json={"title": "X", "risk_level": "L9"},
        )
        assert resp.status_code == 400
        assert "Invalid risk_level" in resp.json()["detail"]

    def test_create_fixplan_with_full_payload(self, client, seed_issue):
        resp = client.post(
            f"/api/health-issues/{seed_issue.id}/fix-plan",
            json={
                "title": "Full plan",
                "description": "Detailed restart plan",
                "risk_level": "L2",
                "steps": [{"action": "stop"}, {"action": "start"}],
                "pre_checks": ["verify health"],
                "post_checks": ["check status"],
                "rollback_plan": ["revert config"],
                "estimated_impact": "30s downtime",
                "sop_id": "sop-123",
                "sop_name": "Restart EC2",
                "rca_result_id": "rca-456",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["sop_id"] == "sop-123"
        assert len(body["steps"]) == 2
        assert body["estimated_impact"] == "30s downtime"


# ===================================================================
# PATCH /api/health-issues/{id}/fix-plan/{plan_id}/approve
# ===================================================================

class TestApproveFixPlanEndpoint:
    def test_approve_l2_happy(self, client, seed_issue_with_plan):
        issue, plan = seed_issue_with_plan
        resp = client.patch(
            f"/api/health-issues/{issue.id}/fix-plan/{plan.id}/approve",
            json={"approver": "ops-lead", "is_senior": False},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert resp.json()["approved_by"] == "ops-lead"

    def test_approve_l3_needs_senior_and_double(self, client, store, seed_issue):
        plan = FixPlan(
            id="plan-l3",
            health_issue_id=seed_issue.id,
            risk_level=FixPlanRiskLevel.L3,
            status=FixPlanStatus.PENDING_APPROVAL,
        )
        store.create_fix_plan(plan)

        # Missing senior
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/plan-l3/approve",
            json={"approver": "jr-ops", "is_senior": False, "double_confirmed": True},
        )
        assert resp.status_code == 409

        # Missing double confirm
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/plan-l3/approve",
            json={"approver": "sr-ops", "is_senior": True, "double_confirmed": False},
        )
        assert resp.status_code == 409

        # Both present → success
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/plan-l3/approve",
            json={"approver": "sr-ops", "is_senior": True, "double_confirmed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_approve_nonexistent_issue_404(self, client):
        resp = client.patch(
            "/api/health-issues/nope/fix-plan/plan-001/approve",
            json={"approver": "x"},
        )
        assert resp.status_code == 404

    def test_approve_nonexistent_plan_404(self, client, seed_issue):
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/nope/approve",
            json={"approver": "x"},
        )
        assert resp.status_code == 404

    def test_approve_plan_wrong_issue_404(self, client, store, seed_issue):
        """Plan exists but belongs to different issue."""
        plan = FixPlan(
            id="plan-other",
            health_issue_id="other-issue-id",
            status=FixPlanStatus.PENDING_APPROVAL,
        )
        store.create_fix_plan(plan)
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/plan-other/approve",
            json={"approver": "x"},
        )
        assert resp.status_code == 404

    def test_approve_already_approved_409(self, client, store, seed_issue):
        plan = FixPlan(
            id="plan-approved",
            health_issue_id=seed_issue.id,
            status=FixPlanStatus.APPROVED,
            approved_by="someone",
        )
        store.create_fix_plan(plan)
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/plan-approved/approve",
            json={"approver": "another"},
        )
        assert resp.status_code == 409


# ===================================================================
# PATCH /api/health-issues/{id}/fix-plan/{plan_id}/reject
# ===================================================================

class TestRejectFixPlanEndpoint:
    def test_reject_happy(self, client, seed_issue_with_plan):
        issue, plan = seed_issue_with_plan
        resp = client.patch(
            f"/api/health-issues/{issue.id}/fix-plan/{plan.id}/reject",
            json={"reason": "Too risky"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        assert resp.json()["rejected_reason"] == "Too risky"

    def test_reject_nonexistent_issue_404(self, client):
        resp = client.patch(
            "/api/health-issues/nope/fix-plan/plan-001/reject",
            json={"reason": "x"},
        )
        assert resp.status_code == 404

    def test_reject_nonexistent_plan_404(self, client, seed_issue):
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/nope/reject",
            json={"reason": "x"},
        )
        assert resp.status_code == 404

    def test_reject_already_approved_409(self, client, store, seed_issue):
        plan = FixPlan(
            id="plan-done",
            health_issue_id=seed_issue.id,
            status=FixPlanStatus.APPROVED,
        )
        store.create_fix_plan(plan)
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/plan-done/reject",
            json={"reason": "No"},
        )
        assert resp.status_code == 409

    def test_reject_plan_wrong_issue_404(self, client, store, seed_issue):
        plan = FixPlan(
            id="plan-orphan",
            health_issue_id="other-issue",
            status=FixPlanStatus.PENDING_APPROVAL,
        )
        store.create_fix_plan(plan)
        resp = client.patch(
            f"/api/health-issues/{seed_issue.id}/fix-plan/plan-orphan/reject",
            json={"reason": "x"},
        )
        assert resp.status_code == 404


# ===================================================================
# POST /api/health-issues/{id}/feedback
# ===================================================================

class TestFeedbackEndpoint:
    def test_feedback_happy(self, client, seed_issue):
        resp = client.post(
            f"/api/health-issues/{seed_issue.id}/feedback",
            json={"feedback": "thumbs-up"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["feedback"] == "thumbs-up"
        assert body["id"] == seed_issue.id

    def test_feedback_nonexistent_404(self, client):
        resp = client.post(
            "/api/health-issues/nope/feedback",
            json={"feedback": "x"},
        )
        assert resp.status_code == 404

    def test_feedback_persists(self, client, seed_issue, store):
        client.post(
            f"/api/health-issues/{seed_issue.id}/feedback",
            json={"feedback": "thumbs-down"},
        )
        updated = store.get_issue(seed_issue.id)
        assert updated.user_feedback == "thumbs-down"

    def test_feedback_overwrite(self, client, seed_issue, store):
        client.post(
            f"/api/health-issues/{seed_issue.id}/feedback",
            json={"feedback": "good"},
        )
        client.post(
            f"/api/health-issues/{seed_issue.id}/feedback",
            json={"feedback": "actually bad"},
        )
        updated = store.get_issue(seed_issue.id)
        assert updated.user_feedback == "actually bad"


# ===================================================================
# Lifecycle convenience functions (reopen, force_close)
# ===================================================================

class TestReopenConvenience:
    """Test the reopen() convenience function in lifecycle.py."""

    def test_reopen_resolved_issue(self):
        issue = HealthIssue(status=HealthIssueStatus.RESOLVED, resolved_at="2026-01-01T00:00:00Z")
        result = reopen(issue, "Recurrence detected", actor="ops-team")
        assert result.status == HealthIssueStatus.OPEN
        assert result.resolved_at is None
        assert len(result.timeline) == 1
        assert result.timeline[0]["note"] == "Recurrence detected"
        assert result.timeline[0]["actor"] == "ops-team"

    def test_reopen_non_resolved_raises(self):
        issue = HealthIssue(status=HealthIssueStatus.INVESTIGATING)
        with pytest.raises(ValueError, match="investigating.*not.*resolved"):
            reopen(issue, "try reopen")

    def test_reopen_empty_note_raises(self):
        issue = HealthIssue(status=HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError, match="non-empty note"):
            reopen(issue, "")

    def test_reopen_whitespace_note_raises(self):
        issue = HealthIssue(status=HealthIssueStatus.RESOLVED)
        with pytest.raises(ValueError, match="non-empty note"):
            reopen(issue, "   ")

    def test_reopen_open_issue_raises(self):
        issue = HealthIssue(status=HealthIssueStatus.OPEN)
        with pytest.raises(ValueError, match="open.*not.*resolved"):
            reopen(issue, "try again")


class TestForceClose:
    """Test the force_close() function in lifecycle.py."""

    def test_force_close_from_open(self):
        issue = HealthIssue(status=HealthIssueStatus.OPEN)
        result = force_close(issue, actor="admin", has_permission=True)
        assert result.status == HealthIssueStatus.RESOLVED
        assert result.resolved_at is not None
        assert len(result.timeline) == 1
        assert result.timeline[0]["action"] == "force_close"
        assert result.timeline[0]["actor"] == "admin"

    def test_force_close_from_investigating(self):
        issue = HealthIssue(status=HealthIssueStatus.INVESTIGATING)
        result = force_close(issue, actor="admin", note="False alarm", has_permission=True)
        assert result.status == HealthIssueStatus.RESOLVED
        assert result.timeline[0]["note"] == "False alarm"

    def test_force_close_from_fix_executed(self):
        issue = HealthIssue(status=HealthIssueStatus.FIX_EXECUTED)
        result = force_close(issue, actor="sre", has_permission=True)
        assert result.status == HealthIssueStatus.RESOLVED

    def test_force_close_from_resolved(self):
        """Even from resolved, force_close should work."""
        issue = HealthIssue(status=HealthIssueStatus.RESOLVED, resolved_at="old")
        result = force_close(issue, actor="admin", has_permission=True)
        assert result.status == HealthIssueStatus.RESOLVED
        # resolved_at should be refreshed
        assert result.resolved_at != "old"

    def test_force_close_without_permission_raises(self):
        issue = HealthIssue(status=HealthIssueStatus.OPEN)
        with pytest.raises(PermissionError, match="elevated permission"):
            force_close(issue, actor="user", has_permission=False)

    def test_force_close_default_note(self):
        issue = HealthIssue(status=HealthIssueStatus.OPEN)
        result = force_close(issue, actor="admin", has_permission=True)
        assert result.timeline[0]["note"] == "Force-closed by operator"

    def test_force_close_custom_note(self):
        issue = HealthIssue(status=HealthIssueStatus.OPEN)
        result = force_close(issue, actor="admin", note="Duplicate issue", has_permission=True)
        assert result.timeline[0]["note"] == "Duplicate issue"

    def test_force_close_all_states(self):
        """Force close should work from every state."""
        for status in HealthIssueStatus:
            issue = HealthIssue(status=status)
            result = force_close(issue, actor="admin", has_permission=True)
            assert result.status == HealthIssueStatus.RESOLVED


# ===================================================================
# Integration: end-to-end API flow
# ===================================================================

class TestE2EAPIFlow:
    """Full lifecycle through the API."""

    def test_create_investigate_rca_plan_approve_execute_resolve(self, client):
        # 1. Create issue
        resp = client.post("/api/health-issues", json={
            "resource_id": "i-e2e",
            "resource_type": "ec2",
            "severity": "critical",
            "title": "E2E Test Issue",
        })
        assert resp.status_code == 201
        issue_id = resp.json()["id"]

        # 2. Transition through lifecycle
        for status in ["investigating", "root_cause_identified", "fix_planned"]:
            resp = client.patch(
                f"/api/health-issues/{issue_id}/status",
                json={"status": status},
            )
            assert resp.status_code == 200

        # 3. Create L2 fix plan (pending)
        resp = client.post(
            f"/api/health-issues/{issue_id}/fix-plan",
            json={"title": "Restart EC2", "risk_level": "L2"},
        )
        assert resp.status_code == 201
        plan_id = resp.json()["id"]
        assert resp.json()["status"] == "pending_approval"

        # 4. Approve fix plan
        resp = client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_id}/approve",
            json={"approver": "ops-lead"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        # 5. Continue lifecycle
        for status in ["fix_approved", "fix_executed", "resolved"]:
            resp = client.patch(
                f"/api/health-issues/{issue_id}/status",
                json={"status": status},
            )
            assert resp.status_code == 200

        # 6. Submit feedback
        resp = client.post(
            f"/api/health-issues/{issue_id}/feedback",
            json={"feedback": "thumbs-up"},
        )
        assert resp.status_code == 200

        # 7. Verify final state
        resp = client.get(f"/api/health-issues/{issue_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "resolved"
        assert body["resolved_at"] is not None
        assert body["user_feedback"] == "thumbs-up"
        assert len(body["fix_plans"]) == 1

    def test_create_l0_auto_approve_fast_path(self, client):
        """L0 plan auto-approves — skip human approval step."""
        resp = client.post("/api/health-issues", json={"title": "Quick check"})
        issue_id = resp.json()["id"]

        resp = client.post(
            f"/api/health-issues/{issue_id}/fix-plan",
            json={"title": "Describe", "risk_level": "L0"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "approved"
        assert resp.json()["approved_by"] == "system:auto_approve"
        assert resp.json()["approved_at"] is not None

    def test_update_nonexistent_fix_plan_raises(self, store):
        """Store: update_fix_plan for nonexistent ID → KeyError (line 139)."""
        ghost = FixPlan(id="ghost-plan")
        with pytest.raises(KeyError, match="ghost-plan"):
            store.update_fix_plan(ghost)

    def test_get_nonexistent_rca_returns_none(self, store):
        """Store: get_rca_result for nonexistent ID → None (line 164)."""
        assert store.get_rca_result("no-such-rca") is None

    def test_reject_then_new_plan(self, client, store):
        """Reject a plan, then submit a new one."""
        resp = client.post("/api/health-issues", json={"title": "Needs replanning"})
        issue_id = resp.json()["id"]

        # Create L2 plan
        resp = client.post(
            f"/api/health-issues/{issue_id}/fix-plan",
            json={"title": "Plan A", "risk_level": "L2"},
        )
        plan_a_id = resp.json()["id"]

        # Reject it
        resp = client.patch(
            f"/api/health-issues/{issue_id}/fix-plan/{plan_a_id}/reject",
            json={"reason": "Insufficient rollback"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        # Submit new plan
        resp = client.post(
            f"/api/health-issues/{issue_id}/fix-plan",
            json={"title": "Plan B", "risk_level": "L1"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "approved"  # L1 auto-approve
