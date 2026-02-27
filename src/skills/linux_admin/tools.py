"""Linux Admin Skill — 18 tools (12×T0, 4×T1, 1×T2, 1×T3)."""
from __future__ import annotations
import json
from .._security import secure_tool
from .._models import SecurityTier, ToolResult
from .._executor import ShellExecutor

_shell = ShellExecutor(timeout=30)

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def process_analysis(sort_by: str = "cpu", top_n: int = 20) -> str:
    """Analyze running processes sorted by resource consumption."""
    top_n = min(top_n, 50)
    flag = {"cpu": "-pcpu", "mem": "-pmem"}.get(sort_by, "-pcpu")
    r = _shell.execute(f"ps aux --sort={flag} | head -n {top_n + 1}")
    load = _shell.execute("cat /proc/loadavg")
    return ToolResult.success({"processes": r.stdout, "load": load.stdout.strip()}).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def resource_stats() -> str:
    """Get CPU, memory, disk, and load summary."""
    mem = _shell.execute("free -h")
    disk = _shell.execute("df -h --total 2>/dev/null || df -h")
    load = _shell.execute("cat /proc/loadavg")
    return ToolResult.success({"memory": mem.stdout, "disk": disk.stdout, "load": load.stdout.strip()}).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def disk_analysis(path: str = "/") -> str:
    """Analyze disk usage for a path."""
    df = _shell.execute(f"df -h {path}")
    du = _shell.execute(f"du -sh {path}/* 2>/dev/null | sort -rh | head -20")
    return ToolResult.success({"df": df.stdout, "top_dirs": du.stdout}).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def io_stats() -> str:
    """Get I/O statistics."""
    r = _shell.execute("iostat -x 1 1 2>/dev/null || cat /proc/diskstats | head -20")
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def network_diagnose(target: str = "", tool: str = "ss") -> str:
    """Network diagnostic — ping, traceroute, dig, ss."""
    cmds = {"ping": f"ping -c 3 -W 2 {target}", "ss": "ss -tuln", "dig": f"dig {target} +short"}
    r = _shell.execute(cmds.get(tool, "ss -tuln"), timeout=15)
    return ToolResult.success(r.stdout, tool=tool).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def file_search(pattern: str, path: str = "/var/log", max_results: int = 20) -> str:
    """Search files by pattern (grep)."""
    max_results = min(max_results, 100)
    r = _shell.execute(f"grep -rl '{pattern}' {path} 2>/dev/null | head -n {max_results}")
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def log_tail(log_path: str = "/var/log/syslog", lines: int = 50, pattern: str = "") -> str:
    """Tail log file with optional grep filter."""
    lines = min(lines, 200)
    cmd = f"tail -n {lines} {log_path}"
    if pattern:
        cmd += f" | grep -i '{pattern}'"
    r = _shell.execute(cmd)
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def systemd_status(service: str = "") -> str:
    """Check systemd service status."""
    cmd = f"systemctl status {service} --no-pager -l" if service else "systemctl --failed --no-pager"
    r = _shell.execute(cmd)
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def open_files(target: str = "", mode: str = "port") -> str:
    """List open files/ports (lsof/ss)."""
    if mode == "port" and target:
        cmd = f"lsof -i :{target} 2>/dev/null || ss -tlnp | grep :{target}"
    else:
        cmd = "ss -tuln"
    r = _shell.execute(cmd)
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def kernel_info() -> str:
    """Get kernel info — uname, dmesg errors."""
    uname = _shell.execute("uname -a")
    dmesg = _shell.execute("dmesg --level=err,warn 2>/dev/null | tail -20")
    return ToolResult.success({"uname": uname.stdout.strip(), "dmesg": dmesg.stdout}).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def user_sessions() -> str:
    """List active user sessions."""
    r = _shell.execute("w")
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin", command_param=None)
def cron_list() -> str:
    """List cron jobs and systemd timers."""
    cron = _shell.execute("crontab -l 2>/dev/null || echo 'no crontab'")
    timers = _shell.execute("systemctl list-timers --no-pager 2>/dev/null")
    return ToolResult.success({"crontab": cron.stdout, "timers": timers.stdout}).to_json()

# ─── T1: Low-Risk ──────────────────────────────────────────────

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="linux_admin", command_param=None)
def service_restart(service: str) -> str:
    """Restart a systemd service."""
    r = _shell.execute(f"systemctl restart {service}")
    status = _shell.execute(f"systemctl status {service} --no-pager -l")
    return ToolResult.success({"service": service, "result": "ok" if r.ok else r.stderr, "status": status.stdout}).to_json()

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="linux_admin", command_param=None)
def process_signal(pid: int, signal: str = "TERM") -> str:
    """Send signal to a process (TERM/HUP only)."""
    allowed = {"TERM", "HUP", "USR1", "USR2", "INT"}
    if signal.upper() not in allowed:
        return ToolResult.blocked(f"Signal {signal} not in {allowed}").to_json()
    r = _shell.execute(f"kill -{signal.upper()} {pid}")
    return ToolResult.success({"pid": pid, "signal": signal, "ok": r.ok}).to_json()

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="linux_admin", command_param=None)
def file_edit(path: str, content: str = "", append: bool = True) -> str:
    """Edit a config file (append or overwrite). T1 — reversible."""
    op = ">>" if append else ">"
    r = _shell.execute(f"echo '{content}' {op} {path}")
    return ToolResult.success({"path": path, "append": append, "ok": r.ok}).to_json()

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="linux_admin", command_param=None)
def package_query(package: str = "", action: str = "info") -> str:
    """Query package info (read-only)."""
    cmd = f"dpkg -s {package} 2>/dev/null || rpm -qi {package} 2>/dev/null" if package else "dpkg -l | tail -20"
    r = _shell.execute(cmd)
    return ToolResult.success(r.stdout).to_json()

# ─── T2/T3 ─────────────────────────────────────────────────────

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="linux_admin", command_param=None, dry_run_support=True)
def process_kill(pid: int, signal: int = 9, dry_run: bool = False) -> str:
    """Force-kill a process. Requires approval_token."""
    r = _shell.execute(f"kill -{signal} {pid}")
    return ToolResult.success({"pid": pid, "signal": signal, "ok": r.ok}).to_json()

@secure_tool(tier=SecurityTier.T3_DESTRUCTIVE, skill="linux_admin", command_param=None, dry_run_support=True)
def system_reboot(dry_run: bool = False) -> str:
    """Reboot the system. Requires dual approval. 🔴 T3."""
    return ToolResult.success({"action": "reboot", "status": "would_execute"}).to_json()
