"""Router: /api/anomalies - Anomaly detection."""

from datetime import datetime, timezone

from fastapi import APIRouter

from routers.deps import get_pods

router = APIRouter(tags=["anomalies"])


@router.get("/api/anomalies")
async def detect_anomalies():
    """Detect anomalies in the cluster."""
    anomalies = []

    try:
        pods_data = get_pods()

        for pod in pods_data.get('pods', []):
            status = pod.get('status', '')
            restarts = pod.get('restarts', 0)

            if 'CrashLoop' in status:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "critical",
                    "type": "CrashLoopBackOff",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": f"Pod has restarted {restarts} times",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "aiSuggestion": "Check application logs and configuration."
                })
            elif 'OOM' in status:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "critical",
                    "type": "OOMKilled",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": "Container killed due to out of memory",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "aiSuggestion": "Increase memory limits in deployment spec."
                })
            elif restarts > 5:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "warning",
                    "type": "HighRestarts",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": f"Pod restart count ({restarts}) exceeds threshold",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "aiSuggestion": "Review application health and probe configurations."
                })

    except Exception:
        pass

    return {"anomalies": anomalies}
