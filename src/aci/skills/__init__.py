"""
ACI Skills — Agent Skills standard implementation for AgenticAIOps.

Provides SkillLoader for discovering, loading, and registering
domain-specific SRE skills following the Agent Skills open standard
(agentskills.io).

Usage:
    from src.aci.skills import SkillLoader

    loader = SkillLoader("skills/")
    summaries = loader.discover()          # ~100 tokens/skill
    skill = loader.load("linux-admin")     # full load
    tools = skill.get_tools()              # @tool callables
"""

from .loader import SkillLoader
from .models import SkillDefinition, SkillSummary, SafetyTier

__all__ = [
    "SkillLoader",
    "SkillDefinition",
    "SkillSummary",
    "SafetyTier",
]
