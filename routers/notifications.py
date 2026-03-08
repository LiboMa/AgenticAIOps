"""Router: /api/notifications - Notification management."""

from typing import Optional, Dict, Any

from fastapi import APIRouter

from routers.schemas import AlertRequest

router = APIRouter(tags=["notifications"])


@router.get("/api/notifications/status")
async def get_notification_status():
    """Get notification system status."""
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()
        return manager.get_status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/notifications/test")
async def send_test_notification():
    """Send a test notification."""
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()

        if not manager.is_configured():
            return {"success": False, "error": "No notification channels configured"}

        result = manager.send_alert(
            title="Test Alert",
            message="This is a test notification from AgenticAIOps",
            level="info"
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/notifications/send")
async def send_notification(request: AlertRequest):
    """Send a custom notification."""
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()

        result = manager.send_alert(
            title=request.title,
            message=request.message,
            level=request.level,
            details=request.details
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}
