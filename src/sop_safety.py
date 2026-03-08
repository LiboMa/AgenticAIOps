"""
SOP Safety Layer — Step 3 of SOP↔RCA Enhancement

Enforces safety constraints before SOP execution:
1. Risk Level Classification (L0-L3)
2. Cooldown Period (prevent rapid re-execution)
3. Dry-Run Mode (preview without executing)
4. Pre-execution Validation (checks resource state)
5. Rollback Tracking (snapshot state before changes)

Level Classification:
  L0 = Read-only (logs, describe, list) → auto
  L1 = Low-risk reversible (restart, scale) → auto with cooldown
  L2 = Medium-risk (config change, failover) → notify + wait for confirm
  L3 = High-risk destructive (delete, terminate) → manual approval required

Design ref: docs/designs/SOP_RCA_ENHANCEMENT_DESIGN.md
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from src.utils.time import ensure_aware
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Risk Level Classification
# =============================================================================

class RiskLevel(Enum):
    L0 = "L0"  # Read-only: describe, list, get logs
    L1 = "L1"  # Low-risk: restart, scale up/down (reversible)
    L2 = "L2"  # Medium-risk: config change, failover
    L3 = "L3"  # High-risk: delete, terminate, destroy


class ExecutionMode(Enum):
    AUTO = "auto"           # Execute immediately (L0, L1)
    NOTIFY = "notify"       # Execute and notify (L1 with cooldown passed)
    CONFIRM = "confirm"     # Notify and wait for confirmation (L2)
    APPROVAL = "approval"   # Require explicit approval (L3)
    BLOCKED = "blocked"     # Blocked by cooldown or policy
    DRY_RUN = "dry_run"     # Preview only, no execution


# AWS API risk classification
API_RISK_MAP = {
    # L0: Read-only
    "describe_instances": RiskLevel.L0,
    "get_metric_data": RiskLevel.L0,
    "describe_alarms": RiskLevel.L0,
    "describe_db_instances": RiskLevel.L0,
    "list_functions": RiskLevel.L0,
    "get_log_events": RiskLevel.L0,
    "describe_auto_scaling_groups": RiskLevel.L0,
    "describe_target_health": RiskLevel.L0,
    "lookup_events": RiskLevel.L0,  # CloudTrail
    
    # L1: Low-risk reversible
    "reboot_instances": RiskLevel.L1,
    "start_instances": RiskLevel.L1,
    "update_auto_scaling_group": RiskLevel.L1,  # scale up/down
    "put_scaling_policy": RiskLevel.L1,
    "update_function_configuration": RiskLevel.L1,
    "update_table": RiskLevel.L1,  # DynamoDB capacity
    "register_targets": RiskLevel.L1,
    "deregister_targets": RiskLevel.L1,
    
    # L2: Medium-risk
    "modify_db_instance": RiskLevel.L2,
    "reboot_db_instance": RiskLevel.L2,
    "failover_db_cluster": RiskLevel.L2,
    "modify_instance_attribute": RiskLevel.L2,
    "authorize_security_group_ingress": RiskLevel.L2,
    "create_snapshot": RiskLevel.L2,
    "modify_volume": RiskLevel.L2,
    "stop_instances": RiskLevel.L2,
    
    # L3: High-risk destructive
    "terminate_instances": RiskLevel.L3,
    "delete_db_instance": RiskLevel.L3,
    "delete_db_cluster": RiskLevel.L3,
    "delete_function": RiskLevel.L3,
    "delete_table": RiskLevel.L3,
    "delete_security_group": RiskLevel.L3,
    "delete_snapshot": RiskLevel.L3,
    "delete_volume": RiskLevel.L3,
}

# SOP-level risk overrides (more conservative)
SOP_RISK_MAP = {
    # L0: Read-only diagnostics
    "sop-describe-instances": RiskLevel.L0,
    "sop-list-resources": RiskLevel.L0,
    "sop-get-metrics": RiskLevel.L0,
    "sop-check-health": RiskLevel.L0,
    "sop-get-logs": RiskLevel.L0,
    # L1: Low-risk reversible
    "sop-ec2-high-cpu": RiskLevel.L1,
    "sop-lambda-errors": RiskLevel.L1,
    "sop-ec2-disk-full": RiskLevel.L1,
    "sop-elb-5xx-spike": RiskLevel.L1,
    "sop-dynamodb-throttle": RiskLevel.L1,
    # L2: Medium-risk
    "sop-rds-storage-low": RiskLevel.L2,
    "sop-ec2-unreachable": RiskLevel.L2,
    # L3: High-risk destructive
    "sop-rds-failover": RiskLevel.L3,
}


# =============================================================================
# Cooldown Configuration
# =============================================================================

# Per risk-level cooldown periods
COOLDOWN_CONFIG = {
    RiskLevel.L0: timedelta(seconds=0),     # No cooldown for read-only
    RiskLevel.L1: timedelta(minutes=5),      # 5 min for low-risk
    RiskLevel.L2: timedelta(minutes=30),     # 30 min for medium-risk
    RiskLevel.L3: timedelta(hours=1),        # 1 hour for high-risk
}

# Per-resource cooldown (prevent hammering same resource)
RESOURCE_COOLDOWN = timedelta(minutes=10)


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class SafetyCheck:
    """Result of a safety pre-check."""
    passed: bool
    risk_level: RiskLevel
    execution_mode: ExecutionMode
    reason: str
    cooldown_remaining_seconds: int = 0
    warnings: List[str] = field(default_factory=list)
    required_approvers: List[str] = field(default_factory=list)
    dry_run_preview: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['risk_level'] = self.risk_level.value
        d['execution_mode'] = self.execution_mode.value
        return d
    
    def to_markdown(self) -> str:
        icon = {
            RiskLevel.L0: "🟢",
            RiskLevel.L1: "🔵",
            RiskLevel.L2: "🟡",
            RiskLevel.L3: "🔴",
        }[self.risk_level]
        
        mode_desc = {
            ExecutionMode.AUTO: "✅ 自动执行",
            ExecutionMode.NOTIFY: "📢 执行并通知",
            ExecutionMode.CONFIRM: "⏳ 等待确认",
            ExecutionMode.APPROVAL: "🔐 需要审批",
            ExecutionMode.BLOCKED: "🚫 已阻止",
            ExecutionMode.DRY_RUN: "👁️ 预览模式",
        }[self.execution_mode]
        
        md = f"""### {icon} 安全检查 — {self.risk_level.value}

**执行模式:** {mode_desc}
**状态:** {'✅ 通过' if self.passed else '❌ 未通过'}
**原因:** {self.reason}
"""
        if self.cooldown_remaining_seconds > 0:
            md += f"**冷却剩余:** {self.cooldown_remaining_seconds}s\n"
        
        if self.warnings:
            md += "\n**⚠️ 警告:**\n"
            for w in self.warnings:
                md += f"- {w}\n"
        
        if self.dry_run_preview:
            md += "\n**📋 Dry-Run 预览:**\n```json\n"
            import json
            md += json.dumps(self.dry_run_preview, indent=2, default=str)
            md += "\n```\n"
        
        return md


@dataclass
class ExecutionSnapshot:
    """State snapshot before SOP execution for rollback."""
    snapshot_id: str
    sop_id: str
    resource_ids: List[str]
    pre_state: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PendingApproval:
    """Pending approval for L2/L3 SOPs."""
    approval_id: str
    sop_id: str
    risk_level: RiskLevel
    requested_by: str
    requested_at: str
    expires_at: str
    context: Dict[str, Any]
    approved: Optional[bool] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None


# =============================================================================
# Safety Layer
# =============================================================================

class SOPSafetyLayer:
    """
    Safety enforcement for SOP execution.
    
    Checks:
    1. Risk level classification (L0-L3)
    2. Cooldown enforcement (prevent rapid re-execution)
    3. Dry-run support (preview mode)
    4. Pre-execution snapshot (for rollback)
    5. Approval workflow (L2/L3)
    """
    
    def __init__(self):
        # Cooldown tracking: {(sop_id, resource_id): last_execution_time}
        self._cooldowns: Dict[Tuple[str, str], datetime] = {}
        # Resource-level cooldown: {resource_id: last_action_time}
        self._resource_cooldowns: Dict[str, datetime] = {}
        # Execution snapshots for rollback
        self._snapshots: Dict[str, ExecutionSnapshot] = {}
        # Pending approvals
        self._pending_approvals: Dict[str, PendingApproval] = {}
        # Execution count tracking (circuit breaker)
        self._execution_counts: Dict[str, int] = {}  # sop_id → count today
        self._count_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Configurable limits
        self.max_daily_executions = {
            RiskLevel.L0: 100,
            RiskLevel.L1: 20,
            RiskLevel.L2: 5,
            RiskLevel.L3: 2,
        }
    
    def check(
        self,
        sop_id: str,
        resource_ids: List[str] = None,
        dry_run: bool = False,
        force: bool = False,
        context: Dict[str, Any] = None,
    ) -> SafetyCheck:
        """
        Run safety checks before SOP execution.
        
        Args:
            sop_id: SOP identifier
            resource_ids: Target resources
            dry_run: If True, always return dry-run mode
            force: Override cooldown (not risk level)
            context: RCA/trigger context
            
        Returns:
            SafetyCheck with verdict
        """
        resource_ids = resource_ids or []
        context = context or {}
        warnings = []
        
        # 1. Classify risk level
        risk_level = self._classify_risk(sop_id)
        
        # 2. Dry-run override
        if dry_run:
            preview = self._generate_dry_run_preview(sop_id, resource_ids, context)
            return SafetyCheck(
                passed=True,
                risk_level=risk_level,
                execution_mode=ExecutionMode.DRY_RUN,
                reason=f"Dry-run 模式: 预览 {sop_id} 对 {len(resource_ids)} 个资源的操作",
                dry_run_preview=preview,
            )
        
        # 3. Check daily execution limit (circuit breaker)
        self._reset_daily_counts()
        current_count = self._execution_counts.get(sop_id, 0)
        max_count = self.max_daily_executions.get(risk_level, 10)
        
        if current_count >= max_count:
            return SafetyCheck(
                passed=False,
                risk_level=risk_level,
                execution_mode=ExecutionMode.BLOCKED,
                reason=f"日执行上限: {sop_id} 已执行 {current_count}/{max_count} 次",
                warnings=[f"Circuit breaker: 达到 {risk_level.value} 级别日上限"],
            )
        
        # 4. Check cooldown
        if not force:
            cooldown_check = self._check_cooldown(sop_id, resource_ids, risk_level)
            if cooldown_check:
                remaining, source = cooldown_check
                return SafetyCheck(
                    passed=False,
                    risk_level=risk_level,
                    execution_mode=ExecutionMode.BLOCKED,
                    reason=f"冷却期: {source} 需等待 {remaining}s",
                    cooldown_remaining_seconds=remaining,
                    warnings=[f"上次执行时间过近，请等待冷却期结束"],
                )
        elif force:
            warnings.append("⚠️ 强制跳过冷却期")
        
        # 5. Determine execution mode based on risk level
        mode = self._determine_mode(risk_level, context)
        
        # 6. Additional warnings
        if risk_level in (RiskLevel.L2, RiskLevel.L3):
            warnings.append(f"操作风险等级: {risk_level.value}")
        
        if len(resource_ids) > 5:
            warnings.append(f"影响 {len(resource_ids)} 个资源 — 请确认范围")
        
        rca_confidence = context.get('confidence', 0)
        if rca_confidence > 0 and rca_confidence < 0.7:
            warnings.append(f"RCA 置信度较低 ({rca_confidence:.0%})，建议人工确认")
            if risk_level != RiskLevel.L0:
                mode = ExecutionMode.CONFIRM  # Downgrade to confirm for low-confidence
        
        # 7. Approval requirements for L3
        required_approvers = []
        if risk_level == RiskLevel.L3:
            required_approvers = ["admin", "ops-lead"]
            mode = ExecutionMode.APPROVAL
        
        passed = mode not in (ExecutionMode.BLOCKED, ExecutionMode.APPROVAL)
        
        return SafetyCheck(
            passed=passed,
            risk_level=risk_level,
            execution_mode=mode,
            reason=self._mode_reason(mode, sop_id, risk_level),
            warnings=warnings,
            required_approvers=required_approvers,
        )
    
    def record_execution(self, sop_id: str, resource_ids: List[str]):
        """Record that a SOP was executed (update cooldowns + counts)."""
        now = datetime.now(timezone.utc)
        
        # SOP-level cooldown
        for rid in resource_ids:
            self._cooldowns[(sop_id, rid)] = now
            self._resource_cooldowns[rid] = now
        
        # Bare SOP cooldown (no specific resource)
        if not resource_ids:
            self._cooldowns[(sop_id, "__global__")] = now
        
        # Daily count
        self._execution_counts[sop_id] = self._execution_counts.get(sop_id, 0) + 1
        
        logger.info(
            f"Recorded execution: {sop_id} on {len(resource_ids)} resources "
            f"(daily count: {self._execution_counts[sop_id]})"
        )
    
    def create_snapshot(
        self,
        sop_id: str,
        resource_ids: List[str],
        pre_state: Dict[str, Any],
    ) -> ExecutionSnapshot:
        """Create a pre-execution state snapshot for rollback."""
        snapshot_id = f"snap-{sop_id}-{int(time.time())}"
        snapshot = ExecutionSnapshot(
            snapshot_id=snapshot_id,
            sop_id=sop_id,
            resource_ids=resource_ids,
            pre_state=pre_state,
        )
        self._snapshots[snapshot_id] = snapshot
        logger.info(f"Created snapshot {snapshot_id} for {sop_id}")
        return snapshot
    
    def get_snapshot(self, snapshot_id: str) -> Optional[ExecutionSnapshot]:
        """Retrieve a snapshot for rollback."""
        return self._snapshots.get(snapshot_id)
    
    def request_approval(
        self,
        sop_id: str,
        requested_by: str = "rca_auto",
        context: Dict[str, Any] = None,
        expires_minutes: int = 60,
    ) -> PendingApproval:
        """Create an approval request for L2/L3 SOPs."""
        now = datetime.now(timezone.utc)
        approval_id = f"approval-{sop_id}-{int(time.time())}"
        
        approval = PendingApproval(
            approval_id=approval_id,
            sop_id=sop_id,
            risk_level=self._classify_risk(sop_id),
            requested_by=requested_by,
            requested_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=expires_minutes)).isoformat(),
            context=context or {},
        )
        
        self._pending_approvals[approval_id] = approval
        logger.info(f"Created approval request {approval_id} for {sop_id}")
        return approval
    
    def approve(self, approval_id: str, approved_by: str) -> Optional[PendingApproval]:
        """Approve a pending request."""
        approval = self._pending_approvals.get(approval_id)
        if not approval:
            return None
        
        if approval.approved is not None:
            logger.warning(f"Approval {approval_id} already processed")
            return approval
        
        # Check expiry
        expires = ensure_aware(approval.expires_at)
        if datetime.now(timezone.utc) > expires:
            approval.approved = False
            logger.warning(f"Approval {approval_id} expired")
            return approval
        
        approval.approved = True
        approval.approved_by = approved_by
        approval.approved_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Approved {approval_id} by {approved_by}")
        return approval
    
    def reject(self, approval_id: str, rejected_by: str) -> Optional[PendingApproval]:
        """Reject a pending request."""
        approval = self._pending_approvals.get(approval_id)
        if not approval:
            return None
        
        approval.approved = False
        approval.approved_by = rejected_by
        approval.approved_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Rejected {approval_id} by {rejected_by}")
        return approval
    
    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Get all pending approvals."""
        pending = []
        now = datetime.now(timezone.utc)
        for a in self._pending_approvals.values():
            if a.approved is None:
                expires = datetime.fromisoformat(a.expires_at)
                if now <= expires:
                    d = asdict(a)
                    d['risk_level'] = a.risk_level.value
                    pending.append(d)
        return pending
    
    def get_stats(self) -> Dict[str, Any]:
        """Get safety layer statistics."""
        self._reset_daily_counts()
        return {
            "daily_execution_counts": dict(self._execution_counts),
            "active_cooldowns": len(self._cooldowns),
            "snapshots_stored": len(self._snapshots),
            "pending_approvals": len(self.get_pending_approvals()),
            "cooldown_config": {
                level.value: str(delta) for level, delta in COOLDOWN_CONFIG.items()
            },
            "daily_limits": {
                level.value: limit for level, limit in self.max_daily_executions.items()
            },
        }
    
    # =========================================================================
    # Internal Methods
    # =========================================================================
    
    def _classify_risk(self, sop_id: str) -> RiskLevel:
        """Classify the risk level of a SOP."""
        # First check SOP-level overrides
        if sop_id in SOP_RISK_MAP:
            return SOP_RISK_MAP[sop_id]
        
        # Pattern matching: read-only operations → L0
        sop_lower = sop_id.lower()
        if any(kw in sop_lower for kw in ['describe', 'list', 'get-', 'check', 'read']):
            return RiskLevel.L0
        
        # Default based on SOP name heuristics
        if any(kw in sop_lower for kw in ['delete', 'terminate', 'destroy', 'failover']):
            return RiskLevel.L3
        if any(kw in sop_lower for kw in ['modify', 'config', 'stop', 'storage']):
            return RiskLevel.L2
        if any(kw in sop_lower for kw in ['restart', 'reboot', 'scale', 'clean']):
            return RiskLevel.L1
        
        return RiskLevel.L2  # Default to L2 (safe: require confirmation for unknown SOPs)
    
    def _check_cooldown(
        self, sop_id: str, resource_ids: List[str], risk_level: RiskLevel
    ) -> Optional[Tuple[int, str]]:
        """Check if cooldown period is active. Returns (remaining_seconds, source) or None."""
        now = datetime.now(timezone.utc)
        cooldown_period = COOLDOWN_CONFIG.get(risk_level, timedelta(minutes=5))
        
        if cooldown_period.total_seconds() == 0:
            return None  # No cooldown for L0
        
        # Check SOP + resource cooldown
        for rid in resource_ids:
            key = (sop_id, rid)
            if key in self._cooldowns:
                elapsed = now - self._cooldowns[key]
                if elapsed < cooldown_period:
                    remaining = int((cooldown_period - elapsed).total_seconds())
                    return (remaining, f"{sop_id} on {rid}")
        
        # Check global SOP cooldown
        global_key = (sop_id, "__global__")
        if global_key in self._cooldowns:
            elapsed = now - self._cooldowns[global_key]
            if elapsed < cooldown_period:
                remaining = int((cooldown_period - elapsed).total_seconds())
                return (remaining, f"{sop_id} (global)")
        
        # Check resource-level cooldown (any SOP on same resource)
        for rid in resource_ids:
            if rid in self._resource_cooldowns:
                elapsed = now - self._resource_cooldowns[rid]
                if elapsed < RESOURCE_COOLDOWN:
                    remaining = int((RESOURCE_COOLDOWN - elapsed).total_seconds())
                    return (remaining, f"resource {rid}")
        
        return None
    
    def _determine_mode(self, risk_level: RiskLevel, context: Dict) -> ExecutionMode:
        """Determine execution mode from risk level and context."""
        mode_map = {
            RiskLevel.L0: ExecutionMode.AUTO,
            RiskLevel.L1: ExecutionMode.NOTIFY,
            RiskLevel.L2: ExecutionMode.CONFIRM,
            RiskLevel.L3: ExecutionMode.APPROVAL,
        }
        return mode_map.get(risk_level, ExecutionMode.CONFIRM)
    
    def _generate_dry_run_preview(
        self, sop_id: str, resource_ids: List[str], context: Dict
    ) -> Dict[str, Any]:
        """Generate a preview of what the SOP would do."""
        risk_level = self._classify_risk(sop_id)
        
        return {
            "sop_id": sop_id,
            "risk_level": risk_level.value,
            "target_resources": resource_ids,
            "execution_mode": self._determine_mode(risk_level, context).value,
            "cooldown_after": str(COOLDOWN_CONFIG.get(risk_level, "5 min")),
            "daily_limit": self.max_daily_executions.get(risk_level, 10),
            "current_daily_count": self._execution_counts.get(sop_id, 0),
            "preview_note": "This is a dry-run. No changes will be made.",
        }
    
    def _mode_reason(self, mode: ExecutionMode, sop_id: str, risk_level: RiskLevel) -> str:
        """Generate human-readable reason for execution mode."""
        reasons = {
            ExecutionMode.AUTO: f"{sop_id} ({risk_level.value}) — 自动执行",
            ExecutionMode.NOTIFY: f"{sop_id} ({risk_level.value}) — 执行并通知",
            ExecutionMode.CONFIRM: f"{sop_id} ({risk_level.value}) — 需要确认后执行",
            ExecutionMode.APPROVAL: f"{sop_id} ({risk_level.value}) — 需要审批: admin/ops-lead",
            ExecutionMode.BLOCKED: f"{sop_id} — 已阻止",
            ExecutionMode.DRY_RUN: f"{sop_id} — 预览模式",
        }
        return reasons.get(mode, str(mode))
    
    def _reset_daily_counts(self):
        """Reset daily execution counts if date changed."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._count_reset_date:
            self._execution_counts.clear()
            self._count_reset_date = today


# =============================================================================
# Singleton
# =============================================================================

_safety: Optional[SOPSafetyLayer] = None


def get_safety_layer() -> SOPSafetyLayer:
    """Get or create the safety layer singleton."""
    global _safety
    if _safety is None:
        _safety = SOPSafetyLayer()
    return _safety
