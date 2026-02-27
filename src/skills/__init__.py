"""
Skills Framework — SkillRegistry singleton.

Central registry for all operational Skills. Agents load Skills by tier
and domain, getting only the tools they're authorized to use.

Architecture: ADR-006 §5 Skill Registry
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from ._models import SecurityTier, SkillManifest
from ._security import secure_tool, SecurityViolation, GLOBAL_BLACKLIST_COMMANDS  # noqa: F401 re-export

logger = logging.getLogger(__name__)


@dataclass
class RegisteredSkill:
    """A skill registered with the SkillRegistry."""

    manifest: SkillManifest
    tools: Dict[str, Callable] = field(default_factory=dict)
    security_policy: Optional[object] = None

    def get_tools_by_tier(self, max_tier: SecurityTier) -> List[Callable]:
        """Return tools at or below the given tier."""
        result = []
        for tool_fn in self.tools.values():
            tool_tier = getattr(tool_fn, "_security_tier", SecurityTier.T0_READONLY)
            if tool_tier <= max_tier:
                result.append(tool_fn)
        return result


class SkillRegistry:
    """Singleton registry for operational Skills.

    Usage::

        registry = SkillRegistry.get()
        registry.register_skill("kubernetes", tools=[...], manifest=manifest)
        tools = registry.load_for_agent("detect", ["kubernetes"], SecurityTier.T0_READONLY)
    """

    _instance: Optional["SkillRegistry"] = None

    def __init__(self) -> None:
        self._skills: Dict[str, RegisteredSkill] = {}
        self._frozen = False

    @classmethod
    def get(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (testing only)."""
        cls._instance = None

    @classmethod
    def create_isolated(cls) -> "SkillRegistry":
        """Factory for test isolation — fresh non-singleton instance."""
        return cls()

    def register_skill(
        self,
        name: str,
        *,
        manifest: SkillManifest,
        tools: List[Callable],
        security_policy: Optional[object] = None,
    ) -> None:
        if self._frozen:
            raise RuntimeError(f"Cannot register skill '{name}' — registry is frozen")

        if name in self._skills:
            raise RuntimeError(f"Skill '{name}' is already registered")

        tool_map: Dict[str, Callable] = {}
        for tool_fn in tools:
            if not hasattr(tool_fn, "_security_tier"):
                raise ValueError(
                    f"Tool '{getattr(tool_fn, '__name__', tool_fn)}' in skill '{name}' "
                    "is not decorated with @secure_tool"
                )
            tool_name = getattr(tool_fn, "_tool_name", tool_fn.__name__)
            if tool_name in tool_map:
                raise ValueError(f"Duplicate tool name '{tool_name}' in skill '{name}'")
            tool_map[tool_name] = tool_fn

        self._skills[name] = RegisteredSkill(
            manifest=manifest, tools=tool_map, security_policy=security_policy,
        )
        logger.info("Registered skill '%s': %d tools", name, len(tool_map))

    def freeze(self) -> None:
        self._frozen = True
        total = sum(len(s.tools) for s in self._skills.values())
        logger.info("SkillRegistry frozen: %d skills, %d tools", len(self._skills), total)

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def get_skill(self, name: str) -> Optional[RegisteredSkill]:
        return self._skills.get(name)

    def list_skills(self) -> List[str]:
        return sorted(self._skills.keys())

    def load_for_agent(
        self,
        agent_id: str,
        skill_names: List[str],
        max_tier: SecurityTier,
    ) -> List[Callable]:
        tools: List[Callable] = []
        seen: Set[str] = set()

        targets = list(self._skills.keys()) if "ALL" in skill_names else skill_names

        for name in targets:
            skill = self._skills.get(name)
            if skill is None:
                logger.warning("Agent '%s' requested unknown skill '%s'", agent_id, name)
                continue
            for tool_fn in skill.get_tools_by_tier(max_tier):
                tname = getattr(tool_fn, "_tool_name", tool_fn.__name__)
                if tname not in seen:
                    tools.append(tool_fn)
                    seen.add(tname)

        logger.info(
            "Loaded %d tools for agent '%s' (max_tier=%s, skills=%s)",
            len(tools), agent_id, max_tier.name, targets,
        )
        return tools

    def can_handle(self, query: str) -> List[str]:
        """Route query to matching skills by keywords/domains."""
        scores: Dict[str, float] = {}
        q = query.lower()
        for name, skill in self._skills.items():
            score = 0.0
            m = skill.manifest
            for kw in m.keywords:
                if kw.lower() in q:
                    score += 1.0
            for d in m.domains:
                if d.lower() in q:
                    score += 0.5
            if score > 0:
                score += m.confidence_boost
                scores[name] = score
        return sorted(scores, key=lambda n: scores[n], reverse=True)
