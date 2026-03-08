"""
Pattern Matcher - Rule-based Root Cause Identification

Matches telemetry data against predefined patterns to identify
root causes quickly and reliably.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

import yaml

from .models import Pattern, RCAResult, Severity, Remediation, Symptom

logger = logging.getLogger(__name__)

# Default config path
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "rca_patterns.yaml"


class PatternMatcher:
    """
    Rule-based pattern matching engine.
    
    Matches telemetry data (events, metrics, logs) against predefined
    patterns to identify root causes.
    
    Example:
        matcher = PatternMatcher()
        
        telemetry = {
            "events": [{"reason": "OOMKilled", "type": "Warning"}],
            "metrics": {"memory_usage": 95},
            "logs": ["OutOfMemoryError"]
        }
        
        result = matcher.match(telemetry)
        if result:
            print(f"Root cause: {result.root_cause}")
            print(f"Severity: {result.severity}")
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the pattern matcher.
        
        Args:
            config_path: Path to YAML config file (uses default if None)
        """
        path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.config_path = path
        self.patterns: List[Pattern] = []
        
        if path.exists():
            self._load_patterns()
        else:
            logger.warning(f"Pattern config not found: {path}")
    
    def _load_patterns(self) -> None:
        """Load patterns from YAML config."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            self.patterns = []
            for p_data in config.get('patterns', []):
                pattern = self._parse_pattern(p_data)
                if pattern:
                    self.patterns.append(pattern)
            
            logger.info(f"Loaded {len(self.patterns)} patterns from {self.config_path}")
            
        except Exception as e:
            logger.error(f"Failed to load patterns: {e}")
    
    def _parse_pattern(self, data: Dict) -> Optional[Pattern]:
        """Parse a single pattern from config data."""
        try:
            # Parse symptoms
            symptoms = []
            symptoms_data = data.get('symptoms', {})
            
            # Parse events symptoms
            for item in symptoms_data.get('events', []):
                if isinstance(item, dict):
                    # Handle {reason: "OOMKilled"} format
                    if 'reason' in item:
                        symptoms.append(Symptom(
                            source='events',
                            field='reason',
                            value=str(item['reason']),
                            condition=item.get('condition'),
                            required=item.get('required', True)
                        ))
                    if 'message' in item:
                        symptoms.append(Symptom(
                            source='events',
                            field='message',
                            value=str(item['message']),
                            condition=item.get('condition'),
                            required=item.get('required', True)
                        ))
                    if 'type' in item:
                        symptoms.append(Symptom(
                            source='events',
                            field='type',
                            value=str(item['type']),
                            condition=item.get('condition'),
                            required=item.get('required', True)
                        ))
            
            # Parse metrics symptoms
            for item in symptoms_data.get('metrics', []):
                if isinstance(item, dict):
                    symptoms.append(Symptom(
                        source='metrics',
                        field=item.get('name', ''),
                        value=item.get('name', ''),
                        condition=item.get('condition'),
                        required=item.get('required', True)
                    ))
            
            # Parse logs symptoms
            for item in symptoms_data.get('logs', []):
                if isinstance(item, dict):
                    symptoms.append(Symptom(
                        source='logs',
                        field='pattern',
                        value=item.get('pattern', ''),
                        required=item.get('required', True)
                    ))
                elif isinstance(item, str):
                    symptoms.append(Symptom(
                        source='logs',
                        field='pattern',
                        value=item,
                        required=True
                    ))
            
            # Parse remediation
            rem_data = data.get('remediation', {})
            remediation = Remediation(
                action=rem_data.get('action', 'manual_review'),
                auto_execute=rem_data.get('auto_execute', False),
                params=rem_data.get('params', {}),
                conditions=rem_data.get('conditions', []),
                rollback=rem_data.get('rollback'),
                suggestion=rem_data.get('suggestion'),
                checklist=rem_data.get('checklist', []),
                fallback=rem_data.get('fallback'),
            )
            
            return Pattern(
                id=data['id'],
                name=data['name'],
                description=data.get('description', ''),
                symptoms=symptoms,
                root_cause=data['root_cause'],
                severity=Severity(data.get('severity', 'medium')),
                confidence=data.get('confidence', 0.8),
                remediation=remediation,
                references=data.get('references', []),
            )
            
        except Exception as e:
            logger.error(f"Failed to parse pattern {data.get('id', 'unknown')}: {e}")
            return None
    
    def match(self, telemetry: Dict[str, Any]) -> Optional[RCAResult]:
        """
        Match telemetry data against patterns.
        
        Args:
            telemetry: Dict with 'events', 'metrics', 'logs' keys
            
        Returns:
            RCAResult if matched, None otherwise
        """
        events = telemetry.get('events', [])
        metrics = telemetry.get('metrics', {})
        logs = telemetry.get('logs', [])
        
        best_match: Optional[RCAResult] = None
        best_confidence = 0.0
        
        for pattern in self.patterns:
            matched, evidence = self._match_pattern(pattern, events, metrics, logs)
            
            if matched and pattern.confidence > best_confidence:
                best_match = RCAResult(
                    pattern_id=pattern.id,
                    pattern_name=pattern.name,
                    root_cause=pattern.root_cause,
                    severity=pattern.severity,
                    confidence=pattern.confidence,
                    matched_symptoms=[s.value for s in pattern.symptoms if s.required],
                    remediation=pattern.remediation,
                    evidence=evidence,
                )
                best_confidence = pattern.confidence
        
        if best_match:
            logger.info(f"Pattern matched: {best_match.pattern_id} (confidence={best_confidence})")
        
        return best_match
    
    def _match_pattern(
        self,
        pattern: Pattern,
        events: List[Dict],
        metrics: Dict[str, Any],
        logs: List[str],
    ) -> Tuple[bool, List[str]]:
        """
        Match a single pattern against telemetry.
        
        Logic: At least one symptom from each source type must match.
        Multiple symptoms from the same source are OR'd together.
        
        Returns:
            Tuple of (matched: bool, evidence: List[str])
        """
        evidence = []
        
        # Group symptoms by source
        event_symptoms = [s for s in pattern.symptoms if s.source == 'events']
        metric_symptoms = [s for s in pattern.symptoms if s.source == 'metrics']
        log_symptoms = [s for s in pattern.symptoms if s.source == 'logs']
        
        # For events: at least one event symptom must match (OR logic)
        event_matched = False
        if event_symptoms:
            for symptom in event_symptoms:
                for event in events:
                    if self._match_event(symptom, event):
                        event_matched = True
                        evidence.append(f"Event matched: {symptom.field}={symptom.value}")
                        break
                if event_matched:
                    break
            
            # If we have event symptoms but none matched, pattern fails
            if not event_matched:
                return False, []
        
        # For metrics: at least one must match (if any defined)
        metric_matched = False
        if metric_symptoms:
            for symptom in metric_symptoms:
                if self._match_metric(symptom, metrics):
                    metric_matched = True
                    evidence.append(f"Metric matched: {symptom.field}")
                    break
        else:
            metric_matched = True  # No metric symptoms = auto pass
        
        # For logs: at least one must match (if any defined)
        log_matched = False
        if log_symptoms:
            for symptom in log_symptoms:
                for log_entry in logs:
                    log_text = log_entry if isinstance(log_entry, str) else str(log_entry.get('message', ''))
                    if self._match_log(symptom, log_text):
                        log_matched = True
                        evidence.append(f"Log matched pattern: {symptom.value[:50]}")
                        break
                if log_matched:
                    break
        else:
            log_matched = True  # No log symptoms = auto pass
        
        # Pattern matches if all required source types matched
        # Events are required if defined, metrics and logs are optional
        # But if ONLY logs are defined, we need at least logs to match
        if event_symptoms:
            matched = event_matched
        elif log_symptoms:
            matched = log_matched
        elif metric_symptoms:
            matched = metric_matched
        else:
            matched = False
        
        return matched and len(evidence) > 0, evidence
    
    def _match_event(self, symptom: Symptom, event: Dict) -> bool:
        """Match symptom against a K8s event."""
        if symptom.field == 'reason':
            return event.get('reason', '').lower() == symptom.value.lower()
        elif symptom.field == 'type':
            return event.get('type', '').lower() == symptom.value.lower()
        elif symptom.field == 'message':
            return symptom.value.lower() in event.get('message', '').lower()
        elif symptom.field == 'value':
            # Generic match against reason or message
            event_text = f"{event.get('reason', '')} {event.get('message', '')}".lower()
            return symptom.value.lower() in event_text
        return False
    
    def _match_metric(self, symptom: Symptom, metrics: Dict[str, Any]) -> bool:
        """Match symptom against metrics."""
        # Check if metric exists
        metric_name = symptom.field if symptom.field != 'value' else symptom.value.split()[0]
        value = metrics.get(metric_name)
        
        if value is None:
            return False
        
        # If there's a condition, try to evaluate it
        if symptom.condition:
            try:
                # Simple condition parsing (> X, < X, == X)
                if '>' in symptom.condition:
                    threshold = float(symptom.condition.replace('>', '').strip().rstrip('%'))
                    return float(value) > threshold
                elif '<' in symptom.condition:
                    threshold = float(symptom.condition.replace('<', '').strip().rstrip('%'))
                    return float(value) < threshold
                elif '==' in symptom.condition:
                    return str(value) == symptom.condition.replace('==', '').strip()
            except (ValueError, TypeError):
                pass
        
        # Default: metric exists
        return True
    
    def _match_log(self, symptom: Symptom, log_text: str) -> bool:
        """Match symptom against log text using regex."""
        try:
            pattern = symptom.value
            return bool(re.search(pattern, log_text, re.IGNORECASE))
        except re.error:
            # Fall back to simple substring match
            return symptom.value.lower() in log_text.lower()
    
    def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        """Get a pattern by ID."""
        for p in self.patterns:
            if p.id == pattern_id:
                return p
        return None
    
    def list_patterns(self) -> List[Dict[str, Any]]:
        """List all patterns with summary info."""
        return [p.to_dict() for p in self.patterns]
    
    def reload(self) -> None:
        """Reload patterns from config file."""
        self._load_patterns()
