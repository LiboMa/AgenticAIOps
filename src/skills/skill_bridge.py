"""
Skills Bridge — connects Agent layer to Skills framework.

Called at application startup to initialize skills,
and by individual agents to get their tools and prompts.

Includes SkillBridge class for context-aware tool loading (ADR-009 §3.4).
"""
from __future__ import annotations

import logging
from typing import List, Callable, Optional, Dict, Any

from .agent_binding import (
    initialize_registry, bind_skills_to_agent, get_agent_system_prompt,
    AGENT_TIER_BINDINGS,
)
from ._models import SecurityTier
from . import SkillRegistry

logger = logging.getLogger(__name__)

# ── Context-aware skill routing (from Architect ADR-009 §3.4) ──

_CONTEXT_TO_SKILLS: Dict[str, List[str]] = {
    # Resource types → relevant skill domains
    "eks": ["kubernetes", "monitoring", "log_analysis"],
    "pod": ["kubernetes", "monitoring", "log_analysis"],
    "node": ["kubernetes", "linux_admin", "monitoring"],
    "ec2": ["aws_general", "linux_admin", "monitoring"],
    "rds": ["database_admin", "aws_general", "monitoring"],
    "lambda": ["aws_general", "monitoring", "log_analysis"],
    "s3": ["storage", "aws_general"],
    "vpc": ["network_engineer", "aws_general"],
    "elb": ["network_engineer", "aws_general", "monitoring"],
    "ecs": ["aws_general", "monitoring", "log_analysis"],
    # Alert types → relevant skill domains
    "pod_crash": ["kubernetes", "log_analysis"],
    "high_cpu": ["monitoring", "linux_admin"],
    "high_memory": ["monitoring", "linux_admin"],
    "disk_pressure": ["linux_admin", "monitoring"],
    "network_issue": ["network_engineer", "monitoring"],
    "database_slow": ["database_admin", "monitoring"],
    "certificate_expiry": ["network_engineer", "aws_general"],
}

MAX_TOOLS_PER_INVOCATION = 50

_initialized = False


def ensure_initialized() -> SkillRegistry:
    """Initialize skill registry (idempotent)."""
    global _initialized
    registry = SkillRegistry.get()
    if not _initialized:
        initialize_registry(registry)
        _initialized = True
        logger.info("Skills framework initialized: %d skills", len(registry.list_skills()))
    return registry


def get_detect_tools() -> List[Callable]:
    """Get T0 read-only tools for Detect Agent."""
    ensure_initialized()
    return bind_skills_to_agent("detect")


def get_rca_tools() -> List[Callable]:
    """Get T0+T1 tools for RCA Agent."""
    ensure_initialized()
    return bind_skills_to_agent("rca")


def get_sre_tools() -> List[Callable]:
    """Get all-tier tools for SRE Agent."""
    ensure_initialized()
    return bind_skills_to_agent("sre")


def get_detect_prompt() -> str:
    """Get system prompt for Detect Agent."""
    ensure_initialized()
    return get_agent_system_prompt("detect")


def get_rca_prompt() -> str:
    """Get system prompt for RCA Agent."""
    ensure_initialized()
    return get_agent_system_prompt("rca")


def get_sre_prompt() -> str:
    """Get system prompt for SRE Agent."""
    ensure_initialized()
    return get_agent_system_prompt("sre")


def execute_skill_tool(tool_name: str, agent_role: str = "detect", **kwargs) -> str:
    """Execute a specific skill tool by name.

    Args:
        tool_name: Name of the tool function
        agent_role: Agent role for tier checking
        **kwargs: Tool parameters

    Returns:
        JSON string result from the tool
    """
    ensure_initialized()
    tools = bind_skills_to_agent(agent_role)
    for tool in tools:
        if getattr(tool, '_tool_name', None) == tool_name:
            return tool(**kwargs)
    from ._models import ToolResult
    return ToolResult.fail(f"Tool '{tool_name}' not found for role '{agent_role}'").to_json()


def list_available_tools(agent_role: str = "detect") -> List[Dict[str, Any]]:
    """List available tools for a role with metadata."""
    ensure_initialized()
    tools = bind_skills_to_agent(agent_role)
    return [
        {
            "name": getattr(t, '_tool_name', t.__name__),
            "skill": getattr(t, '_skill_name', 'unknown'),
            "tier": getattr(t, '_security_tier', 0).name if hasattr(getattr(t, '_security_tier', 0), 'name') else str(getattr(t, '_security_tier', 0)),
            "doc": (t.__doc__ or "").split("\n")[0].strip(),
        }
        for t in tools
    ]


def reset_bridge() -> None:
    """Reset initialization state (testing only)."""
    global _initialized
    _initialized = False


# ── Context-aware SkillBridge class (Architect ADR-009 §3.4) ──

class SkillBridge:
    """Context-aware skill loading for Agents.

    Selects relevant Skills based on resource_type/alert_type context,
    rather than loading all tools.

    Usage::

        bridge = SkillBridge("detect")
        tools = bridge.load_for_context({"resource_type": "eks", "alert_type": "pod_crash"})
    """

    def __init__(self, agent_name: str):
        ensure_initialized()
        self.agent_name = agent_name
        self.registry = SkillRegistry.get()
        self.max_tier = AGENT_TIER_BINDINGS.get(
            agent_name, SecurityTier.T0_READONLY
        )

    def load_for_context(self, context: dict) -> List[Callable]:
        """Load relevant Skills tools based on alert/detection context."""
        relevant_domains = self._resolve_domains(context)
        tools: List[Callable] = []
        loaded_skills: List[str] = []

        for domain in relevant_domains:
            skill = self.registry.get_skill(domain)
            if skill is None:
                continue
            domain_tools = skill.get_tools_by_tier(self.max_tier)
            tools.extend(domain_tools)
            loaded_skills.append(domain)
            if len(tools) >= MAX_TOOLS_PER_INVOCATION:
                break

        tools = tools[:MAX_TOOLS_PER_INVOCATION]
        logger.info(
            "SkillBridge loaded %d tools from %s for context %s",
            len(tools), loaded_skills,
            {k: v for k, v in context.items() if k in ("resource_type", "alert_type")},
        )
        return tools

    def _resolve_domains(self, context: dict) -> List[str]:
        """Resolve context to a prioritized list of Skill domains."""
        domains: List[str] = []
        seen: set = set()

        for key_field in ("resource_type", "alert_type"):
            value = context.get(key_field, "").lower()
            for key, skill_domains in _CONTEXT_TO_SKILLS.items():
                if key == value:
                    for d in skill_domains:
                        if d not in seen:
                            domains.append(d)
                            seen.add(d)

        if "monitoring" not in seen:
            domains.append("monitoring")
        return domains

    def get_available_skills(self) -> List[str]:
        """List all registered skill domains."""
        return self.registry.list_skills()

    def get_tools_count(self) -> int:
        """Count total tools available at this agent's tier."""
        total = 0
        for name in self.registry.list_skills():
            skill = self.registry.get_skill(name)
            if skill:
                total += len(skill.get_tools_by_tier(self.max_tier))
        return total
