"""
Runbook Data Models

Defines data structures for runbooks, steps, and executions.
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import List, Dict, Optional, Any


class ExecutionStatus(Enum):
    """Runbook execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class StepStatus(Enum):
    """Individual step status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class RunbookStep:
    """
    Individual runbook step definition.
    
    Attributes:
        id: Step identifier
        action: Action to execute
        description: Human-readable description
        params: Action parameters (supports templating)
        output: Variable name to store output
        requires_approval: Whether step needs manual approval
        timeout_seconds: Step timeout
        retry_count: Number of retries on failure
    """
    id: str
    action: str
    description: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    output: Optional[str] = None
    requires_approval: bool = False
    timeout_seconds: int = 300
    retry_count: int = 0


@dataclass
class StepResult:
    """
    Result of a single step execution.
    
    Attributes:
        step_id: Step identifier
        status: Step status
        output: Step output data
        error: Error message if failed
        duration_ms: Execution duration
        timestamp: Execution timestamp
    """
    step_id: str
    status: StepStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Runbook:
    """
    Runbook definition.
    
    Attributes:
        id: Unique runbook identifier
        name: Human-readable name
        description: Detailed description
        triggers: Trigger conditions (pattern_ids, severities)
        preconditions: Conditions to check before execution
        steps: List of execution steps
        rollback: Rollback steps if execution fails
        notifications: Notification settings
    """
    id: str
    name: str
    description: str = ""
    triggers: List[Dict[str, Any]] = field(default_factory=list)
    preconditions: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[RunbookStep] = field(default_factory=list)
    rollback: List[RunbookStep] = field(default_factory=list)
    notifications: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "step_count": len(self.steps),
            "has_rollback": len(self.rollback) > 0,
        }


@dataclass
class RunbookExecution:
    """
    Runbook execution record.
    
    Attributes:
        execution_id: Unique execution ID
        runbook_id: Runbook being executed
        issue_id: Associated issue ID
        status: Execution status
        context: Execution context (variables)
        step_results: Results of each step
        started_at: Start timestamp
        completed_at: Completion timestamp
        error: Error message if failed
    """
    execution_id: str
    runbook_id: str
    issue_id: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    context: Dict[str, Any] = field(default_factory=dict)
    step_results: List[StepResult] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "execution_id": self.execution_id,
            "runbook_id": self.runbook_id,
            "issue_id": self.issue_id,
            "status": self.status.value,
            "context": self.context,
            "step_results": [
                {
                    "step_id": r.step_id,
                    "status": r.status.value,
                    "output": r.output,
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                }
                for r in self.step_results
            ],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }
    
    @property
    def is_complete(self) -> bool:
        """Check if execution is complete."""
        return self.status in [
            ExecutionStatus.SUCCESS,
            ExecutionStatus.FAILED,
            ExecutionStatus.ROLLED_BACK,
            ExecutionStatus.CANCELLED,
        ]
    
    @property
    def duration_ms(self) -> float:
        """Calculate total duration."""
        return sum(r.duration_ms for r in self.step_results)
