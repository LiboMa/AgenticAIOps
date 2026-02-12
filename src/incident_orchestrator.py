"""
Incident Orchestrator — Step 4 Closed-Loop Integration

Ties together Step 1 (Data Collection) → Step 2 (RCA Inference) → 
Step 3 (Safety Layer) → SOP Execution into a single automated pipeline.

Flow:
  Alert/Trigger → Collect → Analyze → Match SOP → Safety Check → Execute → Learn
       ↑                                                              │
       └─────────────── Feedback Loop ────────────────────────────────┘

Trigger types:
  - CloudWatch Alarm (auto)
  - Anomaly Detection (auto)
  - Health Event (auto)
  - Manual chat command (user)

Design ref: docs/designs/SOP_RCA_ENHANCEMENT_DESIGN.md
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class TriggerType(Enum):
    ALARM = "alarm"
    ANOMALY = "anomaly"
    HEALTH_EVENT = "health_event"
    MANUAL = "manual"
    PROACTIVE = "proactive"


class IncidentStatus(Enum):
    TRIGGERED = "triggered"
    COLLECTING = "collecting"
    ANALYZING = "analyzing"
    SOP_MATCHED = "sop_matched"
    SAFETY_CHECK = "safety_check"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IncidentRecord:
    """Full lifecycle record of an incident through the pipeline."""
    incident_id: str
    trigger_type: TriggerType
    trigger_data: Dict[str, Any]
    region: str
    status: IncidentStatus = IncidentStatus.TRIGGERED
    
    # Pipeline results
    collection_summary: Optional[Dict[str, Any]] = None
    rca_result: Optional[Dict[str, Any]] = None
    matched_sops: Optional[List[Dict[str, Any]]] = None
    safety_check: Optional[Dict[str, Any]] = None
    execution_result: Optional[Dict[str, Any]] = None
    
    # Timing
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    duration_ms: int = 0
    stage_timings: Dict[str, int] = field(default_factory=dict)
    
    # Errors
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['trigger_type'] = self.trigger_type.value
        d['status'] = self.status.value
        return d
    
    def to_markdown(self) -> str:
        """Generate markdown incident report."""
        status_icon = {
            IncidentStatus.TRIGGERED: "🔔",
            IncidentStatus.COLLECTING: "📡",
            IncidentStatus.ANALYZING: "🧠",
            IncidentStatus.SOP_MATCHED: "🔍",
            IncidentStatus.SAFETY_CHECK: "🛡️",
            IncidentStatus.EXECUTING: "⚡",
            IncidentStatus.WAITING_APPROVAL: "🔐",
            IncidentStatus.COMPLETED: "✅",
            IncidentStatus.FAILED: "❌",
        }.get(self.status, "❓")
        
        md = f"""## {status_icon} 事件 `{self.incident_id[:12]}`

| 属性 | 值 |
|------|-----|
| 触发类型 | {self.trigger_type.value} |
| 状态 | {self.status.value} |
| 区域 | {self.region} |
| 总耗时 | {self.duration_ms}ms |
| 时间 | {self.created_at} |
"""
        # Stage timings
        if self.stage_timings:
            md += "\n### ⏱️ 各阶段耗时\n\n"
            md += "| 阶段 | 耗时 |\n|------|------|\n"
            for stage, ms in self.stage_timings.items():
                md += f"| {stage} | {ms}ms |\n"
        
        # RCA Result
        if self.rca_result:
            rca = self.rca_result
            sev = rca.get('severity', 'unknown')
            sev_icon = '🔴' if sev == 'high' else '🟡' if sev == 'medium' else '🟢'
            md += f"\n### 🔍 根因分析\n\n"
            md += f"**根因:** {rca.get('root_cause', 'N/A')}\n"
            md += f"**严重性:** {sev_icon} {sev.upper()}\n"
            md += f"**置信度:** {rca.get('confidence', 0):.0%}\n"
            md += f"**模型:** `{rca.get('pattern_id', 'N/A')}`\n"
            
            evidence = rca.get('evidence', [])
            if evidence:
                md += "\n**证据:**\n"
                for e in evidence[:5]:
                    md += f"- {e}\n"
        
        # SOP Match
        if self.matched_sops:
            md += "\n### 🛠️ 推荐 SOP\n\n"
            md += "| SOP | 名称 | 风险 | 匹配度 |\n|-----|------|------|--------|\n"
            for sop in self.matched_sops[:3]:
                md += f"| `{sop['sop_id']}` | {sop['name']} | {sop.get('risk_level', '?')} | {sop['match_confidence']:.0%} |\n"
        
        # Safety Check
        if self.safety_check:
            sc = self.safety_check
            md += f"\n### 🛡️ 安全检查\n\n"
            md += f"**风险等级:** {sc.get('risk_level', '?')}\n"
            md += f"**执行模式:** {sc.get('execution_mode', '?')}\n"
            md += f"**通过:** {'✅' if sc.get('passed') else '❌'}\n"
        
        # Execution Result
        if self.execution_result:
            ex = self.execution_result
            md += f"\n### ⚡ 执行结果\n\n"
            md += f"**SOP:** `{ex.get('sop_id', '?')}`\n"
            md += f"**结果:** {'✅ 成功' if ex.get('success') else '❌ 失败'}\n"
            if ex.get('message'):
                md += f"**详情:** {ex['message']}\n"
        
        # Error
        if self.error:
            md += f"\n### ❌ 错误\n\n```\n{self.error}\n```\n"
        
        return md


class IncidentOrchestrator:
    """
    Main orchestrator that connects all pipeline stages.
    
    Alert → Collect (Step 1) → Analyze (Step 2) → Safety (Step 3) → Execute → Learn
    """
    
    def __init__(self, region: str = "ap-southeast-1"):
        self.region = region
        self._incidents: Dict[str, IncidentRecord] = {}
    
    async def handle_incident(
        self,
        trigger_type: str = "manual",
        trigger_data: Dict[str, Any] = None,
        services: List[str] = None,
        auto_execute: bool = False,
        dry_run: bool = False,
        force: bool = False,
        lookback_minutes: int = 15,
    ) -> IncidentRecord:
        """
        Full closed-loop incident handling pipeline.
        
        Args:
            trigger_type: alarm/anomaly/health_event/manual
            trigger_data: Raw trigger data
            services: Service filter for data collection
            auto_execute: Auto-execute matched SOPs
            dry_run: Preview only
            force: Override cooldowns
            
        Returns:
            IncidentRecord with full pipeline results
        """
        incident_id = f"inc-{uuid.uuid4().hex[:12]}"
        start_time = time.time()
        
        incident = IncidentRecord(
            incident_id=incident_id,
            trigger_type=TriggerType(trigger_type),
            trigger_data=trigger_data or {},
            region=self.region,
        )
        self._incidents[incident_id] = incident
        
        try:
            # ── Stage 1: Data Collection ──────────────────────────
            incident.status = IncidentStatus.COLLECTING
            stage_start = time.time()
            
            from src.event_correlator import get_correlator
            correlator = get_correlator(self.region)
            
            event = await correlator.collect(
                services=services,
                lookback_minutes=lookback_minutes,  # User-configurable, default 15
            )
            
            incident.collection_summary = {
                "collection_id": event.collection_id,
                "metrics": len(event.metrics),
                "alarms": len(event.alarms),
                "trail_events": len(event.trail_events),
                "anomalies": len(event.anomalies),
                "health_events": len(event.health_events),
                "duration_ms": event.duration_ms,
            }
            incident.stage_timings["collect"] = int((time.time() - stage_start) * 1000)
            
            # ── Stage 2: RCA Inference ────────────────────────────
            incident.status = IncidentStatus.ANALYZING
            stage_start = time.time()
            
            from src.rca_inference import get_rca_inference_engine
            engine = get_rca_inference_engine()
            
            rca_result = await engine.analyze(event)
            
            incident.rca_result = rca_result.to_dict()
            incident.stage_timings["analyze"] = int((time.time() - stage_start) * 1000)
            
            # ── Stage 3: SOP Matching ─────────────────────────────
            incident.status = IncidentStatus.SOP_MATCHED
            stage_start = time.time()
            
            from src.rca_sop_bridge import get_bridge
            bridge = get_bridge()
            
            # Match SOPs using the bridge (pass pre-computed RCA result)
            matched_sops = bridge._find_matching_sops(rca_result)
            
            # Enrich with auto_execute policy
            for sop in matched_sops:
                sop_severity = sop.get('severity', 'medium')
                sop['auto_execute'] = (
                    sop_severity == 'low' and rca_result.confidence >= 0.8
                )
            incident.matched_sops = matched_sops
            incident.stage_timings["sop_match"] = int((time.time() - stage_start) * 1000)
            
            # ── Stage 4: Safety Check ─────────────────────────────
            if matched_sops:
                incident.status = IncidentStatus.SAFETY_CHECK
                stage_start = time.time()
                
                from src.sop_safety import get_safety_layer
                safety = get_safety_layer()
                
                best_sop = matched_sops[0]
                
                # Extract resource IDs from RCA
                # Prefer affected_resources from RCA, fallback to matched_symptoms
                resource_ids = (
                    getattr(rca_result, 'affected_resources', None)
                    or getattr(rca_result, 'matched_symptoms', None)
                    or []
                )
                
                safety_result = safety.check(
                    sop_id=best_sop['sop_id'],
                    resource_ids=resource_ids,
                    dry_run=dry_run,
                    force=force,
                    context={
                        "confidence": rca_result.confidence,
                        "severity": rca_result.severity.value if hasattr(rca_result.severity, 'value') else str(rca_result.severity),
                        "incident_id": incident_id,
                    },
                )
                
                # Enrich matched SOPs with risk level
                for sop in matched_sops:
                    sop['risk_level'] = safety._classify_risk(sop['sop_id']).value
                
                incident.safety_check = safety_result.to_dict()
                incident.stage_timings["safety_check"] = int((time.time() - stage_start) * 1000)
                
                # ── Stage 5: Execute or Wait ──────────────────────
                if auto_execute and safety_result.passed and not dry_run:
                    incident.status = IncidentStatus.EXECUTING
                    stage_start = time.time()
                    
                    exec_result = self._execute_sop(
                        best_sop['sop_id'],
                        rca_result,
                        resource_ids,
                        safety,
                    )
                    
                    incident.execution_result = exec_result
                    incident.stage_timings["execute"] = int((time.time() - stage_start) * 1000)
                    
                elif safety_result.execution_mode == "approval":
                    incident.status = IncidentStatus.WAITING_APPROVAL
                    
                    # Create approval request
                    approval = safety.request_approval(
                        sop_id=best_sop['sop_id'],
                        context={
                            "incident_id": incident_id,
                            "root_cause": rca_result.root_cause,
                            "confidence": rca_result.confidence,
                        },
                    )
                    incident.execution_result = {
                        "action": "approval_requested",
                        "approval_id": approval.approval_id,
                        "sop_id": best_sop['sop_id'],
                        "message": f"需要审批: {approval.approval_id}",
                    }
            
            # ── Complete ──────────────────────────────────────────
            if incident.status not in (IncidentStatus.WAITING_APPROVAL,):
                incident.status = IncidentStatus.COMPLETED
            
            incident.completed_at = datetime.utcnow().isoformat()
            incident.duration_ms = int((time.time() - start_time) * 1000)
            
            logger.info(
                f"Incident {incident_id} completed: {incident.status.value} "
                f"in {incident.duration_ms}ms"
            )
            
            return incident
            
        except Exception as e:
            incident.status = IncidentStatus.FAILED
            incident.error = str(e)
            incident.duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Incident {incident_id} failed: {e}")
            return incident
    
    def _execute_sop(
        self,
        sop_id: str,
        rca_result,
        resource_ids: List[str],
        safety,
    ) -> Dict[str, Any]:
        """Execute a SOP with safety recording."""
        try:
            from src.sop_system import get_sop_executor
            
            executor = get_sop_executor()
            
            # Create snapshot before execution
            snapshot = safety.create_snapshot(
                sop_id=sop_id,
                resource_ids=resource_ids,
                pre_state={"rca_severity": rca_result.severity.value if hasattr(rca_result.severity, 'value') else str(rca_result.severity)},
            )
            
            # Execute
            execution = executor.start_execution(
                sop_id=sop_id,
                triggered_by="incident_orchestrator",
                context={
                    "rca_pattern_id": rca_result.pattern_id,
                    "root_cause": rca_result.root_cause,
                    "snapshot_id": snapshot.snapshot_id,
                },
            )
            
            # Record execution in safety layer
            safety.record_execution(sop_id, resource_ids)
            
            if execution:
                return {
                    "success": True,
                    "sop_id": sop_id,
                    "execution_id": execution.execution_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "message": f"SOP {sop_id} 已启动",
                }
            else:
                return {
                    "success": False,
                    "sop_id": sop_id,
                    "message": "SOP executor returned None",
                }
        except Exception as e:
            return {
                "success": False,
                "sop_id": sop_id,
                "message": str(e),
            }
    
    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]:
        """Get an incident by ID."""
        return self._incidents.get(incident_id)
    
    def list_incidents(self, limit: int = 20, status: str = None) -> List[Dict[str, Any]]:
        """List recent incidents."""
        incidents = list(self._incidents.values())
        
        if status:
            incidents = [i for i in incidents if i.status.value == status]
        
        incidents.sort(key=lambda x: x.created_at, reverse=True)
        return [i.to_dict() for i in incidents[:limit]]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        incidents = list(self._incidents.values())
        
        by_status = {}
        for i in incidents:
            by_status[i.status.value] = by_status.get(i.status.value, 0) + 1
        
        completed = [i for i in incidents if i.status == IncidentStatus.COMPLETED]
        avg_duration = (
            sum(i.duration_ms for i in completed) / len(completed)
            if completed else 0
        )
        
        # Average stage timings
        avg_stages = {}
        for i in completed:
            for stage, ms in i.stage_timings.items():
                if stage not in avg_stages:
                    avg_stages[stage] = []
                avg_stages[stage].append(ms)
        
        avg_stages = {
            stage: int(sum(times) / len(times))
            for stage, times in avg_stages.items()
        }
        
        return {
            "total_incidents": len(incidents),
            "by_status": by_status,
            "avg_duration_ms": int(avg_duration),
            "avg_stage_timings": avg_stages,
            "target_ms": 25000,
            "within_target": avg_duration <= 25000 if completed else True,
        }


# =============================================================================
# Singleton
# =============================================================================

_orchestrator: Optional[IncidentOrchestrator] = None


def get_orchestrator(region: str = "ap-southeast-1") -> IncidentOrchestrator:
    """Get or create the incident orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = IncidentOrchestrator(region=region)
    return _orchestrator
