"""
Skills Framework — Agent-Skill Binding.

Binds Skills to Agents by role and tier.
Detect=T0(read-only), RCA=T1(+low-risk), SRE=T3(all).

Architecture: ADR-006 §6 Tool Routing & Agent Integration
"""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Callable, Dict, List, Optional

from ._models import SecurityTier, SkillManifest
from . import SkillRegistry

logger = logging.getLogger(__name__)

# Agent role → max tier binding
AGENT_TIER_BINDINGS: Dict[str, SecurityTier] = {
    "detect": SecurityTier.T0_READONLY,
    "rca": SecurityTier.T1_LOW_RISK,
    "sre": SecurityTier.T3_DESTRUCTIVE,
}

# All skill module paths
SKILL_MODULES = {
    "kubernetes": "src.skills.kubernetes.tools",
    "linux_admin": "src.skills.linux_admin.tools",
    "network_engineer": "src.skills.network_engineer.tools",
    "aws_general": "src.skills.aws_general.tools",
    "database_admin": "src.skills.database_admin.tools",
    "monitoring": "src.skills.monitoring.tools",
    "log_analysis": "src.skills.log_analysis.tools",
    "storage": "src.skills.storage.tools",
}


def _discover_tools(module_path: str) -> List[Callable]:
    """Import module and return all @secure_tool decorated functions."""
    mod = importlib.import_module(module_path)
    return [
        obj for _, obj in inspect.getmembers(mod)
        if hasattr(obj, "_security_tier") and hasattr(obj, "_tool_name")
    ]


def initialize_registry(registry: Optional[SkillRegistry] = None) -> SkillRegistry:
    """Register all 8 skills with the registry.

    Call once at application startup.

    Args:
        registry: Optional registry instance (uses singleton if None).

    Returns:
        Initialized SkillRegistry.
    """
    if registry is None:
        registry = SkillRegistry.get()

    for name, mod_path in SKILL_MODULES.items():
        if registry.get_skill(name) is not None:
            continue  # Already registered
        try:
            tools = _discover_tools(mod_path)
            manifest = SkillManifest(
                name=name,
                description=f"{name.replace('_', ' ').title()} operational skill",
                domains=[name],
                keywords=_skill_keywords(name),
            )
            registry.register_skill(name, manifest=manifest, tools=tools)
        except Exception:
            logger.warning("Failed to register skill '%s'", name, exc_info=True)

    return registry


def bind_skills_to_agent(
    agent_role: str,
    skill_names: Optional[List[str]] = None,
    registry: Optional[SkillRegistry] = None,
) -> List[Callable]:
    """Get tools for an agent role, filtered by tier.

    Args:
        agent_role: "detect", "rca", or "sre"
        skill_names: Specific skills to load (default: all)
        registry: Optional registry (uses singleton if None)

    Returns:
        List of @secure_tool decorated callables.
    """
    if registry is None:
        registry = SkillRegistry.get()

    max_tier = AGENT_TIER_BINDINGS.get(agent_role, SecurityTier.T0_READONLY)

    if skill_names is None:
        skill_names = ["ALL"]

    from ._security import set_agent_context
    set_agent_context(agent_role, max_tier)

    tools = registry.load_for_agent(agent_role, skill_names, max_tier)
    logger.info(
        "Bound %d tools to agent '%s' (tier=%s)",
        len(tools), agent_role, max_tier.name,
    )
    return tools


def get_agent_system_prompt(agent_role: str) -> str:
    """Generate a system prompt section describing available skills.

    Injected into the Agent's system prompt so it knows what tools are available.
    """
    max_tier = AGENT_TIER_BINDINGS.get(agent_role, SecurityTier.T0_READONLY)

    lines = [
        f"## Available Skills (Role: {agent_role}, Max Tier: {max_tier.name})",
        "",
    ]

    registry = SkillRegistry.get()
    for name in registry.list_skills():
        skill = registry.get_skill(name)
        if skill is None:
            continue

        tier_tools = skill.get_tools_by_tier(max_tier)
        if not tier_tools:
            continue

        lines.append(f"### {name} ({len(tier_tools)} tools)")
        for t in tier_tools:
            tier_label = t._security_tier.name
            doc = (t.__doc__ or "").split("\n")[0].strip()
            lines.append(f"- `{t._tool_name}` [{tier_label}]: {doc}")
        lines.append("")

    return "\n".join(lines)


def _skill_keywords(name: str) -> List[str]:
    """Default keywords for each skill."""
    return {
        "kubernetes": ["pod", "kubectl", "deployment", "node", "k8s", "container", "namespace", "service"],
        "linux_admin": ["process", "cpu", "memory", "disk", "linux", "systemd", "log", "kernel"],
        "network_engineer": ["ping", "traceroute", "dns", "network", "iptables", "route", "port", "tcp"],
        "aws_general": ["ec2", "rds", "lambda", "s3", "ecs", "eks", "asg", "cloudwatch", "aws"],
        "database_admin": ["rds", "dynamodb", "elasticache", "aurora", "database", "db", "query"],
        "monitoring": ["alarm", "metric", "prometheus", "grafana", "cloudwatch", "alert"],
        "log_analysis": ["log", "syslog", "journalctl", "cloudwatch logs", "error rate"],
        "storage": ["s3", "ebs", "efs", "disk", "volume", "snapshot", "bucket"],
    }.get(name, [name])
