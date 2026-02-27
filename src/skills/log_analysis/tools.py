"""Log Analysis Skill — 8 tools (CloudWatch Logs/K8s/local)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from .._security import secure_tool
from .._models import SecurityTier, ToolResult
from .._executor import ShellExecutor, KubectlExec

_shell = ShellExecutor(timeout=30)
_kubectl = KubectlExec(timeout=60)

def _boto(svc, method, **kw):
    try:
        import boto3; c = boto3.client(svc); r = getattr(c, method)(**kw); r.pop("ResponseMetadata", None); return r
    except Exception as e: return {"error": str(e)}

@secure_tool(tier=SecurityTier.T0_READONLY, skill="log_analysis", command_param=None)
def cw_logs_query(log_group: str, query: str = "fields @timestamp, @message | sort @timestamp desc | limit 50", hours: int = 1) -> str:
    """Run CloudWatch Logs Insights query."""
    now = datetime.now(timezone.utc)
    return ToolResult.success(_boto("logs", "start_query",
        logGroupName=log_group, queryString=query,
        startTime=int((now - timedelta(hours=min(hours, 24))).timestamp()),
        endTime=int(now.timestamp()), limit=100)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="log_analysis", command_param=None)
def k8s_pod_logs(pod_name: str, namespace: str = "default", tail: int = 100, container: str = "") -> str:
    """Get Kubernetes pod logs."""
    args = ["logs", pod_name, f"--tail={min(tail, 500)}"]
    if container: args.extend(["-c", container])
    r = _kubectl.execute(args, namespace=namespace, output_format="")
    return ToolResult.success(r.stdout if r.ok else r.stderr).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="log_analysis", command_param=None)
def local_log_search(log_path: str = "/var/log/syslog", pattern: str = "error", lines: int = 50) -> str:
    """Search local log files with grep."""
    lines = min(lines, 200)
    r = _shell.execute(f"grep -i '{pattern}' {log_path} | tail -n {lines}")
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="log_analysis", command_param=None)
def journalctl_query(unit: str = "", priority: str = "err", lines: int = 50) -> str:
    """Query systemd journal."""
    lines = min(lines, 200)
    cmd = f"journalctl -p {priority} -n {lines} --no-pager"
    if unit: cmd += f" -u {unit}"
    r = _shell.execute(cmd)
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="log_analysis", command_param=None)
def cw_log_groups(prefix: str = "") -> str:
    """List CloudWatch log groups."""
    kwargs = {}
    if prefix: kwargs["logGroupNamePrefix"] = prefix
    return ToolResult.success(_boto("logs", "describe_log_groups", **kwargs)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="log_analysis", command_param=None)
def error_rate_analysis(log_path: str = "/var/log/syslog", window_minutes: int = 60) -> str:
    """Analyze error rate in log file over time window."""
    r = _shell.execute(f"grep -ci 'error\\|fatal\\|critical' {log_path} || echo '0'")
    total = _shell.execute(f"wc -l < {log_path} 2>/dev/null || echo '0'")
    return ToolResult.success({
        "error_count": r.stdout.strip(), "total_lines": total.stdout.strip(),
        "log_path": log_path,
    }).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="log_analysis", command_param=None)
def log_pattern_detect(log_path: str = "/var/log/syslog", top_n: int = 10) -> str:
    """Detect most frequent log patterns."""
    r = _shell.execute(f"cat {log_path} | sed 's/[0-9]\\+/N/g' | sort | uniq -c | sort -rn | head -n {min(top_n, 50)}")
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="log_analysis", command_param=None)
def multi_source_search(query: str, sources: str = "syslog,auth") -> str:
    """Search across multiple log sources."""
    results = {}
    for src in sources.split(",")[:5]:
        src = src.strip()
        path = f"/var/log/{src}" if "/" not in src else src
        r = _shell.execute(f"grep -i '{query}' {path} 2>/dev/null | tail -20")
        results[src] = r.stdout if r.ok else f"not found: {path}"
    return ToolResult.success(results).to_json()
