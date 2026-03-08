"""Monitoring Skill — 10 tools (CloudWatch/Prometheus/Datadog)."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from .._security import secure_tool
from .._models import SecurityTier, ToolResult

def _boto(svc, method, **kw):
    try:
        import boto3
        c = boto3.client(svc)
        r = getattr(c, method)(**kw)
        r.pop("ResponseMetadata", None)
        return r
    except Exception as e:
        return {"error": str(e)}

@secure_tool(tier=SecurityTier.T0_READONLY, skill="monitoring", command_param=None)
def cw_get_alarms(state: str = "ALARM") -> str:
    """Get CloudWatch alarms by state (ALARM/OK/INSUFFICIENT_DATA)."""
    return ToolResult.success(_boto("cloudwatch", "describe_alarms", StateValue=state)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="monitoring", command_param=None)
def cw_get_metric(namespace: str, metric_name: str, dimensions: str = "",
                  period: int = 300, stat: str = "Average", hours: int = 1) -> str:
    """Get CloudWatch metric data."""
    now = datetime.now(timezone.utc)
    kwargs = {
        "Namespace": namespace, "MetricName": metric_name,
        "StartTime": now - timedelta(hours=min(hours, 24)),
        "EndTime": now, "Period": period, "Statistics": [stat],
    }
    if dimensions:
        parts = dimensions.split("=")
        if len(parts) == 2:
            kwargs["Dimensions"] = [{"Name": parts[0], "Value": parts[1]}]
    return ToolResult.success(_boto("cloudwatch", "get_metric_statistics", **kwargs)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="monitoring", command_param=None)
def cw_log_insights(log_group: str, query: str, hours: int = 1) -> str:
    """Run CloudWatch Logs Insights query."""
    now = datetime.now(timezone.utc)
    return ToolResult.success(_boto("logs", "start_query",
        logGroupName=log_group, queryString=query,
        startTime=int((now - timedelta(hours=min(hours, 24))).timestamp()),
        endTime=int(now.timestamp()), limit=100,
    )).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="monitoring", command_param=None)
def cw_alarm_history(alarm_name: str, days: int = 7) -> str:
    """Get CloudWatch alarm history."""
    now = datetime.now(timezone.utc)
    return ToolResult.success(_boto("cloudwatch", "describe_alarm_history",
        AlarmName=alarm_name,
        StartDate=now - timedelta(days=min(days, 30)),
        EndDate=now, MaxRecords=50,
    )).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="monitoring", command_param=None)
def prometheus_query(query: str, endpoint: str = "http://localhost:9090") -> str:
    """Execute a PromQL query against Prometheus."""
    try:
        import requests
        r = requests.get(f"{endpoint}/api/v1/query", params={"query": query}, timeout=10)
        return ToolResult.success(r.json()).to_json()
    except Exception as e:
        return ToolResult.fail(str(e)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="monitoring", command_param=None)
def prometheus_alerts(endpoint: str = "http://localhost:9090") -> str:
    """Get active Prometheus alerts."""
    try:
        import requests
        r = requests.get(f"{endpoint}/api/v1/alerts", timeout=10)
        return ToolResult.success(r.json()).to_json()
    except Exception as e:
        return ToolResult.fail(str(e)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="monitoring", command_param=None)
def cw_describe_log_groups(prefix: str = "") -> str:
    """List CloudWatch log groups."""
    kwargs = {}
    if prefix:
        kwargs["logGroupNamePrefix"] = prefix
    return ToolResult.success(_boto("logs", "describe_log_groups", **kwargs)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="monitoring", command_param=None)
def health_check_summary() -> str:
    """Summary of all monitoring sources health."""
    alarms = _boto("cloudwatch", "describe_alarms", StateValue="ALARM")
    alarm_count = len(alarms.get("MetricAlarms", [])) if isinstance(alarms, dict) else 0
    return ToolResult.success({"cloudwatch_alarms": alarm_count}).to_json()

# T1
@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="monitoring", command_param=None)
def cw_set_alarm_state(alarm_name: str, state: str = "OK", reason: str = "Manual reset") -> str:
    """Manually set CloudWatch alarm state (for testing/reset)."""
    return ToolResult.success(_boto("cloudwatch", "set_alarm_state",
        AlarmName=alarm_name, StateValue=state, StateReason=reason)).to_json()

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="monitoring", command_param=None)
def cw_enable_alarm(alarm_name: str, enable: bool = True) -> str:
    """Enable or disable a CloudWatch alarm."""
    method = "enable_alarm_actions" if enable else "disable_alarm_actions"
    return ToolResult.success(_boto("cloudwatch", method, AlarmNames=[alarm_name])).to_json()
