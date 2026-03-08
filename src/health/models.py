"""
Health Check Data Models

Defines data structures for health check results and configurations.
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import List, Dict, Optional, Any


class CheckType(Enum):
    """Types of health checks."""
    PODS = "pods"
    NODES = "nodes"
    SERVICES = "services"
    EVENTS = "events"
    RESOURCES = "resources"
    FULL = "full"


class CheckStatus(Enum):
    """Health check status."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class CheckItem:
    """
    Individual check item result.
    
    Attributes:
        name: Resource name (pod, node, service)
        namespace: K8s namespace
        status: Check status
        message: Status message
        details: Additional details
    """
    name: str
    namespace: str
    status: CheckStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    """
    Health check result for a check run.
    
    Attributes:
        check_type: Type of check performed
        status: Overall status
        items: Individual check items
        issues_created: Number of issues created
        issues_updated: Number of issues updated
        timestamp: Check timestamp
        duration_ms: Check duration in milliseconds
    """
    check_type: CheckType
    status: CheckStatus
    items: List[CheckItem] = field(default_factory=list)
    issues_created: int = 0
    issues_updated: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration_ms: float = 0.0
    
    @property
    def healthy_count(self) -> int:
        """Count of healthy items."""
        return sum(1 for i in self.items if i.status == CheckStatus.HEALTHY)
    
    @property
    def warning_count(self) -> int:
        """Count of warning items."""
        return sum(1 for i in self.items if i.status == CheckStatus.WARNING)
    
    @property
    def critical_count(self) -> int:
        """Count of critical items."""
        return sum(1 for i in self.items if i.status == CheckStatus.CRITICAL)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "check_type": self.check_type.value,
            "status": self.status.value,
            "summary": {
                "total": len(self.items),
                "healthy": self.healthy_count,
                "warning": self.warning_count,
                "critical": self.critical_count,
            },
            "issues_created": self.issues_created,
            "issues_updated": self.issues_updated,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "items": [
                {
                    "name": i.name,
                    "namespace": i.namespace,
                    "status": i.status.value,
                    "message": i.message,
                    "details": i.details,
                }
                for i in self.items
            ]
        }


@dataclass
class HealthCheckConfig:
    """
    Health check scheduler configuration.
    
    Attributes:
        enabled: Whether scheduling is enabled
        interval_seconds: Check interval in seconds
        namespaces: Namespaces to check (empty = all)
        check_types: Types of checks to perform
    """
    enabled: bool = True
    interval_seconds: int = 60
    namespaces: List[str] = field(default_factory=list)
    check_types: List[CheckType] = field(
        default_factory=lambda: [CheckType.PODS, CheckType.EVENTS]
    )
