"""Network Engineer Skill — 14 tools (CCIE-level networking)."""
from __future__ import annotations
from .._security import secure_tool
from .._models import SecurityTier, ToolResult
from .._executor import ShellExecutor

_shell = ShellExecutor(timeout=30)

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def ping_host(target: str, count: int = 4) -> str:
    """Ping a host to check reachability."""
    count = min(count, 20)
    r = _shell.execute(f"ping -c {count} -W 2 {target}", timeout=15)
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def traceroute(target: str) -> str:
    """Trace route to target host."""
    r = _shell.execute(f"traceroute -m 20 -w 2 {target}", timeout=30)
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def dns_lookup(domain: str, record_type: str = "A") -> str:
    """DNS lookup (dig/nslookup)."""
    r = _shell.execute(f"dig {domain} {record_type} +short")
    full = _shell.execute(f"dig {domain} {record_type}")
    return ToolResult.success({"short": r.stdout.strip(), "full": full.stdout}).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def port_scan(target: str, ports: str = "22,80,443") -> str:
    """Check if ports are open on a target (nc-based)."""
    results = {}
    for port in ports.split(",")[:20]:
        p = port.strip()
        r = _shell.execute(f"nc -zv -w2 {target} {p} 2>&1", timeout=5)
        results[p] = "open" if r.ok else "closed"
    return ToolResult.success(results).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def network_interfaces() -> str:
    """List network interfaces with IP addresses."""
    r = _shell.execute("ip addr show")
    routes = _shell.execute("ip route show")
    return ToolResult.success({"interfaces": r.stdout, "routes": routes.stdout}).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def arp_table() -> str:
    """Show ARP table."""
    r = _shell.execute("ip neigh show || arp -a")
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def connection_stats() -> str:
    """Show TCP/UDP connection statistics."""
    r = _shell.execute("ss -s")
    conns = _shell.execute("ss -tuln")
    return ToolResult.success({"summary": r.stdout, "listening": conns.stdout}).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def mtr_report(target: str) -> str:
    """MTR network diagnostic report."""
    r = _shell.execute(f"mtr -r -c 5 {target} 2>/dev/null || traceroute {target}", timeout=30)
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def iptables_list() -> str:
    """List iptables/nftables rules (read-only)."""
    r = _shell.execute("iptables -L -n -v 2>/dev/null || nft list ruleset 2>/dev/null || echo 'no firewall rules'")
    return ToolResult.success(r.stdout).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer", command_param=None)
def bandwidth_test() -> str:
    """Check network bandwidth stats."""
    r = _shell.execute("cat /proc/net/dev")
    return ToolResult.success(r.stdout).to_json()

# T1

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="network_engineer", command_param=None)
def flush_dns() -> str:
    """Flush DNS cache."""
    r = _shell.execute("systemd-resolve --flush-caches 2>/dev/null || echo 'no systemd-resolved'")
    return ToolResult.success(r.stdout.strip()).to_json()

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="network_engineer", command_param=None)
def restart_network_service(service: str = "systemd-networkd") -> str:
    """Restart networking service."""
    r = _shell.execute(f"systemctl restart {service}")
    return ToolResult.success({"service": service, "ok": r.ok}).to_json()

# T2

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="network_engineer", command_param=None, dry_run_support=True)
def modify_iptables(action: str = "list", rule: str = "", dry_run: bool = False) -> str:
    """Modify iptables rules. Requires approval_token."""
    if action == "list":
        r = _shell.execute("iptables -L -n -v")
    else:
        r = _shell.execute(f"iptables {rule}")
    return ToolResult.success({"action": action, "output": r.stdout, "ok": r.ok}).to_json()

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="network_engineer", command_param=None, dry_run_support=True)
def modify_route(action: str = "show", route: str = "", dry_run: bool = False) -> str:
    """Modify routing table. Requires approval_token."""
    if action == "show":
        r = _shell.execute("ip route show")
    else:
        r = _shell.execute(f"ip route {action} {route}")
    return ToolResult.success({"action": action, "output": r.stdout, "ok": r.ok}).to_json()
