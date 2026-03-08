"""Alert API router — feed + stats for frontend Ops Hub."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/alert", tags=["alert"])


@router.get("/feed")
async def get_alert_feed(
    limit: int = Query(50, ge=1, le=200),
    provider: Optional[str] = Query(None),
):
    """Return recent alerts from AlertIngressService.

    Returns list of parsed alerts, newest first.
    """
    try:
        from src.alert.ingress import AlertIngressService

        svc = AlertIngressService()
        # Get recent alerts from the service's history
        alerts = list(getattr(svc, "_history", []))
        if provider:
            alerts = [a for a in alerts if a.get("provider") == provider]
        alerts = alerts[-limit:]
        alerts.reverse()
        return {"alerts": alerts, "total": len(alerts)}
    except Exception as e:
        return {"alerts": [], "total": 0, "error": str(e)}


@router.get("/stats")
async def get_alert_stats():
    """Return alert parser statistics — counts by provider and severity."""
    try:
        from src.alert.ingress import AlertIngressService

        svc = AlertIngressService()
        history = list(getattr(svc, "_history", []))

        by_provider = {}
        by_severity = {}
        for alert in history:
            p = alert.get("provider", "unknown")
            s = alert.get("severity", "unknown")
            by_provider[p] = by_provider.get(p, 0) + 1
            by_severity[s] = by_severity.get(s, 0) + 1

        return {
            "total": len(history),
            "by_provider": by_provider,
            "by_severity": by_severity,
            "dedup_cache_size": len(getattr(svc, "_seen", {})),
            "parsers": [
                "cloudwatch",
                "datadog",
                "pagerduty",
                "grafana",
                "generic",
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {
            "total": 0,
            "by_provider": {},
            "by_severity": {},
            "error": str(e),
        }
