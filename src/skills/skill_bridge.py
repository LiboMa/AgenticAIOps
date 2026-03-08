"""
Skills Bridge — connects Agent layer to Skills framework.

Called at application startup to initialize skills,
and by individual agents to get their tools and prompts.
"""
from __future__ import annotations

import logging
from typing import List, Callable, Optional, Dict, Any

from .agent_binding import initialize_registry, bind_skills_to_agent, get_agent_system_prompt
from . import SkillRegistry

logger = logging.getLogger(__name__)

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
