"""Router: Incident pipeline, event collection, safety, SOP execution."""

import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from routers.deps import get_current_region, logger

router = APIRouter(tags=["incident"])


# =============================================================================
# Event Correlator API
# =============================================================================

@router.get("/api/events/collect")
async def collect_events(
    services: str = None,
    lookback_minutes: int = 60,
):
    """Collect and correlate events from multiple AWS sources."""
    try:
        from src.event_correlator import get_correlator

        correlator = get_correlator(get_current_region())
        service_list = services.split(',') if services else None

        event = await correlator.collect(
            services=service_list,
            lookback_minutes=lookback_minutes,
        )

        return {
            "success": True,
            "summary": event.summary(),
            "data": event.to_dict(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


@router.get("/api/events/collect/rca")
async def collect_events_for_rca(
    services: str = None,
    lookback_minutes: int = 60,
):
    """Collect events and format for RCA Engine consumption."""
    try:
        from src.event_correlator import get_correlator

        correlator = get_correlator(get_current_region())
        service_list = services.split(',') if services else None

        event = await correlator.collect(
            services=service_list,
            lookback_minutes=lookback_minutes,
        )

        return {
            "success": True,
            "telemetry": event.to_rca_telemetry(),
            "collection_id": event.collection_id,
            "duration_ms": event.duration_ms,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/rca/deep")
async def rca_deep_analyze(
    services: str = None,
    lookback_minutes: int = 60,
    force_llm: bool = False,
):
    """Full RCA pipeline: Collect → Infer with Claude → SOP suggestions."""
    try:
        from src.event_correlator import get_correlator
        from src.rca_inference import get_rca_inference_engine
        from src.rca_sop_bridge import get_bridge

        correlator = get_correlator(get_current_region())
        service_list = services.split(',') if services else None
        event = await correlator.collect(
            services=service_list,
            lookback_minutes=lookback_minutes,
        )

        engine = get_rca_inference_engine()
        rca_result = await engine.analyze(event, force_llm=force_llm)

        bridge = get_bridge()
        sop_suggestions = bridge.match_sops(rca_result)

        return {
            "success": True,
            "collection": {
                "id": event.collection_id,
                "duration_ms": event.duration_ms,
                "metrics": len(event.metrics),
                "alarms": len(event.alarms),
                "trail_events": len(event.trail_events),
                "anomalies": len(event.anomalies),
            },
            "rca": rca_result.to_dict(),
            "sop_suggestions": sop_suggestions,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# =============================================================================
# Safety
# =============================================================================

@router.get("/api/safety/check/{sop_id}")
async def safety_check(sop_id: str, dry_run: bool = True):
    """Safety check / dry-run for a SOP."""
    try:
        from src.sop_safety import get_safety_layer
        safety = get_safety_layer()
        check = safety.check(sop_id=sop_id, dry_run=dry_run)
        return {"success": True, **check.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/safety/stats")
async def safety_stats():
    """Get safety layer statistics."""
    try:
        from src.sop_safety import get_safety_layer
        safety = get_safety_layer()
        return {"success": True, **safety.get_stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/safety/approvals")
async def safety_approvals():
    """Get pending approvals."""
    try:
        from src.sop_safety import get_safety_layer
        safety = get_safety_layer()
        return {"success": True, "approvals": safety.get_pending_approvals()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Incident Pipeline
# =============================================================================

@router.post("/api/incident/run")
async def incident_run(
    trigger_type: str = "manual",
    services: str = None,
    auto_execute: bool = False,
    dry_run: bool = False,
    force_refresh: bool = False,
):
    """Full closed-loop incident pipeline via DetectAgent."""
    try:
        from src.detect_agent import get_detect_agent
        detect = get_detect_agent(get_current_region())
        service_list = services.split(',') if services else None

        incident = await detect.trigger_incident(
            trigger_type=trigger_type,
            services=service_list,
            auto_execute=auto_execute,
            dry_run=dry_run,
        )
        return {"success": True, **incident.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@router.get("/api/detect/status")
async def detect_status():
    """DetectAgent status: cache state, data freshness."""
    from src.detect_agent import get_detect_agent
    detect = get_detect_agent(get_current_region())
    return {"success": True, **detect.status()}


@router.get("/api/incident/list")
async def incident_list(limit: int = 20, status: str = None):
    """List recent incidents."""
    try:
        from src.incident_orchestrator import get_orchestrator
        orchestrator = get_orchestrator(get_current_region())
        return {"success": True, "incidents": orchestrator.list_incidents(limit, status)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/incident/stats")
async def incident_stats():
    """Get incident pipeline statistics."""
    try:
        from src.incident_orchestrator import get_orchestrator
        orchestrator = get_orchestrator(get_current_region())
        return {"success": True, **orchestrator.get_stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/incident/{incident_id}")
async def get_incident_detail(incident_id: str):
    """Get full incident detail including RCA, SOP, and safety results."""
    try:
        from src.incident_orchestrator import get_orchestrator
        orchestrator = get_orchestrator(get_current_region())
        incident = orchestrator.get_incident(incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        return {"success": True, "incident": incident.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/incident/{incident_id}/rca")
async def trigger_incident_rca(incident_id: str):
    """Trigger RCA analysis for a specific incident."""
    try:
        from src.incident_orchestrator import get_orchestrator
        from src.rca_inference import get_rca_engine
        orchestrator = get_orchestrator(get_current_region())
        incident = orchestrator.get_incident(incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")

        if incident.rca_result:
            return {"success": True, "rca": incident.rca_result, "cached": True}

        rca_engine = get_rca_engine()
        telemetry = incident.collection_summary or {}
        rca_result = await rca_engine.analyze(telemetry)
        incident.rca_result = rca_result.to_dict() if hasattr(rca_result, 'to_dict') else rca_result
        return {"success": True, "rca": incident.rca_result, "cached": False}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/safety/approve/{approval_id}")
async def approve_execution(approval_id: str, approved_by: str = "webui_user"):
    """Approve a pending SOP execution."""
    try:
        from src.sop_safety import get_safety_layer
        safety = get_safety_layer()
        result = safety.approve(approval_id, approved_by)
        if not result:
            raise HTTPException(status_code=404, detail="Approval not found or already processed")
        return {
            "success": True,
            "approval_id": approval_id,
            "status": "approved",
            "sop_id": result.sop_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/safety/reject/{approval_id}")
async def reject_execution(approval_id: str, rejected_by: str = "webui_user"):
    """Reject a pending SOP execution."""
    try:
        from src.sop_safety import get_safety_layer
        safety = get_safety_layer()
        result = safety.reject(approval_id, rejected_by)
        if not result:
            raise HTTPException(status_code=404, detail="Approval not found or already processed")
        return {
            "success": True,
            "approval_id": approval_id,
            "status": "rejected",
            "sop_id": result.sop_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# SOP Execution (manual flow from WebUI)
# =============================================================================

@router.post("/api/sop/execute/{sop_id}/manual")
async def manual_execute_sop(sop_id: str, incident_id: str = None, dry_run: bool = False):
    """Start manual SOP execution from WebUI."""
    try:
        from src.sop_system import get_sop_executor, get_sop_store
        from src.sop_safety import get_safety_layer

        store = get_sop_store()
        executor = get_sop_executor()
        safety = get_safety_layer()

        sop = store.get_sop(sop_id)
        if not sop:
            raise HTTPException(status_code=404, detail=f"SOP {sop_id} not found")

        safety_result = safety.check(sop_id=sop_id, dry_run=dry_run)

        execution = executor.start_execution(
            sop_id=sop_id,
            triggered_by="manual_fix",
            context={"incident_id": incident_id, "dry_run": dry_run},
        )
        if not execution:
            raise HTTPException(status_code=500, detail="Failed to start execution")

        return {
            "success": True,
            "execution_id": execution.execution_id,
            "sop_id": sop_id,
            "sop_name": sop.name,
            "safety": safety_result.to_dict() if hasattr(safety_result, 'to_dict') else {},
            "steps": [{"index": i, "description": s.description if hasattr(s, 'description') else str(s), "status": "pending"} for i, s in enumerate(sop.steps)],
            "total_steps": len(sop.steps),
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/sop/execute/{execution_id}/step")
async def complete_sop_step(execution_id: str, step_index: int = 0, result: str = "success", notes: str = ""):
    """Mark a SOP step as complete."""
    try:
        from src.sop_system import get_sop_executor
        executor = get_sop_executor()

        execution = executor.get_execution(execution_id)
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

        step_result = {
            "step_index": step_index,
            "result": result,
            "notes": notes,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        success = executor.complete_step(execution_id, step_result)
        if not success:
            return {"success": False, "error": "Failed to complete step"}

        execution = executor.get_execution(execution_id)
        return {
            "success": True,
            "execution_id": execution_id,
            "current_step": execution.current_step,
            "status": execution.status,
            "completed": execution.status == "completed",
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/sop/execute/{execution_id}/complete")
async def complete_sop_execution(execution_id: str, overall_result: str = "resolved", notes: str = ""):
    """Mark entire SOP execution as complete and trigger feedback loop."""
    try:
        from src.sop_system import get_sop_executor
        from src.incident_orchestrator import get_orchestrator
        executor = get_sop_executor()

        execution = executor.get_execution(execution_id)
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

        execution.status = "completed" if overall_result == "resolved" else "failed"
        execution.success = overall_result == "resolved"
        execution.notes = notes
        execution.completed_at = datetime.now(timezone.utc).isoformat()

        incident_id = execution.trigger_context.get("incident_id")
        if incident_id:
            try:
                orchestrator = get_orchestrator(get_current_region())
                incident = orchestrator.get_incident(incident_id)
                if incident:
                    incident.execution_result = {
                        "execution_id": execution_id,
                        "sop_id": execution.sop_id,
                        "result": overall_result,
                        "notes": notes,
                        "completed_at": execution.completed_at,
                    }
                    from src.incident_orchestrator import IncidentStatus
                    incident.status = IncidentStatus.COMPLETED
                    incident.completed_at = execution.completed_at
            except Exception as e:
                logger.warning(f"Failed to update incident feedback: {e}")

        return {
            "success": True,
            "execution_id": execution_id,
            "status": execution.status,
            "result": overall_result,
            "feedback_recorded": incident_id is not None,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Webhook
# =============================================================================

@router.post("/api/webhook/alarm")
async def webhook_alarm(request: Request):
    """Receive CloudWatch Alarm notifications via SNS."""
    try:
        body = await request.json()
        from src.alarm_webhook import handle_alarm_webhook
        result = await handle_alarm_webhook(body)
        return result
    except Exception as e:
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()[:500]}


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}
