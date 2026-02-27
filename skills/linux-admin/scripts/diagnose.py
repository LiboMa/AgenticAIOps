"""Linux Admin diagnostic tools for Strands Agent.

Each function is decorated with @tool for automatic registration
via SkillLoader.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

from strands import tool

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds


def _run(cmd: str, timeout: int = _TIMEOUT) -> str:
    """Execute a shell command and return stdout+stderr."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Command timed out after {timeout}s: {cmd}"
    except Exception as e:
        return f"[ERROR] {e}"


@tool
def system_overview() -> str:
    """Get a quick system health overview: uptime, memory, disk, load.

    Returns a combined snapshot of system status for initial triage.
    """
    commands = [
        ("Uptime", "uptime"),
        ("Memory", "free -h"),
        ("Disk", "df -h --total"),
        ("Load", "cat /proc/loadavg"),
        ("Top Processes (CPU)", "ps auxf --sort=-%cpu | head -10"),
        ("Top Processes (MEM)", "ps auxf --sort=-%mem | head -10"),
    ]
    sections = []
    for label, cmd in commands:
        sections.append(f"=== {label} ===\n{_run(cmd)}")
    return "\n\n".join(sections)


@tool
def check_disk_usage(path: str = "/") -> str:
    """Check disk usage for a specific path.

    Args:
        path: Filesystem path to check (default: /)

    Returns:
        Disk usage summary including large files.
    """
    parts = [
        f"=== df ===\n{_run(f'df -h {path}')}",
        f"=== du top dirs ===\n{_run(f'du -sh {path}/* 2>/dev/null | sort -rh | head -15')}",
    ]
    return "\n\n".join(parts)


@tool
def check_process(
    pid: Optional[int] = None,
    name: Optional[str] = None,
    port: Optional[int] = None,
) -> str:
    """Investigate a process by PID, name, or port.

    Args:
        pid: Process ID to inspect.
        name: Process name to search for (grep).
        port: Network port to find the owning process.

    Returns:
        Process details including open files, connections, and resource usage.
    """
    if pid:
        parts = [
            f"=== ps ===\n{_run(f'ps -p {pid} -o pid,ppid,user,%cpu,%mem,stat,start,command')}",
            f"=== lsof ===\n{_run(f'lsof -p {pid} 2>/dev/null | head -30')}",
        ]
        return "\n\n".join(parts)
    elif name:
        return _run(f"ps aux | grep -i '{name}' | grep -v grep")
    elif port:
        return _run(f"ss -tlnp | grep :{port}")
    else:
        return "[ERROR] Provide at least one of: pid, name, or port"


@tool
def check_logs(
    service: Optional[str] = None,
    file: Optional[str] = None,
    lines: int = 50,
    grep: Optional[str] = None,
) -> str:
    """Check system or service logs.

    Args:
        service: Systemd service name (uses journalctl).
        file: Log file path (e.g. /var/log/syslog).
        lines: Number of lines to return (default 50).
        grep: Filter pattern to grep for.

    Returns:
        Recent log entries.
    """
    if service:
        cmd = f"journalctl -u {service} --no-pager -n {lines}"
        if grep:
            cmd += f" | grep -i '{grep}'"
        return _run(cmd)
    elif file:
        cmd = f"tail -n {lines} {file}"
        if grep:
            cmd += f" | grep -i '{grep}'"
        return _run(cmd)
    else:
        # Default: recent syslog + dmesg
        parts = [
            f"=== syslog ===\n{_run(f'tail -n {lines} /var/log/syslog 2>/dev/null || journalctl -n {lines} --no-pager')}",
            f"=== dmesg ===\n{_run(f'dmesg -T | tail -n {lines}')}",
        ]
        return "\n\n".join(parts)


@tool
def check_network(
    port: Optional[int] = None,
    target: Optional[str] = None,
) -> str:
    """Diagnose network connectivity and listening services.

    Args:
        port: Check what's listening on this port.
        target: Host/IP to check connectivity to (ping + traceroute).

    Returns:
        Network diagnostic output.
    """
    parts = []
    if port:
        parts.append(f"=== Port {port} ===\n{_run(f'ss -tlnp | grep :{port}')}")
    if target:
        parts.append(f"=== Ping ===\n{_run(f'ping -c 3 -W 2 {target}')}")
        parts.append(f"=== Traceroute ===\n{_run(f'traceroute -m 10 -w 2 {target} 2>/dev/null || tracepath {target}')}")
    if not parts:
        parts = [
            f"=== Listening ===\n{_run('ss -tlnp')}",
            f"=== Connections ===\n{_run('ss -s')}",
        ]
    return "\n\n".join(parts)
