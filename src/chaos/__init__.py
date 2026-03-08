"""Chaos Engineering Module — programmable, safe, observable K8s chaos experiments.

Wraps EKS chaos scenarios (resource stress, network block, pod kill, config break,
node drain) as Python-driven experiments with safety guards, dry-run mode,
namespace allowlists, and auto-rollback.

Usage:
    from src.chaos import ChaosEngine, ChaosType, ChaosStatus
    from src.chaos.models import ChaosExperiment, ChaosResult
    from src.chaos.api import router as chaos_router
"""

from .models import (
    ChaosExperiment,
    ChaosResult,
    ChaosStatus,
    ChaosType,
)
from .engine import ChaosEngine

__all__ = [
    "ChaosEngine",
    "ChaosExperiment",
    "ChaosResult",
    "ChaosStatus",
    "ChaosType",
]
