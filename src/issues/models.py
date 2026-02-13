"""
Issue Data Models

Defines the core data structures for issue tracking.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
import uuid


class IssueSeverity(Enum):
    """Issue severity levels for auto-remediation decision."""
    LOW = "low"           # Auto-fix, no notification
    MEDIUM = "medium"     # Auto-fix + notification
    HIGH = "high"         # Manual confirmation required
    CRITICAL = "critical" # Immediate attention required


class IssueStatus(Enum):
    """Issue lifecycle status."""
    DETECTED = "detected"           # Just detected
    ANALYZING = "analyzing"         # RCA in progress
    PENDING_FIX = "pending_fix"     # Waiting for fix (high severity)
    FIXING = "fixing"               # Auto-fix in progress
    FIXED = "fixed"                 # Successfully fixed
    FAILED = "failed"               # Fix attempt failed
    ACKNOWLEDGED = "acknowledged"   # Human acknowledged (high)
    CLOSED = "closed"               # Issue resolved


class IssueType(Enum):
    """Types of issues detected."""
    OOM_KILLED = "oom_killed"
    CRASH_LOOP = "crash_loop"
    IMAGE_PULL_ERROR = "image_pull_error"
    CPU_THROTTLING = "cpu_throttling"
    MEMORY_PRESSURE = "memory_pressure"
    NODE_NOT_READY = "node_not_ready"
    NETWORK_ERROR = "network_error"
    SERVICE_UNREACHABLE = "service_unreachable"
    HIGH_LATENCY = "high_latency"
    ERROR_RATE_HIGH = "error_rate_high"
    DISK_PRESSURE = "disk_pressure"
    UNKNOWN = "unknown"


@dataclass
class Issue:
    """
    Represents a detected issue in the system.
    
    Attributes:
        id: Unique issue identifier
        type: Type of issue (OOM, CrashLoop, etc.)
        severity: Severity level (low/medium/high)
        status: Current status in lifecycle
        title: Human-readable title
        description: Detailed description
        namespace: K8s namespace
        resource: Affected resource (pod/deployment name)
        root_cause: Diagnosed root cause
        symptoms: List of observed symptoms
        suggested_fix: Recommended remediation action
        auto_fixable: Whether issue can be auto-fixed
        fix_actions: List of executed fix actions
        created_at: Detection timestamp
        updated_at: Last update timestamp
        resolved_at: Resolution timestamp
        metadata: Additional context data
    """
    
    type: IssueType
    severity: IssueSeverity
    title: str
    namespace: str
    resource: str
    
    # Optional fields with defaults
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: IssueStatus = IssueStatus.DETECTED
    description: str = ""
    root_cause: str = ""
    symptoms: List[str] = field(default_factory=list)
    suggested_fix: str = ""
    auto_fixable: bool = True
    fix_actions: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "type": self.type.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "title": self.title,
            "description": self.description,
            "namespace": self.namespace,
            "resource": self.resource,
            "root_cause": self.root_cause,
            "symptoms": self.symptoms,
            "suggested_fix": self.suggested_fix,
            "auto_fixable": self.auto_fixable,
            "fix_actions": self.fix_actions,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Issue":
        """Create Issue from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            type=IssueType(data.get("type", "unknown")),
            severity=IssueSeverity(data.get("severity", "medium")),
            status=IssueStatus(data.get("status", "detected")),
            title=data.get("title", ""),
            description=data.get("description", ""),
            namespace=data.get("namespace", ""),
            resource=data.get("resource", ""),
            root_cause=data.get("root_cause", ""),
            symptoms=data.get("symptoms", []),
            suggested_fix=data.get("suggested_fix", ""),
            auto_fixable=data.get("auto_fixable", True),
            fix_actions=data.get("fix_actions", []),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(timezone.utc),
            resolved_at=datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else None,
            metadata=data.get("metadata", {}),
        )
    
    def is_resolved(self) -> bool:
        """Check if issue is resolved."""
        return self.status in [IssueStatus.FIXED, IssueStatus.CLOSED]
    
    def requires_approval(self) -> bool:
        """Check if issue requires human approval for fix."""
        return self.severity in [IssueSeverity.HIGH, IssueSeverity.CRITICAL]
    
    def update_status(self, new_status: IssueStatus) -> None:
        """Update issue status with timestamp."""
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)
        
        if new_status in [IssueStatus.FIXED, IssueStatus.CLOSED]:
            self.resolved_at = datetime.now(timezone.utc)
    
    def add_fix_action(self, action: str, result: str, success: bool) -> None:
        """Record a fix action attempt."""
        self.fix_actions.append({
            "action": action,
            "result": result,
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.updated_at = datetime.now(timezone.utc)
