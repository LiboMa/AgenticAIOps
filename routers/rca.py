"""Router: /api/rca - RCA reports and RCA↔SOP bridge."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException

from routers.schemas import RCAReport, RCAAnalyzeRequest, RCAFeedbackRequest
from routers.deps import rca_reports

router = APIRouter(tags=["rca"])


@router.get("/api/rca/reports")
async def list_rca_reports():
    """List all RCA reports."""
    return {"reports": rca_reports}


@router.post("/api/rca/reports")
async def create_rca_report(report: RCAReport):
    """Create a new RCA report."""
    rca_reports.append(report.dict())
    return {"status": "created", "id": report.id}


@router.get("/api/rca/reports/{report_id}")
async def get_rca_report(report_id: str):
    """Get a specific RCA report."""
    for report in rca_reports:
        if report["id"] == report_id:
            return report
    raise HTTPException(status_code=404, detail="Report not found")


@router.post("/api/rca/analyze")
async def rca_analyze(request: RCAAnalyzeRequest = None):
    """Run RCA analysis with SOP recommendations."""
    try:
        if request is None:
            request = RCAAnalyzeRequest()
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()

        result = bridge.analyze_and_suggest(
            namespace=request.namespace,
            pod=request.pod,
            symptoms=request.symptoms,
            auto_execute=request.auto_execute,
        )

        return {
            "success": True,
            "result": result.to_dict(),
            "markdown": result.to_markdown(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/rca/feedback")
async def rca_feedback(request: RCAFeedbackRequest):
    """Submit feedback from SOP execution back to RCA."""
    try:
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()

        feedback = bridge.submit_feedback(
            execution_id=request.execution_id,
            sop_id=request.sop_id,
            rca_pattern_id=request.rca_pattern_id,
            success=request.success,
            root_cause_confirmed=request.root_cause_confirmed,
            resolution_time_seconds=request.resolution_time_seconds,
            notes=request.notes,
        )

        return {
            "success": True,
            "feedback_recorded": True,
            "success_rate": bridge.get_feedback_stats()['success_rate'],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/rca/bridge/stats")
async def rca_bridge_stats():
    """Get RCA ↔ SOP bridge statistics and learned mappings."""
    try:
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()
        return {"success": True, **bridge.get_feedback_stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/rca/bridge/history")
async def rca_bridge_history(limit: int = 20):
    """Get recent RCA → SOP bridge results."""
    try:
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()
        return {"success": True, "history": bridge.get_history(limit)}
    except Exception as e:
        return {"success": False, "error": str(e)}
