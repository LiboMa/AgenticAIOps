"""Metrics & logs intents: EC2 metrics, RDS metrics, Lambda logs."""

import re
from typing import Optional

from routers.deps import get_current_region, logger


def _get_ops():
    try:
        from src.aws_ops import get_aws_ops
        return get_aws_ops(get_current_region())
    except ImportError:
        return None


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Route metrics / logs intents.  Returns None if not matched."""

    # --- EC2 Metrics ---
    if any(kw in message_lower for kw in ['ec2 metrics', 'ec2 指标', 'ec2 监控']):
        return _ec2_metrics(message)

    # --- RDS Metrics ---
    if any(kw in message_lower for kw in ['rds metrics', 'rds 指标', 'rds 监控', 'database metrics']):
        return _rds_metrics(message)

    # --- Lambda Logs ---
    if any(kw in message_lower for kw in ['lambda logs', 'lambda 日志', 'function logs']):
        return _lambda_logs(message, message_lower)

    return None


# =========================================================================
# Private helpers
# =========================================================================

def _ec2_metrics(message: str) -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    instance_match = re.search(r'i-[a-f0-9]+', message)
    if instance_match:
        instance_id = instance_match.group()
        try:
            metrics = ops.ec2_get_metrics(instance_id)
            response = f"""📊 **EC2 Metrics** - {instance_id}

| Metric | Average | Max | Min |
|--------|---------|-----|-----|"""
            for metric_name, data in metrics.get('metrics', {}).items():
                if data:
                    response += f"\n| {metric_name} | {data.get('avg', 0):.2f} | {data.get('max', 0):.2f} | {data.get('min', 0):.2f} |"
            return response
        except Exception as e:
            return f"❌ 获取 EC2 指标失败: {str(e)}"
    else:
        return "请指定实例 ID，例如: `EC2 metrics i-0123456789abcdef0`"


def _rds_metrics(message: str) -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    words = message.split()
    db_id = None
    for i, word in enumerate(words):
        if word.lower() in ['metrics', 'for', '指标']:
            if i + 1 < len(words):
                db_id = words[i + 1]
                break
    if db_id and not db_id.startswith(('metrics', 'for')):
        try:
            metrics = ops.rds_get_metrics(db_id)
            response = f"""📊 **RDS Metrics** - {db_id}

| Metric | Average | Max |
|--------|---------|-----|"""
            for metric_name, data in metrics.get('metrics', {}).items():
                if data:
                    value = data.get('avg', 0)
                    if 'Storage' in metric_name or 'Memory' in metric_name:
                        value = value / (1024**3)
                        response += f"\n| {metric_name} | {value:.2f} GB | {data.get('max', 0) / (1024**3):.2f} GB |"
                    else:
                        response += f"\n| {metric_name} | {value:.2f} | {data.get('max', 0):.2f} |"
            return response
        except Exception as e:
            return f"❌ 获取 RDS 指标失败: {str(e)}"
    else:
        health = ops.rds_health_check()
        response = f"""📊 **RDS Metrics Summary** (Region: {get_current_region()})

| Database | CPU Avg | CPU Max | Connections |
|----------|---------|---------|-------------|"""
        for db in health.get('databases', []):
            response += f"\n| {db['id']} | {db.get('cpu_avg', 0):.1f}% | {db.get('cpu_max', 0):.1f}% | {db.get('connections', 0):.0f} |"
        response += "\n\n💡 查看详细指标: `RDS metrics <db-id>`"
        return response


def _lambda_logs(message: str, message_lower: str) -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    words = message.split()
    func_name = None
    for i, word in enumerate(words):
        if word.lower() in ['logs', 'log', '日志', 'for']:
            if i + 1 < len(words) and words[i + 1].lower() not in ['logs', 'log', '日志', 'for']:
                func_name = words[i + 1]
                break
    if func_name:
        try:
            filter_errors = 'error' in message_lower
            logs = ops.lambda_get_logs(func_name, hours=1, filter_errors=filter_errors)
            response = f"""📜 **Lambda Logs** - {func_name}
{'(Filtered: ERRORS only)' if filter_errors else ''}

"""
            events = logs.get('events', [])
            if events:
                for event in events[:20]:
                    response += f"**{event['timestamp']}**\n```\n{event['message'][:200]}\n```\n\n"
            else:
                response += "📭 没有找到日志记录"
            return response
        except Exception as e:
            return f"❌ 获取 Lambda 日志失败: {str(e)}"
    else:
        return "请指定函数名，例如: `Lambda logs my-function` 或 `Lambda error logs my-function`"
