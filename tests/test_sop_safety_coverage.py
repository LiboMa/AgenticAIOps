"""
Tests for SOP Safety Layer — risk classification, cooldown, circuit breaker,
approval workflow, snapshots, dry-run.

Covers:
- SafetyCheck: to_dict, to_markdown
- SOPSafetyLayer.check(): L0-L3, dry_run, force, circuit breaker, cooldown
- _classify_risk: known SOPs, heuristics, default
- _check_cooldown: active/expired/global/resource-level
- _determine_mode, _generate_dry_run_preview, _mode_reason
- record_execution, create_snapshot, get_snapshot
- request_approval, approve, reject, get_pending_approvals
- get_stats, _reset_daily_counts
- Singleton: get_safety_layer
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.sop_safety import (
    SOPSafetyLayer,
    SafetyCheck,
    ExecutionSnapshot,
    PendingApproval,
    RiskLevel,
    ExecutionMode,
    get_safety_layer,
    SOP_RISK_MAP,
    COOLDOWN_CONFIG,
)


# =============================================================================
# SafetyCheck Tests
# =============================================================================

class TestSafetyCheck:

    def test_to_dict(self):
        sc = SafetyCheck(
            passed=True,
            risk_level=RiskLevel.L1,
            execution_mode=ExecutionMode.NOTIFY,
            reason="Test reason",
        )
        d = sc.to_dict()
        assert d["passed"] is True
        assert d["risk_level"] == "L1"
        assert d["execution_mode"] == "notify"

    def test_to_markdown_passed(self):
        sc = SafetyCheck(
            passed=True,
            risk_level=RiskLevel.L0,
            execution_mode=ExecutionMode.AUTO,
            reason="Low risk, auto-execute",
        )
        md = sc.to_markdown()
        assert "🟢" in md
        assert "通过" in md
        assert "自动执行" in md

    def test_to_markdown_with_warnings(self):
        sc = SafetyCheck(
            passed=True,
            risk_level=RiskLevel.L2,
            execution_mode=ExecutionMode.CONFIRM,
            reason="High risk",
            warnings=["操作风险等级: L2", "影响 10 个资源"],
        )
        md = sc.to_markdown()
        assert "🟡" in md
        assert "警告" in md
        assert "操作风险等级" in md

    def test_to_markdown_with_cooldown(self):
        sc = SafetyCheck(
            passed=False,
            risk_level=RiskLevel.L1,
            execution_mode=ExecutionMode.BLOCKED,
            reason="Cooldown active",
            cooldown_remaining_seconds=120,
        )
        md = sc.to_markdown()
        assert "120s" in md
        assert "未通过" in md

    def test_to_markdown_with_dry_run(self):
        sc = SafetyCheck(
            passed=True,
            risk_level=RiskLevel.L1,
            execution_mode=ExecutionMode.DRY_RUN,
            reason="Dry run",
            dry_run_preview={"sop_id": "sop-test", "risk_level": "L1"},
        )
        md = sc.to_markdown()
        assert "预览模式" in md
        assert "Dry-Run" in md


# =============================================================================
# SOPSafetyLayer.check()
# =============================================================================

class TestCheck:

    def test_l0_auto_execute(self):
        """L0 SOP → auto execute."""
        safety = SOPSafetyLayer()
        result = safety.check(sop_id="sop-describe-instances")
        assert result.passed is True
        assert result.risk_level == RiskLevel.L0
        assert result.execution_mode == ExecutionMode.AUTO

    def test_l3_requires_approval(self):
        """L3 SOP → approval required."""
        safety = SOPSafetyLayer()
        result = safety.check(sop_id="sop-delete-instance")
        assert result.passed is False
        assert result.risk_level == RiskLevel.L3
        assert result.execution_mode == ExecutionMode.APPROVAL
        assert "admin" in result.required_approvers

    def test_dry_run_mode(self):
        """dry_run=True → always DRY_RUN mode."""
        safety = SOPSafetyLayer()
        result = safety.check(sop_id="sop-ec2-high-cpu", dry_run=True, resource_ids=["i-123"])
        assert result.passed is True
        assert result.execution_mode == ExecutionMode.DRY_RUN
        assert result.dry_run_preview is not None
        assert result.dry_run_preview["sop_id"] == "sop-ec2-high-cpu"

    def test_circuit_breaker_blocks(self):
        """Exceeding daily limit → BLOCKED."""
        safety = SOPSafetyLayer()
        # L0 has limit of 100, set count to 100
        safety._execution_counts["sop-describe-instances"] = 100
        result = safety.check(sop_id="sop-describe-instances")
        assert result.passed is False
        assert result.execution_mode == ExecutionMode.BLOCKED
        assert "日执行上限" in result.reason

    def test_cooldown_blocks(self):
        """Recent execution → cooldown blocks."""
        safety = SOPSafetyLayer()
        # Record an execution just now
        safety.record_execution("sop-ec2-high-cpu", ["i-123"])
        result = safety.check(sop_id="sop-ec2-high-cpu", resource_ids=["i-123"])
        assert result.passed is False
        assert result.execution_mode == ExecutionMode.BLOCKED
        assert result.cooldown_remaining_seconds > 0

    def test_force_bypasses_cooldown(self):
        """force=True → skip cooldown."""
        safety = SOPSafetyLayer()
        safety.record_execution("sop-ec2-high-cpu", ["i-123"])
        result = safety.check(sop_id="sop-ec2-high-cpu", resource_ids=["i-123"], force=True)
        assert result.passed is True
        assert any("强制跳过冷却期" in w for w in result.warnings)

    def test_low_confidence_warning(self):
        """Low RCA confidence adds warning."""
        safety = SOPSafetyLayer()
        result = safety.check(
            sop_id="sop-ec2-high-cpu",
            context={"confidence": 0.5},
        )
        assert any("置信度较低" in w for w in result.warnings)

    def test_many_resources_warning(self):
        """More than 5 resources adds warning."""
        safety = SOPSafetyLayer()
        resources = [f"i-{i}" for i in range(10)]
        result = safety.check(sop_id="sop-describe-instances", resource_ids=resources)
        assert any("10 个资源" in w for w in result.warnings)


# =============================================================================
# _classify_risk
# =============================================================================

class TestClassifyRisk:

    def test_known_sop_in_risk_map(self):
        safety = SOPSafetyLayer()
        assert safety._classify_risk("sop-describe-instances") == RiskLevel.L0

    def test_read_only_heuristic(self):
        safety = SOPSafetyLayer()
        assert safety._classify_risk("describe-instances") == RiskLevel.L0
        assert safety._classify_risk("list-buckets") == RiskLevel.L0

    def test_destructive_heuristic(self):
        safety = SOPSafetyLayer()
        assert safety._classify_risk("sop-delete-cluster") == RiskLevel.L3
        assert safety._classify_risk("sop-terminate-instances") == RiskLevel.L3

    def test_modify_heuristic(self):
        safety = SOPSafetyLayer()
        assert safety._classify_risk("sop-modify-config") == RiskLevel.L2

    def test_restart_heuristic(self):
        safety = SOPSafetyLayer()
        assert safety._classify_risk("sop-restart-service") == RiskLevel.L1

    def test_unknown_defaults_l2(self):
        safety = SOPSafetyLayer()
        assert safety._classify_risk("sop-unknown-operation") == RiskLevel.L2


# =============================================================================
# record_execution / create_snapshot
# =============================================================================

class TestExecutionTracking:

    def test_record_execution_updates_cooldowns(self):
        safety = SOPSafetyLayer()
        safety.record_execution("sop-test", ["i-123", "i-456"])
        assert ("sop-test", "i-123") in safety._cooldowns
        assert ("sop-test", "i-456") in safety._cooldowns
        assert "i-123" in safety._resource_cooldowns

    def test_record_execution_updates_count(self):
        safety = SOPSafetyLayer()
        safety.record_execution("sop-test", ["i-123"])
        safety.record_execution("sop-test", ["i-456"])
        assert safety._execution_counts["sop-test"] == 2

    def test_record_execution_no_resources(self):
        safety = SOPSafetyLayer()
        safety.record_execution("sop-test", [])
        assert ("sop-test", "__global__") in safety._cooldowns

    def test_create_snapshot(self):
        safety = SOPSafetyLayer()
        snap = safety.create_snapshot("sop-test", ["i-123"], {"state": "running"})
        assert snap.sop_id == "sop-test"
        assert snap.resource_ids == ["i-123"]
        assert snap.pre_state == {"state": "running"}
        assert snap.snapshot_id.startswith("snap-")

    def test_get_snapshot(self):
        safety = SOPSafetyLayer()
        snap = safety.create_snapshot("sop-test", ["i-123"], {})
        retrieved = safety.get_snapshot(snap.snapshot_id)
        assert retrieved is snap

    def test_get_snapshot_nonexistent(self):
        safety = SOPSafetyLayer()
        assert safety.get_snapshot("nonexistent") is None


# =============================================================================
# Approval Workflow
# =============================================================================

class TestApprovalWorkflow:

    def test_request_approval(self):
        safety = SOPSafetyLayer()
        approval = safety.request_approval("sop-test", context={"incident": "inc-1"})
        assert approval.sop_id == "sop-test"
        assert approval.approved is None
        assert approval.approval_id.startswith("approval-")

    def test_approve(self):
        safety = SOPSafetyLayer()
        approval = safety.request_approval("sop-test")
        result = safety.approve(approval.approval_id, "admin-user")
        assert result.approved is True
        assert result.approved_by == "admin-user"

    def test_approve_nonexistent(self):
        safety = SOPSafetyLayer()
        assert safety.approve("nonexistent", "admin") is None

    def test_approve_already_processed(self):
        safety = SOPSafetyLayer()
        approval = safety.request_approval("sop-test")
        safety.approve(approval.approval_id, "admin")
        # Second approval returns same object
        result = safety.approve(approval.approval_id, "another-admin")
        assert result.approved is True
        assert result.approved_by == "admin"  # Original approver

    def test_approve_expired(self):
        safety = SOPSafetyLayer()
        approval = safety.request_approval("sop-test", expires_minutes=0)
        # Immediately expired
        result = safety.approve(approval.approval_id, "admin")
        assert result.approved is False

    def test_reject(self):
        safety = SOPSafetyLayer()
        approval = safety.request_approval("sop-test")
        result = safety.reject(approval.approval_id, "ops-lead")
        assert result.approved is False
        assert result.approved_by == "ops-lead"

    def test_reject_nonexistent(self):
        safety = SOPSafetyLayer()
        assert safety.reject("nonexistent", "admin") is None

    def test_get_pending_approvals(self):
        safety = SOPSafetyLayer()
        safety.request_approval("sop-1")
        safety.request_approval("sop-2")
        a3 = safety.request_approval("sop-3")
        safety.approve(a3.approval_id, "admin")  # No longer pending

        pending = safety.get_pending_approvals()
        assert len(pending) == 2


# =============================================================================
# get_stats / _reset_daily_counts
# =============================================================================

class TestStats:

    def test_get_stats_empty(self):
        safety = SOPSafetyLayer()
        stats = safety.get_stats()
        assert stats["active_cooldowns"] == 0
        assert stats["snapshots_stored"] == 0

    def test_get_stats_with_data(self):
        safety = SOPSafetyLayer()
        safety.record_execution("sop-1", ["i-123"])
        safety.create_snapshot("sop-1", ["i-123"], {})
        safety.request_approval("sop-2")

        stats = safety.get_stats()
        assert stats["daily_execution_counts"]["sop-1"] == 1
        assert stats["active_cooldowns"] >= 1
        assert stats["snapshots_stored"] == 1
        assert stats["pending_approvals"] == 1

    def test_reset_daily_counts(self):
        safety = SOPSafetyLayer()
        safety._execution_counts = {"sop-1": 5}
        safety._count_reset_date = "2020-01-01"  # Old date
        safety._reset_daily_counts()
        assert safety._execution_counts == {}


# =============================================================================
# Internal Methods
# =============================================================================

class TestInternalMethods:

    def test_determine_mode_l0(self):
        safety = SOPSafetyLayer()
        assert safety._determine_mode(RiskLevel.L0, {}) == ExecutionMode.AUTO

    def test_determine_mode_l1(self):
        safety = SOPSafetyLayer()
        assert safety._determine_mode(RiskLevel.L1, {}) == ExecutionMode.NOTIFY

    def test_determine_mode_l2(self):
        safety = SOPSafetyLayer()
        assert safety._determine_mode(RiskLevel.L2, {}) == ExecutionMode.CONFIRM

    def test_determine_mode_l3(self):
        safety = SOPSafetyLayer()
        assert safety._determine_mode(RiskLevel.L3, {}) == ExecutionMode.APPROVAL

    def test_generate_dry_run_preview(self):
        safety = SOPSafetyLayer()
        preview = safety._generate_dry_run_preview("sop-test", ["i-123"], {})
        assert preview["sop_id"] == "sop-test"
        assert "risk_level" in preview
        assert "daily_limit" in preview

    def test_mode_reason(self):
        safety = SOPSafetyLayer()
        reason = safety._mode_reason(ExecutionMode.AUTO, "sop-test", RiskLevel.L0)
        assert "sop-test" in reason
        assert "L0" in reason


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:

    def test_get_safety_layer_singleton(self):
        import src.sop_safety as mod
        mod._safety = None

        s1 = get_safety_layer()
        s2 = get_safety_layer()
        assert s1 is s2

        mod._safety = None  # cleanup
