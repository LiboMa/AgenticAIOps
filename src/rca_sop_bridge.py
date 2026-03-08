"""
RCA ↔ SOP Bridge - Connects Root Cause Analysis with SOP Execution

Core enhancement: When RCA identifies a root cause, automatically suggest
and optionally trigger relevant SOPs. When SOPs complete, feed results
back into RCA pattern learning.

Flow:
  Anomaly → RCA Engine → Pattern Match → SOP Suggestion → Execute → Learn
                ↑                                              │
                └──────── Feedback Loop ───────────────────────┘
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# =============================================================================
# RCA → SOP Mapping Rules
# =============================================================================

# Maps RCA pattern IDs / root cause keywords to SOP IDs
RCA_SOP_MAPPING = {
    # Pattern-based mapping (exact match from rca_patterns.yaml)
    "oom-001": ["sop-ec2-high-cpu"],
    "crash-001": ["sop-lambda-errors"],
    "image-001": [],
    "cpu-001": ["sop-ec2-high-cpu"],
    "network-001": ["sop-ec2-unreachable", "sop-elb-5xx-spike"],
    "pvc-001": ["sop-ec2-disk-full"],
    "node-001": ["sop-ec2-unreachable"],
    
    # Legacy pattern IDs (descriptive names)
    "oom-killed": ["sop-ec2-high-cpu"],
    "crash-loop": ["sop-lambda-errors"],
    "image-pull-failure": [],
    "node-not-ready": ["sop-ec2-unreachable"],
    "rds-connection-failure": ["sop-rds-failover"],
    
    # Keyword-based mapping (English + Chinese)
    "high_cpu": ["sop-ec2-high-cpu"],
    "high_memory": ["sop-ec2-high-cpu"],
    "database": ["sop-rds-failover"],
    "lambda_error": ["sop-lambda-errors"],
    "timeout": ["sop-lambda-errors"],
    "disk_full": ["sop-ec2-disk-full"],
    "disk": ["sop-ec2-disk-full"],
    "storage": ["sop-rds-storage-low"],
    "5xx": ["sop-elb-5xx-spike"],
    "error_spike": ["sop-elb-5xx-spike"],
    "unreachable": ["sop-ec2-unreachable"],
    "status_check": ["sop-ec2-unreachable"],
    "throttl": ["sop-dynamodb-throttle"],
    "dynamodb": ["sop-dynamodb-throttle"],
    "capacity": ["sop-dynamodb-throttle"],
    
    # Chinese keyword mapping
    "节点": ["sop-ec2-unreachable"],
    "网络故障": ["sop-ec2-unreachable", "sop-elb-5xx-spike"],
    "kubelet": ["sop-ec2-unreachable"],
    "磁盘": ["sop-ec2-disk-full"],
    "cpu": ["sop-ec2-high-cpu"],
    "内存": ["sop-ec2-high-cpu"],
    "数据库": ["sop-rds-failover"],
    "存储": ["sop-rds-storage-low"],
    "限流": ["sop-dynamodb-throttle"],
    "超时": ["sop-lambda-errors"],
    "错误": ["sop-lambda-errors"],
    "不可达": ["sop-ec2-unreachable"],
    
    # LLM pattern mappings
    "llm-sonnet-resource": ["sop-ec2-high-cpu", "sop-ec2-disk-full"],
    "llm-sonnet-config": ["sop-ec2-unreachable"],
    "llm-sonnet-network": ["sop-ec2-unreachable", "sop-elb-5xx-spike"],
    "llm-sonnet-application": ["sop-lambda-errors"],
    "llm-opus-resource": ["sop-ec2-high-cpu", "sop-ec2-disk-full"],
    "llm-opus-config": ["sop-ec2-unreachable"],
    
    # Healthy / no-issue
    "healthy": [],
}

# Severity → auto-execution policy
AUTO_EXECUTE_POLICY = {
    "low": True,       # Auto-execute for low severity
    "medium": False,    # Suggest only, require approval
    "high": False,      # Suggest only, require approval
}


@dataclass
class RCASOPResult:
    """Combined RCA + SOP recommendation result."""
    # RCA data
    rca_pattern_id: str
    root_cause: str
    severity: str
    confidence: float
    evidence: List[str]
    
    # SOP recommendations
    suggested_sops: List[Dict[str, Any]] = field(default_factory=list)
    auto_executed_sop: Optional[str] = None
    execution_id: Optional[str] = None
    
    # Bridge metadata
    bridge_confidence: float = 0.0  # How confident the SOP suggestion is
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        md = f"""## 🔍 Root Cause Analysis Result

**Root Cause:** {self.root_cause}
**Severity:** {'🔴' if self.severity == 'high' else '🟡' if self.severity == 'medium' else '🟢'} {self.severity.upper()}
**Confidence:** {self.confidence:.0%}
**Pattern:** `{self.rca_pattern_id}`

### 📋 Evidence
"""
        for e in self.evidence:
            md += f"- {e}\n"
        
        if self.suggested_sops:
            md += "\n### 🛠️ Recommended SOPs\n\n"
            md += "| SOP | Name | Steps | Est. Time | Auto-Execute |\n"
            md += "|-----|------|-------|-----------|--------------|\n"
            for sop in self.suggested_sops:
                auto = "✅ Yes" if sop.get('auto_execute') else "❌ Manual"
                md += f"| `{sop['sop_id']}` | {sop['name']} | {sop['steps']} | {sop['est_minutes']}min | {auto} |\n"
            
            md += f"\n使用 `sop run <sop_id>` 执行推荐的 SOP"
        
        if self.auto_executed_sop:
            md += f"\n\n### ⚡ Auto-Executed\n\nSOP `{self.auto_executed_sop}` 已自动启动 (执行 ID: `{self.execution_id}`)"
        
        return md


@dataclass
class SOPFeedback:
    """Feedback from SOP execution back to RCA."""
    execution_id: str
    sop_id: str
    rca_pattern_id: str
    success: bool
    resolution_time_seconds: int
    steps_completed: int
    steps_total: int
    root_cause_confirmed: bool
    notes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RCASOPBridge:
    """
    Bridge between RCA Engine and SOP System.
    
    Responsibilities:
    1. RCA → SOP: Map RCA results to SOP suggestions
    2. SOP → RCA: Feed execution results back to improve patterns
    3. Auto-execute: Trigger SOPs automatically for low-severity issues
    4. Learning: Build a feedback loop for pattern refinement
    """
    
    def __init__(self):
        self._feedbacks: List[SOPFeedback] = []
        self._execution_history: Dict[str, RCASOPResult] = {}
        # Track which RCA patterns lead to successful SOP resolutions
        self._success_map: Dict[str, Dict[str, int]] = {}  # pattern_id → {sop_id: success_count}
        self._failure_map: Dict[str, Dict[str, int]] = {}  # pattern_id → {sop_id: failure_count}
        # Load persisted learning data
        self._load_learning_data()
    
    def analyze_and_suggest(
        self,
        namespace: str = None,
        pod: str = None,
        telemetry: Dict[str, Any] = None,
        symptoms: List[str] = None,
        auto_execute: bool = False,
    ) -> RCASOPResult:
        """
        Run RCA analysis and suggest/execute SOPs.
        
        This is the main entry point that combines RCA + SOP.
        
        Args:
            namespace: K8s namespace to analyze
            pod: Specific pod
            telemetry: Pre-collected telemetry data
            symptoms: Symptom strings for direct analysis
            auto_execute: Whether to auto-execute low-severity SOPs
            
        Returns:
            RCASOPResult with diagnosis and SOP recommendations
        """
        from src.rca.engine import RCAEngine
        
        engine = RCAEngine()
        
        # Step 1: Run RCA
        if symptoms:
            rca_result = engine.analyze_from_symptoms(symptoms)
        elif telemetry:
            rca_result = engine.analyze(
                namespace=namespace or "default",
                telemetry=telemetry
            )
        elif namespace:
            rca_result = engine.analyze(namespace=namespace, pod=pod)
        else:
            rca_result = engine.analyze_from_symptoms(["unknown issue"])
        
        # Step 2: Map RCA result to SOP suggestions
        suggested_sops = self._find_matching_sops(rca_result)
        
        # Step 3: Build combined result
        result = RCASOPResult(
            rca_pattern_id=rca_result.pattern_id,
            root_cause=rca_result.root_cause,
            severity=rca_result.severity.value,
            confidence=rca_result.confidence,
            evidence=rca_result.evidence,
            suggested_sops=suggested_sops,
            bridge_confidence=self._calculate_bridge_confidence(
                rca_result.pattern_id, suggested_sops
            ),
        )
        
        # Step 4: Auto-execute if policy allows
        if auto_execute and suggested_sops:
            severity = rca_result.severity.value
            if AUTO_EXECUTE_POLICY.get(severity, False) and rca_result.confidence >= 0.8:
                best_sop = suggested_sops[0]
                execution = self._auto_execute_sop(
                    best_sop['sop_id'],
                    rca_result
                )
                if execution:
                    result.auto_executed_sop = best_sop['sop_id']
                    result.execution_id = execution.execution_id
        
        # Store for tracking
        self._execution_history[result.timestamp] = result
        
        return result
    
    def match_sops(self, rca_result) -> List[Dict[str, Any]]:
        """
        Public API: Match SOPs against an already-computed RCA result.
        Use this when the orchestrator has already run RCA inference.
        """
        return self._find_matching_sops(rca_result)
    
    def _find_matching_sops(self, rca_result) -> List[Dict[str, Any]]:
        """Find SOPs matching an RCA result."""
        from src.sop_system import get_sop_store
        
        store = get_sop_store()
        matched_sops = []
        
        # Strategy 1: Direct pattern ID mapping
        pattern_id = rca_result.pattern_id
        if pattern_id in RCA_SOP_MAPPING:
            for sop_id in RCA_SOP_MAPPING[pattern_id]:
                sop = store.get_sop(sop_id)
                if sop:
                    matched_sops.append(self._sop_to_suggestion(sop, "pattern_match", 0.9))
        
        # Strategy 2: Keyword matching from root cause text
        root_cause_lower = rca_result.root_cause.lower()
        for keyword, sop_ids in RCA_SOP_MAPPING.items():
            if keyword.replace("_", " ") in root_cause_lower or keyword in root_cause_lower:
                for sop_id in sop_ids:
                    if not any(s['sop_id'] == sop_id for s in matched_sops):
                        sop = store.get_sop(sop_id)
                        if sop:
                            matched_sops.append(self._sop_to_suggestion(sop, "keyword_match", 0.7))
        
        # Strategy 3: Use SOP store's suggest function
        service = self._extract_service(rca_result)
        keywords = self._extract_keywords(rca_result)
        if service:
            suggested = store.suggest_sops(service, keywords)
            for sop in suggested:
                if not any(s['sop_id'] == sop.sop_id for s in matched_sops):
                    matched_sops.append(self._sop_to_suggestion(sop, "fuzzy_match", 0.5))
        
        # Strategy 4: Check historical success (learning loop)
        if pattern_id in self._success_map:
            for sop_id, count in sorted(
                self._success_map[pattern_id].items(),
                key=lambda x: x[1], reverse=True
            ):
                if not any(s['sop_id'] == sop_id for s in matched_sops):
                    # Use learned confidence score (accounts for both success & failure)
                    learned_conf = self.get_learned_confidence(pattern_id, sop_id)
                    if learned_conf > 0.3:  # Only suggest if net positive
                        sop = store.get_sop(sop_id)
                        if sop:
                            matched_sops.append(self._sop_to_suggestion(sop, "learned", learned_conf))
                else:
                    # Boost existing match confidence if historically successful
                    for s in matched_sops:
                        if s['sop_id'] == sop_id:
                            boost = min(0.1, count * 0.02)
                            s['match_confidence'] = min(0.98, s['match_confidence'] + boost)
                            break
        
        # Sort by match confidence
        matched_sops.sort(key=lambda x: x['match_confidence'], reverse=True)
        return matched_sops[:5]
    
    def _sop_to_suggestion(self, sop, match_type: str, confidence: float) -> Dict[str, Any]:
        """Convert SOP to suggestion dict."""
        est_minutes = sum(
            s.estimated_minutes if hasattr(s, 'estimated_minutes') else 5
            for s in sop.steps
        )
        return {
            "sop_id": sop.sop_id,
            "name": sop.name,
            "description": sop.description,
            "service": sop.service,
            "severity": sop.severity,
            "steps": len(sop.steps),
            "est_minutes": est_minutes,
            "match_type": match_type,
            "match_confidence": confidence,
            "auto_execute": AUTO_EXECUTE_POLICY.get(sop.severity, False),
        }
    
    def _extract_service(self, rca_result) -> Optional[str]:
        """Extract AWS service from RCA result."""
        text = f"{rca_result.root_cause} {rca_result.pattern_name}".lower()
        
        service_keywords = {
            "ec2": ["ec2", "instance", "cpu", "memory", "disk"],
            "rds": ["rds", "database", "db", "mysql", "postgres", "connection"],
            "lambda": ["lambda", "function", "invocation", "timeout", "cold start"],
            "s3": ["s3", "bucket", "storage", "object"],
            "ecs": ["ecs", "container", "task", "fargate"],
            "eks": ["eks", "kubernetes", "k8s", "pod", "node", "deployment"],
        }
        
        for service, keywords in service_keywords.items():
            if any(kw in text for kw in keywords):
                return service
        return None
    
    def _extract_keywords(self, rca_result) -> List[str]:
        """Extract keywords from RCA result for SOP matching."""
        text = f"{rca_result.root_cause} {' '.join(rca_result.matched_symptoms)}"
        
        important_words = [
            "high", "cpu", "memory", "disk", "oom", "crash", "error",
            "timeout", "failover", "reboot", "restart", "connection",
            "latency", "throttl", "leak", "full", "unavailable"
        ]
        
        return [w for w in important_words if w in text.lower()]
    
    def _auto_execute_sop(self, sop_id: str, rca_result):
        """Auto-execute a SOP based on RCA result."""
        try:
            from src.sop_system import get_sop_executor
            
            executor = get_sop_executor()
            execution = executor.start_execution(
                sop_id=sop_id,
                triggered_by="rca_auto",
                context={
                    "rca_pattern_id": rca_result.pattern_id,
                    "root_cause": rca_result.root_cause,
                    "confidence": rca_result.confidence,
                    "severity": rca_result.severity.value,
                }
            )
            
            if execution:
                logger.info(
                    f"Auto-executed SOP {sop_id} for RCA pattern "
                    f"{rca_result.pattern_id} (confidence={rca_result.confidence})"
                )
            return execution
        except Exception as e:
            logger.error(f"Auto-execute failed: {e}")
            return None
    
    def _calculate_bridge_confidence(
        self, pattern_id: str, suggested_sops: List[Dict]
    ) -> float:
        """Calculate overall bridge confidence."""
        if not suggested_sops:
            return 0.0
        
        # Best SOP match confidence
        best_match = suggested_sops[0]['match_confidence']
        
        # Boost if historically successful
        if pattern_id in self._success_map:
            total_successes = sum(self._success_map[pattern_id].values())
            history_boost = min(0.2, total_successes * 0.05)
            return min(1.0, best_match + history_boost)
        
        return best_match
    
    # =========================================================================
    # Feedback Loop: SOP → RCA Learning
    # =========================================================================
    
    def submit_feedback(
        self,
        execution_id: str,
        sop_id: str,
        rca_pattern_id: str,
        success: bool,
        root_cause_confirmed: bool = False,
        resolution_time_seconds: int = 0,
        steps_completed: int = 0,
        steps_total: int = 0,
        notes: str = "",
    ) -> SOPFeedback:
        """
        Submit feedback from SOP execution.
        
        This feeds back into the RCA system to improve future pattern matching
        and SOP suggestions.
        """
        feedback = SOPFeedback(
            execution_id=execution_id,
            sop_id=sop_id,
            rca_pattern_id=rca_pattern_id,
            success=success,
            resolution_time_seconds=resolution_time_seconds,
            steps_completed=steps_completed,
            steps_total=steps_total,
            root_cause_confirmed=root_cause_confirmed,
            notes=notes,
        )
        
        self._feedbacks.append(feedback)
        
        # Update success/failure maps for learning
        if success:
            if rca_pattern_id not in self._success_map:
                self._success_map[rca_pattern_id] = {}
            self._success_map[rca_pattern_id][sop_id] = (
                self._success_map[rca_pattern_id].get(sop_id, 0) + 1
            )
            logger.info(
                f"Positive feedback: pattern={rca_pattern_id} → sop={sop_id} "
                f"(total successes: {self._success_map[rca_pattern_id][sop_id]})"
            )
            # Strengthen the pattern confidence
            self._strengthen_pattern(rca_pattern_id)
        else:
            # Track failures — reduce confidence for this pattern→SOP pair
            if rca_pattern_id not in self._failure_map:
                self._failure_map[rca_pattern_id] = {}
            self._failure_map[rca_pattern_id][sop_id] = (
                self._failure_map[rca_pattern_id].get(sop_id, 0) + 1
            )
            logger.info(
                f"Negative feedback: pattern={rca_pattern_id} → sop={sop_id} "
                f"(total failures: {self._failure_map[rca_pattern_id][sop_id]})"
            )
            self._weaken_pattern(rca_pattern_id)
        
        # If root cause confirmed, extra strengthen
        if root_cause_confirmed:
            self._strengthen_pattern(rca_pattern_id)
        
        # Persist learning data
        self._save_learning_data()
        
        return feedback
    
    def _strengthen_pattern(self, pattern_id: str):
        """Strengthen an RCA pattern when confirmed by SOP execution."""
        try:
            from src.rca.engine import RCAEngine
            engine = RCAEngine()
            pattern = engine.matcher.get_pattern(pattern_id)
            if pattern:
                # Increase base confidence for confirmed patterns
                pattern.confidence = min(1.0, pattern.confidence + 0.05)
                logger.info(f"Strengthened pattern {pattern_id} → confidence={pattern.confidence}")
        except Exception as e:
            logger.warning(f"Failed to strengthen pattern: {e}")
    
    def _weaken_pattern(self, pattern_id: str):
        """Weaken an RCA pattern when SOP execution fails — avoids recommending bad fixes."""
        try:
            from src.rca.engine import RCAEngine
            engine = RCAEngine()
            pattern = engine.matcher.get_pattern(pattern_id)
            if pattern:
                # Decrease confidence, but never below 0.3
                pattern.confidence = max(0.3, pattern.confidence - 0.03)
                logger.info(f"Weakened pattern {pattern_id} → confidence={pattern.confidence}")
        except Exception as e:
            logger.warning(f"Failed to weaken pattern: {e}")
    
    def get_learned_confidence(self, pattern_id: str, sop_id: str) -> float:
        """Get the learned confidence for a pattern→SOP pair based on historical feedback."""
        successes = self._success_map.get(pattern_id, {}).get(sop_id, 0)
        failures = self._failure_map.get(pattern_id, {}).get(sop_id, 0)
        total = successes + failures
        if total == 0:
            return 0.0
        # Wilson score lower bound for ranking
        z = 1.96  # 95% CI
        phat = successes / total
        return (phat + z*z/(2*total) - z * ((phat*(1-phat) + z*z/(4*total))/total)**0.5) / (1 + z*z/total)
    
    # =========================================================================
    # Learning Data Persistence (JSON file-based)
    # =========================================================================
    
    LEARNING_FILE = "data/rca_sop_learning.json"
    
    def _save_learning_data(self):
        """Persist learning maps to disk."""
        import json
        from pathlib import Path
        try:
            data = {
                "success_map": self._success_map,
                "failure_map": self._failure_map,
                "total_feedbacks": len(self._feedbacks),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            path = Path(__file__).parent.parent / self.LEARNING_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved learning data: {len(self._success_map)} patterns")
        except Exception as e:
            logger.warning(f"Failed to save learning data: {e}")
    
    def _load_learning_data(self):
        """Load persisted learning maps from disk."""
        import json
        from pathlib import Path
        try:
            path = Path(__file__).parent.parent / self.LEARNING_FILE
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                self._success_map = data.get("success_map", {})
                self._failure_map = data.get("failure_map", {})
                logger.info(
                    f"Loaded learning data: {len(self._success_map)} success patterns, "
                    f"{len(self._failure_map)} failure patterns"
                )
        except Exception as e:
            logger.warning(f"Failed to load learning data: {e}")
    
    def get_feedback_stats(self) -> Dict[str, Any]:
        """Get feedback statistics."""
        total = len(self._feedbacks)
        successful = sum(1 for f in self._feedbacks if f.success)
        confirmed = sum(1 for f in self._feedbacks if f.root_cause_confirmed)
        
        avg_resolution = 0
        if successful:
            avg_resolution = sum(
                f.resolution_time_seconds for f in self._feedbacks if f.success
            ) / successful
        
        return {
            "total_feedbacks": total,
            "successful": successful,
            "failed": total - successful,
            "root_cause_confirmed": confirmed,
            "success_rate": successful / total if total else 0,
            "avg_resolution_seconds": avg_resolution,
            "learned_mappings": {
                pid: dict(sops) for pid, sops in self._success_map.items()
            },
            "failure_mappings": {
                pid: dict(sops) for pid, sops in self._failure_map.items()
            },
        }
    
    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent RCA→SOP bridge results."""
        items = list(self._execution_history.values())
        items.sort(key=lambda x: x.timestamp, reverse=True)
        return [item.to_dict() for item in items[:limit]]


# =============================================================================
# Singleton
# =============================================================================

_bridge: Optional[RCASOPBridge] = None


def get_bridge() -> RCASOPBridge:
    """Get or create the RCA-SOP bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = RCASOPBridge()
    return _bridge
