"""Router: /api/a2ui - Agent-to-UI widget endpoints."""

from datetime import datetime

from fastapi import APIRouter

from routers.schemas import A2UIGenerateRequest, A2UIGenerateResponse, A2UIWidgetConfig

router = APIRouter(tags=["a2ui"])


def detect_ui_action(message: str):
    """Detect if the message is requesting a UI action (A2UI)."""
    message_lower = message.lower()

    add_patterns = ['添加', 'add', '创建', 'create', '显示', 'show', '生成', 'generate']
    widget_types = {
        'ec2': 'stat-card',
        'lambda': 'table',
        'cpu': 'stat-card',
        'memory': 'stat-card',
        'alert': 'alert-list',
        '告警': 'alert-list',
        'service': 'service-status',
        '服务': 'service-status',
        'table': 'table',
        '表格': 'table',
        'card': 'stat-card',
        '卡片': 'stat-card',
    }

    is_add_request = any(pattern in message_lower for pattern in add_patterns)
    if not is_add_request:
        return None

    detected_type = None
    detected_title = "New Widget"

    for keyword, wtype in widget_types.items():
        if keyword in message_lower:
            detected_type = wtype
            detected_title = f"{keyword.upper()} Monitor"
            break

    if detected_type:
        return {
            "action": "add_widget",
            "widget": {
                "type": detected_type,
                "config": {
                    "title": detected_title,
                    "value": 0 if detected_type == 'stat-card' else None,
                    "icon": "cloud",
                    "color": "#06AC38"
                },
                "span": 24 if detected_type == 'table' else 8
            }
        }

    return None


@router.post("/api/a2ui/generate", response_model=A2UIGenerateResponse)
async def a2ui_generate(request: A2UIGenerateRequest):
    """Generate a UI widget configuration from natural language prompt."""
    try:
        ui_action = detect_ui_action(request.prompt)

        if ui_action and ui_action.get("widget"):
            widget = ui_action["widget"]
            widget["id"] = f"widget-{int(datetime.now().timestamp() * 1000)}"

            return A2UIGenerateResponse(
                success=True,
                widget=A2UIWidgetConfig(**widget),
                message=f"Created {widget['type']} widget: {widget['config'].get('title', 'Untitled')}"
            )
        else:
            return A2UIGenerateResponse(
                success=False,
                widget=None,
                message="Could not understand the widget request. Try: 'Add an EC2 monitoring card' or 'Create a Lambda table'"
            )
    except Exception as e:
        return A2UIGenerateResponse(
            success=False,
            widget=None,
            message=f"Error: {str(e)}"
        )


@router.get("/api/a2ui/widget-types")
async def a2ui_widget_types():
    """Get available widget types for A2UI."""
    return {
        "types": [
            {"key": "stat-card", "name": "Stat Card", "description": "KPI/metric display", "icon": "📊"},
            {"key": "table", "name": "Table", "description": "Data table with columns", "icon": "📋"},
            {"key": "alert-list", "name": "Alert List", "description": "List of alerts/issues", "icon": "⚠️"},
            {"key": "service-status", "name": "Service Status", "description": "Service health indicators", "icon": "🟢"},
            {"key": "progress-bar", "name": "Progress Bar", "description": "Progress/utilization meter", "icon": "📈"},
            {"key": "resource-list", "name": "Resource List", "description": "Cloud resource listing", "icon": "☁️"},
        ]
    }
