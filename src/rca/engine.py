"""
RCA Engine - Root Cause Analysis Orchestrator

Integrates pattern matching with ACI telemetry and Multi-Agent voting
for comprehensive root cause analysis.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from .models import RCAResult, Severity, Remediation
from .pattern_matcher import PatternMatcher

logger = logging.getLogger(__name__)


class RCAEngine:
    """
    Root Cause Analysis Engine.
    
    Orchestrates the RCA process:
    1. Collect telemetry data via ACI
    2. Match against known patterns (fast path)
    3. Fall back to Multi-Agent voting for unknown issues
    4. Return structured diagnosis with remediation recommendations
    
    Example:
        engine = RCAEngine()
        
        # Analyze a namespace
        result = engine.analyze(namespace="stress-test")
        
        print(f"Root cause: {result.root_cause}")
        print(f"Should auto-fix: {result.should_auto_fix()}")
    """
    
    def __init__(
        self,
        aci=None,
        voting=None,
        pattern_config: Optional[str] = None,
    ):
        """
        Initialize the RCA engine.
        
        Args:
            aci: AgentCloudInterface instance (lazy-loaded if None)
            voting: MultiAgentVoting instance (lazy-loaded if None)
            pattern_config: Path to pattern YAML config
        """
        self._aci = aci
        self._voting = voting
        self.matcher = PatternMatcher(pattern_config)
    
    @property
    def aci(self):
        """Lazy-load ACI."""
        if self._aci is None:
            try:
                from src.aci import AgentCloudInterface
                self._aci = AgentCloudInterface()
            except ImportError:
                logger.warning("ACI not available")
        return self._aci
    
    @property
    def voting(self):
        """Lazy-load Voting."""
        if self._voting is None:
            try:
                from src.voting import MultiAgentVoting
                self._voting = MultiAgentVoting()
            except ImportError:
                logger.warning("Voting not available")
        return self._voting
    
    def analyze(
        self,
        namespace: str,
        pod: Optional[str] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> RCAResult:
        """
        Perform root cause analysis.
        
        Args:
            namespace: K8s namespace to analyze
            pod: Specific pod name (optional)
            telemetry: Pre-collected telemetry (skips ACI if provided)
            
        Returns:
            RCAResult with diagnosis and remediation
        """
        logger.info(f"Starting RCA for namespace={namespace}, pod={pod}")
        
        # Step 1: Collect or use provided telemetry
        if telemetry is None:
            telemetry = self._collect_telemetry(namespace, pod)
        
        # Step 2: Try pattern matching (fast path)
        result = self.matcher.match(telemetry)
        
        if result and result.confidence >= 0.85:
            logger.info(f"High-confidence pattern match: {result.pattern_id}")
            return result
        
        # Step 3: Try Multi-Agent voting for lower confidence or no match
        if (result is None or result.confidence < 0.85) and self.voting:
            voting_result = self._voting_analysis(telemetry, namespace)
            if voting_result and voting_result.confidence > (result.confidence if result else 0):
                logger.info("Using voting result over pattern match")
                return voting_result
        
        # Step 4: Return pattern result if available
        if result:
            logger.info(f"Returning pattern result: {result.pattern_id} (conf={result.confidence})")
            return result
        
        # Step 5: Return unknown result
        logger.warning(f"Unable to diagnose namespace={namespace}")
        return self._unknown_result(namespace)
    
    def analyze_event(self, event: Dict[str, Any]) -> RCAResult:
        """
        Analyze a single K8s event.
        
        Args:
            event: K8s event dict with reason, message, etc.
            
        Returns:
            RCAResult
        """
        telemetry = {
            "events": [event],
            "metrics": {},
            "logs": [],
        }
        
        namespace = event.get('namespace', event.get('involvedObject', {}).get('namespace', 'default'))
        return self.analyze(namespace=namespace, telemetry=telemetry)
    
    def analyze_from_symptoms(self, symptoms: List[str]) -> RCAResult:
        """
        Analyze from a list of symptom strings.
        
        Useful for testing or manual diagnosis.
        
        Args:
            symptoms: List of symptom strings (e.g., ["OOMKilled", "high memory"])
            
        Returns:
            RCAResult
        """
        # Convert symptoms to pseudo-events
        events = [{"reason": s, "message": s} for s in symptoms]
        telemetry = {
            "events": events,
            "metrics": {},
            "logs": symptoms,
        }
        
        return self.analyze(namespace="analysis", telemetry=telemetry)
    
    def _collect_telemetry(self, namespace: str, pod: Optional[str]) -> Dict[str, Any]:
        """Collect telemetry data via ACI."""
        telemetry = {
            "events": [],
            "metrics": {},
            "logs": [],
        }
        
        if not self.aci:
            logger.warning("ACI not available, returning empty telemetry")
            return telemetry
        
        try:
            # Get events
            events_result = self.aci.get_events(
                namespace=namespace,
                event_type="Warning",
                duration_minutes=30,
                limit=50,
            )
            if events_result.status.value == "success":
                telemetry["events"] = events_result.data or []
            
            # Get metrics
            metrics_result = self.aci.get_metrics(
                namespace=namespace,
                metric_names=["cpu_usage", "memory_usage"],
            )
            if metrics_result.status.value == "success":
                telemetry["metrics"] = metrics_result.data or {}
            
            # Get logs if pod specified
            if pod:
                logs_result = self.aci.get_logs(
                    namespace=namespace,
                    pod_name=pod,
                    severity="error",
                    duration_minutes=15,
                    limit=100,
                )
                if logs_result.status.value == "success":
                    telemetry["logs"] = [
                        log.get("message", str(log)) 
                        for log in (logs_result.data or [])
                    ]
            
        except Exception as e:
            logger.error(f"Failed to collect telemetry: {e}")
        
        return telemetry
    
    def _voting_analysis(
        self,
        telemetry: Dict[str, Any],
        namespace: str,
    ) -> Optional[RCAResult]:
        """Use Multi-Agent voting for analysis."""
        if not self.voting:
            return None
        
        try:
            from src.voting import TaskType
            
            # Build context for agents
            events_summary = telemetry.get("events", [])[:5]
            metrics_summary = telemetry.get("metrics", {})
            logs_summary = telemetry.get("logs", [])[:5]
            
            context = f"""
Namespace: {namespace}
Events: {events_summary}
Metrics: {metrics_summary}
Logs: {logs_summary}
"""
            
            # Create simulated agent responses
            # In real implementation, each agent would analyze independently
            agent_responses = {
                "architect": self._generate_analysis("architect", telemetry),
                "developer": self._generate_analysis("developer", telemetry),
                "tester": self._generate_analysis("tester", telemetry),
            }
            
            result = self.voting.vote(
                task_type=TaskType.ANALYSIS,
                query="Analyze the root cause of issues in this namespace",
                agent_responses=agent_responses,
            )
            
            if result.consensus:
                severity = self._infer_severity(result.final_answer)
                return RCAResult(
                    pattern_id="voting-analysis",
                    pattern_name="Multi-Agent Consensus",
                    root_cause=result.final_answer,
                    severity=severity,
                    confidence=result.agreement_ratio,
                    matched_symptoms=[],
                    remediation=Remediation(
                        action="manual_review",
                        auto_execute=False,
                        suggestion=result.final_answer,
                    ),
                    evidence=[f"Agent consensus: {result.agreement_ratio:.0%}"],
                )
                
        except Exception as e:
            logger.error(f"Voting analysis failed: {e}")
        
        return None
    
    def _generate_analysis(self, agent_role: str, telemetry: Dict[str, Any]) -> str:
        """Generate analysis for an agent role."""
        events = telemetry.get("events", [])
        
        # Simple heuristic analysis based on events
        for event in events:
            reason = event.get("reason", "")
            
            if "OOM" in reason:
                return "Memory exhaustion issue - OOMKilled detected"
            elif "CrashLoop" in reason or "BackOff" in reason:
                return "Application crash loop - startup failure"
            elif "ImagePull" in reason:
                return "Image pull failure - check image configuration"
            elif "Node" in reason:
                return "Node-level issue detected"
        
        return "Unable to determine specific root cause from available data"
    
    def _infer_severity(self, diagnosis: str) -> Severity:
        """Infer severity from diagnosis text."""
        diagnosis_lower = diagnosis.lower()
        
        high_keywords = ["node", "network", "pvc", "critical", "down", "unreachable"]
        low_keywords = ["throttl", "evict", "cleanup", "minor"]
        
        if any(kw in diagnosis_lower for kw in high_keywords):
            return Severity.HIGH
        elif any(kw in diagnosis_lower for kw in low_keywords):
            return Severity.LOW
        else:
            return Severity.MEDIUM
    
    def _unknown_result(self, namespace: str) -> RCAResult:
        """Return result for unknown issues."""
        return RCAResult(
            pattern_id="unknown",
            pattern_name="Unknown Issue",
            root_cause=f"Unable to automatically diagnose issues in namespace {namespace}. Manual investigation required.",
            severity=Severity.HIGH,
            confidence=0.0,
            matched_symptoms=[],
            remediation=Remediation(
                action="manual_review",
                auto_execute=False,
                suggestion="Manual investigation required",
                checklist=[
                    "Review recent deployments",
                    "Check resource quotas",
                    "Examine pod logs",
                    "Review network policies",
                ],
            ),
            evidence=[],
        )
    
    def get_patterns(self) -> List[Dict[str, Any]]:
        """Get all available patterns."""
        return self.matcher.list_patterns()
    
    def get_pattern(self, pattern_id: str):
        """Get a specific pattern."""
        return self.matcher.get_pattern(pattern_id)
