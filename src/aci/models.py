"""
ACI Data Models

Defines result types and data structures for ACI operations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ResultStatus(Enum):
    """Operation result status"""
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"  # Partial success
    TIMEOUT = "timeout"


@dataclass
class TelemetryResult:
    """Telemetry data result"""
    status: ResultStatus
    data: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    query_time_ms: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "metadata": self.metadata,
            "query_time_ms": self.query_time_ms,
            "error": self.error,
        }


@dataclass
class OperationResult:
    """Operation execution result"""
    status: ResultStatus
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    duration_ms: int = 0
    command: str = ""  # For audit
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "duration_ms": self.duration_ms,
            "command": self.command,
            "error": self.error,
        }


@dataclass
class ContextResult:
    """Context information result"""
    status: ResultStatus
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
        }


# ============ Telemetry Data Types ============

@dataclass
class LogEntry:
    """Log entry"""
    timestamp: datetime
    namespace: str
    pod: str
    container: str
    message: str
    level: str = "info"  # info, warning, error
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "namespace": self.namespace,
            "pod": self.pod,
            "container": self.container,
            "message": self.message,
            "level": self.level,
        }


@dataclass
class MetricPoint:
    """Metric data point"""
    timestamp: datetime
    metric_name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "metric_name": self.metric_name,
            "value": self.value,
            "labels": self.labels,
        }


@dataclass
class TraceSpan:
    """Trace span"""
    trace_id: str
    span_id: str
    operation_name: str
    service_name: str
    duration_ms: int
    status: str
    tags: Dict[str, str] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "operation_name": self.operation_name,
            "service_name": self.service_name,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "tags": self.tags,
            "logs": self.logs,
        }


@dataclass
class EventEntry:
    """Kubernetes event entry"""
    timestamp: datetime
    namespace: str
    event_type: str  # Normal, Warning
    reason: str
    message: str
    involved_object: str
    involved_kind: str
    count: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "namespace": self.namespace,
            "event_type": self.event_type,
            "reason": self.reason,
            "message": self.message,
            "involved_object": self.involved_object,
            "involved_kind": self.involved_kind,
            "count": self.count,
        }
