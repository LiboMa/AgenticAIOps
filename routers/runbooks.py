"""Router: /api/runbooks - Runbook management."""

from fastapi import APIRouter

from routers.deps import get_runbook_executor

router = APIRouter(tags=["runbooks"])


@router.get("/api/runbooks")
async def list_runbooks():
    """List available runbooks."""
    executor = get_runbook_executor()
    if not executor:
        return {"error": "Runbook Executor not available", "runbooks": []}

    return {"runbooks": executor.loader.list_runbooks()}


@router.get("/api/runbooks/executions")
async def list_runbook_executions(limit: int = 10):
    """List recent runbook executions."""
    executor = get_runbook_executor()
    if not executor:
        return {"error": "Runbook Executor not available", "executions": []}

    return {"executions": executor.list_executions(limit=limit)}
