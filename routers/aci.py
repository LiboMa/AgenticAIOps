"""Router: /api/aci - Agent-Cloud Interface endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter

from routers.schemas import (
    ACILogsRequest, ACIMetricsRequest, ACIEventsRequest, DiagnosisRequest,
)
from routers.deps import ACI_AVAILABLE, VOTING_AVAILABLE

router = APIRouter(tags=["aci"])


@router.get("/api/aci/status")
async def aci_status():
    """Get ACI availability status."""
    return {
        "aci_available": ACI_AVAILABLE,
        "voting_available": VOTING_AVAILABLE,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.post("/api/aci/logs")
async def get_aci_logs(request: ACILogsRequest = None):
    """Get logs via ACI."""
    if request is None:
        request = ACILogsRequest()
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": []}

    try:
        from src.aci import AgentCloudInterface
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_logs(
            namespace=request.namespace,
            pod_name=request.pod_name,
            severity=request.severity,
            duration_minutes=request.duration_minutes,
            limit=request.limit
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": []}


@router.post("/api/aci/metrics")
async def get_aci_metrics(request: ACIMetricsRequest = None):
    """Get metrics via ACI (from Prometheus/CloudWatch)."""
    if request is None:
        request = ACIMetricsRequest()
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": {}}

    try:
        from src.aci import AgentCloudInterface
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_metrics(
            namespace=request.namespace,
            metric_names=request.metric_names
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": {}}


@router.post("/api/aci/events")
async def get_aci_events(request: ACIEventsRequest = None):
    """Get K8s events via ACI."""
    if request is None:
        request = ACIEventsRequest()
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": []}

    try:
        from src.aci import AgentCloudInterface
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_events(
            namespace=request.namespace,
            event_type=request.event_type if request.event_type != "all" else None,
            duration_minutes=request.duration_minutes,
            limit=request.limit
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": []}


@router.get("/api/aci/telemetry/{namespace}")
async def get_aci_telemetry(namespace: str):
    """Get all telemetry data for a namespace."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available"}

    try:
        from src.aci import AgentCloudInterface
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")

        logs = aci.get_logs(namespace=namespace, severity="error", limit=20)
        metrics = aci.get_metrics(namespace=namespace)
        events = aci.get_events(namespace=namespace, event_type="Warning", limit=30)

        return {
            "namespace": namespace,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logs": logs.to_dict(),
            "metrics": metrics.to_dict(),
            "events": events.to_dict()
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/aci/diagnosis")
async def run_diagnosis(request: DiagnosisRequest = None):
    """Run multi-agent diagnosis on a namespace."""
    if request is None:
        request = DiagnosisRequest()
    if not ACI_AVAILABLE or not VOTING_AVAILABLE:
        return {"error": "ACI or Voting not available"}

    try:
        from scripts.diagnosis.run_diagnosis import DiagnosisRunner

        runner = DiagnosisRunner(namespace=request.namespace)
        report = runner.run_diagnosis()

        return {
            "status": "success",
            "report": report
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}
