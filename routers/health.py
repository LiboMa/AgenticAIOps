"""Router: /api/health - Health check scheduler."""

from typing import Optional

from fastapi import APIRouter

from routers.deps import get_health_scheduler

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness():
    """Liveness probe — always returns 200."""
    return {"status": "ok"}


@router.get("/api/health/check")
async def run_health_check(namespace: Optional[str] = None):
    """Run health check now."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available"}

    try:
        result = scheduler.run_now()
        return result.to_dict()
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/health/status")
async def get_health_status():
    """Get health check scheduler status."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available"}

    return scheduler.get_status()


@router.get("/api/health/history")
async def get_health_history(limit: int = 10):
    """Get health check history."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available", "history": []}

    return {"history": scheduler.get_history(limit=limit)}
