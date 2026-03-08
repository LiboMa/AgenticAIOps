"""Chaos experiment data models — Pydantic models for chaos engineering.

Defines experiment lifecycle types, status enums, and result containers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChaosType(str, Enum):
    """Types of chaos experiments available."""
    RESOURCE_STRESS = "resource_stress"
    NETWORK_BLOCK = "network_block"
    POD_KILL = "pod_kill"
    CONFIG_BREAK = "config_break"
    NODE_DRAIN = "node_drain"


class ChaosStatus(str, Enum):
    """Lifecycle status of a chaos experiment."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ChaosExperiment(BaseModel):
    """A chaos experiment definition and its current state."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: ChaosType
    target_namespace: str = "chaos-lab"
    duration_seconds: int = 300
    status: ChaosStatus = ChaosStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    params: Dict[str, Any] = Field(default_factory=dict)


class ChaosResult(BaseModel):
    """Result of executing a chaos experiment."""
    experiment_id: str
    status: ChaosStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    observations: List[str] = Field(default_factory=list)
    rollback_performed: bool = False


class CreateExperimentRequest(BaseModel):
    """API request body for creating a chaos experiment."""
    name: str
    type: ChaosType
    target_namespace: str = "chaos-lab"
    duration_seconds: int = 300
    params: Dict[str, Any] = Field(default_factory=dict)
