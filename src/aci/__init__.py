"""
Agent-Cloud Interface (ACI) for AgenticAIOps

Based on AIOpsLab Framework (arXiv:2501.06706)

Provides unified interface for AI Agents to interact with cloud resources:
- Telemetry API: logs, metrics, traces, events
- Operation API: shell, kubectl, aws cli
- Context API: topology, dependencies
"""

from .interface import AgentCloudInterface
from .models import (
    TelemetryResult,
    OperationResult,
    ContextResult,
    ResultStatus,
    LogEntry,
    MetricPoint,
    TraceSpan,
    EventEntry,
)

__all__ = [
    "AgentCloudInterface",
    "TelemetryResult",
    "OperationResult",
    "ContextResult",
    "ResultStatus",
    "LogEntry",
    "MetricPoint",
    "TraceSpan",
    "EventEntry",
]
