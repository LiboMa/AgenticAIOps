"""
RCA Inference Engine - Bedrock Claude-powered Root Cause Analysis

Step 2 of the RCA ↔ SOP Enhancement.
Uses Bedrock Claude to analyze correlated event data and produce
structured root cause diagnoses.

Architecture:
- Input: CorrelatedEvent from Step 1 (event_correlator.py)
- Processing: Pattern match (fast) → Claude inference (deep)
- Output: Structured RCAResult with evidence chain
- Model strategy: Sonnet first, upgrade to Opus if confidence < 0.7

Design Decisions:
- Pattern matching first (fast path, <1s)
- Claude inference only when patterns insufficient
- Sonnet → Opus auto-upgrade for complex cases
- Structured JSON output from Claude (not free-form text)
- Evidence chain for auditability
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List

from src.rca.models import RCAResult, Severity, Remediation
from src.rca.pattern_matcher import PatternMatcher

logger = logging.getLogger(__name__)

# Bedrock model IDs for RCA
RCA_MODEL_PRIMARY = "anthropic.claude-sonnet-4-20250514-v1:0"   # Sonnet 4: Fast, balanced
RCA_MODEL_DEEP = "anthropic.claude-opus-4-6-v1"                 # Opus 4.6: Deep reasoning
CONFIDENCE_UPGRADE_THRESHOLD = 0.7  # Below this → upgrade to Opus


# =============================================================================
# Claude RCA Prompt
# =============================================================================

RCA_SYSTEM_PROMPT = """You are an expert AWS Cloud Operations Root Cause Analyst.

Given monitoring data (metrics, alarms, CloudTrail events, health events), 
you must identify the root cause and recommend remediation.

ALWAYS respond with valid JSON in this exact format:
{
  "root_cause": "Clear description of the root cause",
  "severity": "low|medium|high",
  "confidence": 0.0-1.0,
  "category": "resource|config|security|network|application|cost",
  "affected_service": "ec2|rds|lambda|s3|vpc|eks|...",
  "affected_resources": ["resource-id-1", "resource-id-2"],
  "evidence": ["evidence point 1", "evidence point 2"],
  "remediation": {
    "action": "action_identifier",
    "description": "What to do",
    "auto_executable": true|false,
    "risk_level": "L0|L1|L2|L3",
    "steps": ["step 1", "step 2"]
  },
  "related_patterns": ["pattern description if any"]
}

Guidelines:
- Be specific about resource IDs and metrics
- Confidence should reflect how certain you are
- L0=read-only, L1=low-risk auto, L2=confirm first, L3=manual approval
- If data is insufficient, say so and set confidence low
- Correlate across data sources (metric spike + recent change = likely cause)
"""


def _build_analysis_prompt(correlated_event) -> str:
    """Build the analysis prompt from correlated event data."""
    sections = []
    
    # Alarms
    firing = [a for a in correlated_event.alarms if a.state == "ALARM"]
    if firing:
        sections.append("## Active Alarms")
        for a in firing:
            sections.append(f"- {a.name}: {a.metric_name} {a.comparison} {a.threshold} (resource: {a.resource_id})")
    
    # Anomalies
    if correlated_event.anomalies:
        sections.append("\n## Detected Anomalies")
        for an in correlated_event.anomalies:
            sections.append(f"- {an['resource']}: {an['metric']}={an['value']} (threshold: {an['threshold']}, severity: {an['severity']})")
    
    # Key Metrics
    if correlated_event.metrics:
        sections.append("\n## Key Metrics (latest values)")
        # Group by resource
        by_resource = {}
        for m in correlated_event.metrics:
            by_resource.setdefault(m.resource_id, []).append(m)
        for resource, metrics in list(by_resource.items())[:10]:
            sections.append(f"\n### {resource}")
            for m in metrics:
                sections.append(f"- {m.metric_name}: {m.value} {m.unit}")
    
    # Recent Changes (CloudTrail)
    if correlated_event.recent_changes:
        sections.append("\n## Recent Changes (CloudTrail)")
        for c in correlated_event.recent_changes[:10]:
            error_str = f" [ERROR: {c['error']}]" if c.get('error') else ""
            sections.append(f"- {c['event']} by {c['user']} on {c.get('resource', 'N/A')}{error_str} ({c['timestamp']})")
    
    # Health Events
    if correlated_event.health_events:
        sections.append("\n## AWS Health Events")
        for h in correlated_event.health_events:
            sections.append(f"- {h.service}: {h.event_type} ({h.status})")
    
    # Source status
    sections.append(f"\n## Collection Info")
    sections.append(f"- Region: {correlated_event.region}")
    sections.append(f"- Collection time: {correlated_event.duration_ms}ms")
    for src, status in correlated_event.source_status.items():
        sections.append(f"- {src}: {status}")
    
    if not firing and not correlated_event.anomalies and not correlated_event.recent_changes:
        sections.append("\n## Note: No active issues detected. All systems appear healthy.")
    
    return "\n".join(sections)


class RCAInferenceEngine:
    """
    Enhanced RCA Engine with Bedrock Claude inference.
    
    Flow:
    1. Pattern match (fast path, <1s)
    2. If no high-confidence match → Claude Sonnet analysis
    3. If Sonnet confidence < 0.7 → upgrade to Claude Opus
    4. Return structured RCAResult
    """
    
    def __init__(self):
        self.pattern_matcher = PatternMatcher()
        self._bedrock_client = None
    
    @property
    def bedrock(self):
        """Lazy-init Bedrock client."""
        if self._bedrock_client is None:
            import boto3
            from src.config import AWS_REGION
            self._bedrock_client = boto3.client(
                'bedrock-runtime',
                region_name=AWS_REGION  # ap-southeast-1 (models available)
            )
        return self._bedrock_client
    
    async def analyze(
        self,
        correlated_event,
        force_llm: bool = False,
    ) -> RCAResult:
        """
        Analyze correlated event data for root cause.
        
        Args:
            correlated_event: CorrelatedEvent from event_correlator
            force_llm: Skip pattern matching, go straight to Claude
            
        Returns:
            RCAResult with diagnosis and remediation
        """
        import asyncio
        
        # Step 1: Try pattern matching (fast path)
        if not force_llm:
            telemetry = correlated_event.to_rca_telemetry()
            pattern_result = self.pattern_matcher.match(telemetry)
            
            if pattern_result and pattern_result.confidence >= 0.85:
                logger.info(f"High-confidence pattern match: {pattern_result.pattern_id}")
                return pattern_result
        
        # Step 2: Claude Sonnet analysis
        prompt = _build_analysis_prompt(correlated_event)
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._invoke_claude, prompt, RCA_MODEL_PRIMARY
        )
        
        if result and result.confidence >= CONFIDENCE_UPGRADE_THRESHOLD:
            return result
        
        # Step 3: Low confidence → upgrade to Opus
        if result and result.confidence < CONFIDENCE_UPGRADE_THRESHOLD:
            logger.info(
                f"Sonnet confidence {result.confidence:.0%} < {CONFIDENCE_UPGRADE_THRESHOLD:.0%}, "
                f"upgrading to Opus"
            )
            opus_result = await loop.run_in_executor(
                None, self._invoke_claude, prompt, RCA_MODEL_DEEP
            )
            if opus_result and opus_result.confidence > result.confidence:
                return opus_result
        
        # Return whatever we have
        return result or self._no_issue_result(correlated_event)
    
    def _invoke_claude(self, prompt: str, model_id: str) -> Optional[RCAResult]:
        """Invoke Bedrock Claude for RCA analysis."""
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "system": RCA_SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": f"Analyze this AWS monitoring data and identify the root cause:\n\n{prompt}"}
                ],
                "temperature": 0.1,  # Low temperature for consistent analysis
            })
            
            response = self.bedrock.invoke_model(
                modelId=model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            
            response_body = json.loads(response['body'].read())
            content = response_body.get('content', [{}])[0].get('text', '')
            
            # Parse JSON from response
            return self._parse_claude_response(content, model_id)
            
        except Exception as e:
            logger.error(f"Claude invocation failed ({model_id}): {e}")
            return None
    
    def _parse_claude_response(self, text: str, model_id: str) -> Optional[RCAResult]:
        """Parse Claude's JSON response into RCAResult."""
        try:
            # Extract JSON from response (may have markdown wrapping)
            json_match = re.search(r'\{[\s\S]*\}', text)
            if not json_match:
                logger.warning("No JSON found in Claude response")
                return None
            
            data = json.loads(json_match.group())
            
            # Map severity
            severity_map = {
                "low": Severity.LOW,
                "medium": Severity.MEDIUM,
                "high": Severity.HIGH,
            }
            severity = severity_map.get(data.get("severity", "medium"), Severity.MEDIUM)
            
            # Build remediation
            rem_data = data.get("remediation", {})
            remediation = Remediation(
                action=rem_data.get("action", "manual_review"),
                auto_execute=rem_data.get("auto_executable", False),
                suggestion=rem_data.get("description", ""),
                checklist=rem_data.get("steps", []),
            )
            
            # Determine pattern_id
            model_short = "opus" if "opus" in model_id else "sonnet"
            category = data.get("category", "unknown")
            
            return RCAResult(
                pattern_id=f"llm-{model_short}-{category}",
                pattern_name=f"Claude {model_short.title()} Analysis",
                root_cause=data.get("root_cause", "Unable to determine"),
                severity=severity,
                confidence=min(1.0, max(0.0, data.get("confidence", 0.5))),
                matched_symptoms=data.get("affected_resources", []),
                remediation=remediation,
                evidence=data.get("evidence", []),
            )
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse Claude response: {e}")
            logger.debug(f"Raw response: {text[:500]}")
            return None
    
    def _no_issue_result(self, correlated_event) -> RCAResult:
        """Return result when no issues detected."""
        return RCAResult(
            pattern_id="healthy",
            pattern_name="System Healthy",
            root_cause="No active issues detected. All monitored services are operating within normal parameters.",
            severity=Severity.LOW,
            confidence=0.9,
            matched_symptoms=[],
            remediation=Remediation(
                action="none",
                auto_execute=False,
                suggestion="No action needed. Continue monitoring.",
            ),
            evidence=[
                f"Region: {correlated_event.region}",
                f"Alarms firing: {len([a for a in correlated_event.alarms if a.state == 'ALARM'])}",
                f"Anomalies: {len(correlated_event.anomalies)}",
                f"Data sources: {len(correlated_event.source_status)} checked",
            ],
        )


# =============================================================================
# Convenience
# =============================================================================

_engine: Optional[RCAInferenceEngine] = None


def get_rca_inference_engine() -> RCAInferenceEngine:
    """Get or create the RCA inference engine singleton."""
    global _engine
    if _engine is None:
        _engine = RCAInferenceEngine()
    return _engine
