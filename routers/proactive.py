"""Router: /api/proactive - Proactive agent system."""

from fastapi import APIRouter

from routers.schemas import ProactiveToggleRequest, ProactiveIntervalRequest, EventTriggerRequest
from src.proactive_agent import get_proactive_system, ProactiveResult

router = APIRouter(tags=["proactive"])

# Proactive system singleton (shared with startup/shutdown events in api_server)
proactive_system = get_proactive_system()


@router.get("/api/proactive/status")
async def get_proactive_status():
    """Get proactive system status."""
    return proactive_system.get_status()


@router.post("/api/proactive/toggle")
async def toggle_proactive_task(request: ProactiveToggleRequest):
    """Enable or disable a proactive task."""
    proactive_system.enable_task(request.task_name, request.enabled)
    return {"status": "ok", "task": request.task_name, "enabled": request.enabled}


@router.post("/api/proactive/interval")
async def update_proactive_interval(request: ProactiveIntervalRequest):
    """Update proactive task interval."""
    proactive_system.update_task_interval(request.task_name, request.interval_seconds)
    return {"status": "ok", "task": request.task_name, "interval": request.interval_seconds}


@router.post("/api/proactive/trigger")
async def trigger_proactive_event(request: EventTriggerRequest):
    """Trigger an event-driven proactive task."""
    result = await proactive_system.trigger_event(request.event_type, request.event_data)
    return {
        "task_name": result.task_name,
        "status": result.status,
        "summary": result.summary,
        "findings": result.findings,
        "timestamp": result.timestamp.isoformat()
    }


@router.get("/api/proactive/results")
async def get_proactive_results():
    """Get pending proactive results (alerts)."""
    results = []
    while not proactive_system.results_queue.empty():
        try:
            result: ProactiveResult = proactive_system.results_queue.get_nowait()
            results.append({
                "task_name": result.task_name,
                "status": result.status,
                "summary": result.summary,
                "findings": result.findings,
                "timestamp": result.timestamp.isoformat()
            })
        except Exception:
            break
    return {"results": results, "count": len(results)}
