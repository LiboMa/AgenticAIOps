"""Operations intents: EC2 start/stop/reboot, RDS reboot/failover, Lambda invoke, notifications."""

import re
import traceback
from typing import Optional

from routers.deps import get_scanner, get_current_region, logger


def _get_ops():
    try:
        from src.aws_ops import get_aws_ops
        return get_aws_ops(get_current_region())
    except ImportError:
        return None


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Route operation intents. Returns None if not matched."""

    # --- EC2 Start ---
    if any(kw in message_lower for kw in ['ec2 start', 'start ec2', 'start instance', '启动实例', '启动 ec2']):
        return _ec2_action(message, 'start')

    # --- EC2 Stop ---
    if any(kw in message_lower for kw in ['ec2 stop', 'stop ec2', 'stop instance', '停止实例', '停止 ec2']):
        return _ec2_action(message, 'stop')

    # --- EC2 Reboot ---
    if any(kw in message_lower for kw in ['ec2 reboot', 'reboot ec2', 'reboot instance', '重启实例', '重启 ec2']):
        return _ec2_action(message, 'reboot')

    # --- RDS Reboot ---
    if any(kw in message_lower for kw in ['rds reboot', 'reboot rds', 'restart rds', '重启 rds', '重启数据库']):
        return _rds_reboot(message, message_lower)

    # --- RDS Failover ---
    if any(kw in message_lower for kw in ['rds failover', 'failover rds', '故障转移']):
        return _rds_failover(message, message_lower)

    # --- Lambda Invoke ---
    if any(kw in message_lower for kw in ['lambda invoke', 'invoke lambda', '调用 lambda', '执行 lambda']):
        return _lambda_invoke(message)

    # --- Notification Status ---
    if any(kw in message_lower for kw in ['notification status', '通知状态', 'alert status', '告警状态']):
        return _notification_status()

    # --- Test Notification ---
    if any(kw in message_lower for kw in ['test notification', '测试通知', 'test alert', '测试告警']):
        return _test_notification()

    # --- Send Alert ---
    if any(kw in message_lower for kw in ['send alert', '发送告警']):
        return _send_alert(message)

    return None


# =========================================================================
# Private helpers — EC2 operations
# =========================================================================

def _ec2_action(message: str, action: str) -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"

    match = re.search(r'(i-[a-f0-9]+)', message)
    if not match:
        return f"""⚠️ **请提供 Instance ID**

用法: `ec2 {action} i-xxxxxxxxx`

示例:
- `ec2 {action} i-0abc123def456`
- `{action} instance i-0abc123def456`"""

    instance_id = match.group(1)
    try:
        result = ops.ec2_operations(instance_id, action)
        if result.get('success'):
            if action == 'start':
                return f"""✅ **EC2 Start 命令已发送**

| 项目 | 值 |
|------|-----|
| Instance ID | `{instance_id}` |
| Action | Start |
| Status | 启动中... |

⏳ 实例启动需要 1-2 分钟，请稍后使用 `ec2 health {instance_id}` 检查状态。"""
            elif action == 'stop':
                return f"""🛑 **EC2 Stop 命令已发送**

| 项目 | 值 |
|------|-----|
| Instance ID | `{instance_id}` |
| Action | Stop |
| Status | 停止中... |

⏳ 实例停止需要 30-60 秒。"""
            else:  # reboot
                return f"""🔄 **EC2 Reboot 命令已发送**

| 项目 | 值 |
|------|-----|
| Instance ID | `{instance_id}` |
| Action | Reboot |
| Status | 重启中... |

⏳ 实例重启需要 1-2 分钟。"""
        else:
            return f"❌ {action} 失败: {result.get('error')}"
    except Exception as e:
        return f"❌ {action} EC2 失败: {str(e)}"


# =========================================================================
# Private helpers — RDS operations
# =========================================================================

def _rds_reboot(message: str, message_lower: str) -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"

    match = re.search(r'([a-z0-9][a-z0-9-]*[a-z0-9])', message_lower)
    if not match or match.group(1) in ['rds', 'reboot', 'restart']:
        return """⚠️ **请提供 DB Identifier**

用法: `rds reboot mydb-instance`

示例:
- `rds reboot production-mysql`
- `restart rds test-postgres`"""

    db_id = match.group(1)
    try:
        result = ops.rds_operations(db_id, 'reboot')
        if result.get('success'):
            return f"""🔄 **RDS Reboot 命令已发送**

| 项目 | 值 |
|------|-----|
| DB ID | `{db_id}` |
| Action | Reboot |
| Status | {result.get('status', 'rebooting')} |

⏳ 数据库重启需要几分钟，请稍后检查状态。"""
        else:
            return f"❌ 重启失败: {result.get('error')}"
    except Exception as e:
        return f"❌ RDS 重启失败: {str(e)}"


def _rds_failover(message: str, message_lower: str) -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"

    match = re.search(r'([a-z0-9][a-z0-9-]*[a-z0-9])', message_lower)
    if not match or match.group(1) in ['rds', 'failover']:
        return """⚠️ **请提供 DB Identifier**

用法: `rds failover mydb-instance`

注意: 仅适用于 Multi-AZ 部署"""

    db_id = match.group(1)
    try:
        result = ops.rds_operations(db_id, 'failover')
        if result.get('success'):
            return f"""⚠️ **RDS Failover 命令已发送**

| 项目 | 值 |
|------|-----|
| DB ID | `{db_id}` |
| Action | Failover |
| Status | {result.get('status', 'failing-over')} |

⏳ 故障转移进行中..."""
        else:
            return f"❌ Failover 失败: {result.get('error')}"
    except Exception as e:
        return f"❌ RDS Failover 失败: {str(e)}"


# =========================================================================
# Private helpers — Lambda invoke
# =========================================================================

def _lambda_invoke(message: str) -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"

    match = re.search(r'invoke\s+([a-zA-Z0-9_-]+)|([a-zA-Z0-9_-]+)\s+invoke', message)
    if not match:
        return """⚠️ **请提供 Function Name**

用法: `lambda invoke my-function`

示例:
- `lambda invoke hello-world`
- `invoke lambda process-data`"""

    function_name = match.group(1) or match.group(2)
    if function_name.lower() in ['lambda', 'invoke']:
        return "⚠️ 请提供函数名称"

    try:
        result = ops.lambda_invoke(function_name)
        if result.get('success'):
            response_preview = str(result.get('response', ''))[:200]
            return f"""✅ **Lambda Invoke 成功**

| 项目 | 值 |
|------|-----|
| Function | `{function_name}` |
| Status Code | {result.get('status_code', 'N/A')} |
| Type | {result.get('invocation_type', 'sync')} |

**Response Preview:**
```
{response_preview}...
```"""
        else:
            return f"❌ 调用失败: {result.get('error')}"
    except Exception as e:
        return f"❌ Lambda Invoke 失败: {str(e)}"


# =========================================================================
# Private helpers — Notifications
# =========================================================================

def _notification_status() -> str:
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()
        status = manager.get_status()

        slack_status = "✅ 已配置" if status['channels']['slack'] else "❌ 未配置 (需设置 SLACK_WEBHOOK_URL)"

        return f"""🔔 **告警通知状态**

| Channel | Status |
|---------|--------|
| Slack | {slack_status} |

**配置方法:**
设置环境变量 `SLACK_WEBHOOK_URL` 即可启用 Slack 告警"""
    except Exception as e:
        return f"❌ 获取通知状态失败: {str(e)}"


def _test_notification() -> str:
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()

        if not manager.is_configured():
            return """⚠️ **告警通知未配置**

请设置 `SLACK_WEBHOOK_URL` 环境变量后重试。

示例:
```
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
```"""

        result = manager.send_alert(
            title="测试告警",
            message="这是一条测试消息，确认告警通知功能正常工作。",
            level="info",
            details={"Source": "AgenticAIOps", "Type": "Test"}
        )

        if result.get('success'):
            return "✅ **测试告警已发送！** 请检查 Slack 频道。"
        else:
            return f"❌ 发送失败: {result.get('error')}"
    except Exception as e:
        return f"❌ 测试通知失败: {str(e)}"


def _send_alert(message: str) -> str:
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()

        if not manager.is_configured():
            return "⚠️ 告警通知未配置，请设置 SLACK_WEBHOOK_URL"

        match = re.search(r'alert\s+(.+)', message, re.IGNORECASE)
        if match:
            alert_message = match.group(1)
            result = manager.send_alert(
                title="自定义告警",
                message=alert_message,
                level="warning"
            )
            if result.get('success'):
                return f"✅ 告警已发送: {alert_message[:50]}..."
            else:
                return f"❌ 发送失败: {result.get('error')}"
        else:
            return """**发送自定义告警**

用法: `send alert <消息内容>`

示例: `send alert Production DB CPU 超过 90%`"""
    except Exception as e:
        return f"❌ 发送告警失败: {str(e)}"
