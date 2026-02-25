"""Chaos API endpoints — FastAPI router for chaos experiment management.

Provides REST endpoints for creating, running, rolling back, listing,
and deleting chaos experiments.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException

from .engine import (
    ChaosEngine,
    ChaosEngineError,
    ExperimentNotFound,
    MaxConcurrentExceeded,
    NamespaceNotAllowed,
)
from .models import (
    ChaosExperiment,
    ChaosResult,
    CreateExperimentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chaos", tags=["chaos"])

# Module-level engine instance (shared across requests)
_engine = ChaosEngine(dry_run=False)


def get_engine() -> ChaosEngine:
    """Get the shared ChaosEngine instance."""
    return _engine


def set_engine(engine: ChaosEngine) -> None:
    """Replace the shared ChaosEngine instance (for testing)."""
    global _engine
    _engine = engine


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("/experiments", response_model=ChaosExperiment, status_code=201)
async def create_experiment(request: CreateExperimentRequest) -> ChaosExperiment:
    """Create a new chaos experiment."""
    try:
        experiment = get_engine().create_experiment(
            chaos_type=request.type,
            namespace=request.target_namespace,
            params=request.params,
            name=request.name,
            duration_seconds=request.duration_seconds,
        )
        return experiment
    except NamespaceNotAllowed as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChaosEngineError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/experiments/{experiment_id}/run", response_model=ChaosResult)
async def run_experiment(experiment_id: str) -> ChaosResult:
    """Run a pending chaos experiment."""
    try:
        result = get_engine().run_experiment(experiment_id)
        return result
    except ExperimentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except MaxConcurrentExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ChaosEngineError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/experiments/{experiment_id}/rollback")
async def rollback_experiment(experiment_id: str) -> dict:
    """Rollback a chaos experiment."""
    try:
        success = get_engine().rollback_experiment(experiment_id)
        return {"success": success, "experiment_id": experiment_id}
    except ExperimentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ChaosEngineError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/experiments", response_model=List[ChaosExperiment])
async def list_experiments() -> List[ChaosExperiment]:
    """List all chaos experiments."""
    return get_engine().list_experiments()


@router.get("/experiments/{experiment_id}", response_model=ChaosExperiment)
async def get_experiment(experiment_id: str) -> ChaosExperiment:
    """Get a specific chaos experiment by ID."""
    try:
        return get_engine().get_experiment(experiment_id)
    except ExperimentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/experiments/{experiment_id}")
async def delete_experiment(experiment_id: str) -> dict:
    """Delete a chaos experiment."""
    try:
        get_engine().delete_experiment(experiment_id)
        return {"deleted": True, "experiment_id": experiment_id}
    except ExperimentNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ChaosEngineError as e:
        raise HTTPException(status_code=400, detail=str(e))
