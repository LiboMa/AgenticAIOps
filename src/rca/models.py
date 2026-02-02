"""
RCA Data Models

Defines data structures for root cause analysis patterns and results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Any


class Severity(Enum):
    """Issue severity levels."""
    LOW = "low"           # Auto-fix, no notification
    MEDIUM = "medium"     # Auto-fix + notification  
    HIGH = "high"         # Manual confirmation required


@dataclass
class Symptom:
    """
    Symptom definition for pattern matching.
    
    Attributes:
        source: Data source (events, metrics, logs)
        field: Field to match (reason, name, pattern, message)
        value: Value to match
        condition: Optional condition expression
        required: Whether this symptom is required for match
    """
    source: str
    field: str
    value: str
    condition: Optional[str] = None
    required: bool = True


@dataclass
class Remediation:
    """
    Remediation action definition.
    
    Attributes:
        action: Action identifier (increase_memory_limit, rollout_restart, etc.)
        auto_execute: Whether to automatically execute
        params: Action parameters
        conditions: Conditions for auto-execution
        rollback: Rollback action definition
        suggestion: Human-readable suggestion
        checklist: Manual review checklist items
        fallback: Fallback action if primary fails
    """
    action: str
    auto_execute: bool = False
    params: Dict[str, Any] = field(default_factory=dict)
    conditions: List[str] = field(default_factory=list)
    rollback: Optional[Dict[str, Any]] = None
    suggestion: Optional[str] = None
    checklist: List[str] = field(default_factory=list)
    fallback: Optional[Dict[str, Any]] = None


@dataclass
class Pattern:
    """
    Root cause pattern definition.
    
    Attributes:
        id: Unique pattern identifier
        name: Human-readable name
        description: Detailed description
        symptoms: List of symptoms to match
        root_cause: Identified root cause text
        severity: Severity level
        confidence: Match confidence score
        remediation: Remediation definition
        references: Documentation references
    """
    id: str
    name: str
    description: str
    symptoms: List[Symptom]
    root_cause: str
    severity: Severity
    confidence: float
    remediation: Remediation
    references: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "root_cause": self.root_cause,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "auto_execute": self.remediation.auto_execute,
            "action": self.remediation.action,
            "references": self.references,
        }


@dataclass
class RCAResult:
    """
    Root cause analysis result.
    
    Attributes:
        pattern_id: Matched pattern ID
        pattern_name: Matched pattern name
        root_cause: Identified root cause
        severity: Severity level
        confidence: Confidence score
        matched_symptoms: List of matched symptoms
        remediation: Remediation action
        evidence: Evidence supporting diagnosis
        timestamp: Analysis timestamp
    """
    pattern_id: str
    pattern_name: str
    root_cause: str
    severity: Severity
    confidence: float
    matched_symptoms: List[str]
    remediation: Remediation
    evidence: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "pattern_id": self.pattern_id,
            "pattern_name": self.pattern_name,
            "root_cause": self.root_cause,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "matched_symptoms": self.matched_symptoms,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
            "remediation": {
                "action": self.remediation.action,
                "auto_execute": self.remediation.auto_execute,
                "params": self.remediation.params,
                "suggestion": self.remediation.suggestion,
                "checklist": self.remediation.checklist,
            }
        }
    
    def should_auto_fix(self) -> bool:
        """Check if this result allows auto-fix."""
        return (
            self.remediation.auto_execute and 
            self.severity in [Severity.LOW, Severity.MEDIUM] and
            self.confidence >= 0.7
        )
