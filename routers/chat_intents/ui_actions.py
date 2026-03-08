"""UI action detection: detect_ui_action for A2UI widget creation."""

from typing import Optional


def detect_ui_action(message: str) -> Optional[dict]:
    """Detect if the message is requesting a UI action (A2UI)."""
    message_lower = message.lower()

    # Widget creation patterns
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

    # Check if this is an add/create request
    is_add_request = any(pattern in message_lower for pattern in add_patterns)

    if not is_add_request:
        return None

    # Detect widget type
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


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Placeholder — ui_actions never produces a text response.

    The actual detect_ui_action() is called directly from chat().
    """
    return None
