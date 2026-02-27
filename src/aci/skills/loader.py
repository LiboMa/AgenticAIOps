"""
SkillLoader — discover, load, and register Agent Skills.

Implements the Agent Skills standard (agentskills.io) progressive
disclosure pattern:

1. ``discover()`` — scan all skills, return lightweight summaries
2. ``load()`` — fully parse a selected skill (instructions + tools + safety)
3. ``register_tools()`` — bridge to Strands Agent tool registration

Directory layout expected per skill::

    skills/<name>/
    ├── SKILL.md              # Required — YAML frontmatter + Markdown
    ├── scripts/              # Python modules with @tool functions
    │   ├── diagnose.py
    │   └── remediate.py
    ├── references/           # On-demand reference docs
    │   ├── TROUBLESHOOT.md
    │   └── DANGEROUS_OPS.md
    ├── assets/               # Static resources (templates, schemas)
    │   └── command_allowlist.yaml
    └── safety/               # SRE security extension
        ├── safety_tier.yaml
        └── blast_radius.yaml
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from .models import (
    SafetyConfig,
    SafetyTier,
    SkillDefinition,
    SkillSummary,
)

logger = logging.getLogger(__name__)

# ── YAML frontmatter regex (between --- markers) ───────────────

_FRONTMATTER_RE = re.compile(
    r"\A\s*---\s*\n(.*?)\n---\s*\n(.*)",
    re.DOTALL,
)


class SkillLoader:
    """Load and manage Agent Skills from the filesystem.

    Args:
        skills_dir: Root directory containing skill subdirectories.
    """

    def __init__(self, skills_dir: str | Path) -> None:
        self.skills_dir = Path(skills_dir).resolve()
        self._cache: Dict[str, SkillDefinition] = {}

    # ── Phase 1: Discovery (~100 tokens per skill) ─────────────

    def discover(self) -> List[SkillSummary]:
        """Scan all skill directories and return lightweight summaries.

        Only parses SKILL.md frontmatter (name + description).
        Suitable for agent startup — total context cost is low.

        Returns:
            List of SkillSummary sorted by name.
        """
        summaries: List[SkillSummary] = []
        if not self.skills_dir.is_dir():
            logger.warning("Skills directory not found: %s", self.skills_dir)
            return summaries

        for child in sorted(self.skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                summary = self._parse_frontmatter(skill_md, child)
                summaries.append(summary)
                logger.debug("Discovered skill: %s", summary.name)
            except Exception:
                logger.warning("Failed to parse skill at %s", child, exc_info=True)

        logger.info("Discovered %d skills in %s", len(summaries), self.skills_dir)
        return summaries

    # ── Phase 2: Full load ─────────────────────────────────────

    def load(self, name: str) -> SkillDefinition:
        """Fully load a skill by name.

        Parses SKILL.md body, discovers @tool functions in scripts/,
        and loads safety/ configuration.

        Args:
            name: Skill name (e.g. 'linux-admin').

        Returns:
            Fully populated SkillDefinition.

        Raises:
            FileNotFoundError: If skill directory or SKILL.md is missing.
        """
        if name in self._cache:
            return self._cache[name]

        skill_dir = self.skills_dir / name
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.is_file():
            raise FileNotFoundError(f"SKILL.md not found for skill '{name}' at {skill_md}")

        summary = self._parse_frontmatter(skill_md, skill_dir)
        instructions = self._parse_instructions(skill_md)
        tools = self._discover_tools(skill_dir / "scripts")
        safety = self._load_safety(skill_dir / "safety")
        ref_paths = self._list_references(skill_dir / "references")

        definition = SkillDefinition(
            summary=summary,
            instructions=instructions,
            safety=safety,
            _tools=tools,
            _reference_paths=ref_paths,
        )

        self._cache[name] = definition
        logger.info(
            "Loaded skill '%s': %d tools, %d references, tier=%s",
            name,
            len(tools),
            len(ref_paths),
            safety.tier.value,
        )
        return definition

    def load_all(self) -> List[SkillDefinition]:
        """Load all discovered skills (convenience for testing)."""
        return [self.load(s.name) for s in self.discover()]

    # ── Phase 3: Tool registration bridge ──────────────────────

    @staticmethod
    def register_tools(
        skill: SkillDefinition,
        agent: Any,
    ) -> None:
        """Register a skill's tools with a Strands Agent.

        This is the bridge between Agent Skills and Strands:

        .. code-block:: python

            skill = loader.load("kubernetes")
            agent = Agent(
                tools=SkillLoader.get_agent_tools(skill),
                system_prompt=skill.instructions,
            )

        Args:
            skill: Loaded SkillDefinition.
            agent: Strands Agent instance (duck-typed).
        """
        tools = skill.get_tools()
        if hasattr(agent, "tool") and callable(agent.tool):
            # Strands Agent.tool() registration
            for t in tools:
                agent.tool(t)
                logger.debug("Registered tool '%s' from skill '%s'", t.__name__, skill.name)
        else:
            logger.warning(
                "Agent does not support .tool() registration; "
                "pass tools via Agent(tools=[...]) instead"
            )

    @staticmethod
    def get_agent_tools(*skills: SkillDefinition) -> List[Callable]:
        """Collect tools from multiple skills for Agent(tools=[...]).

        Args:
            *skills: One or more loaded SkillDefinitions.

        Returns:
            Flat list of @tool callables (deduped by function name).
        """
        seen: set[str] = set()
        tools: List[Callable] = []
        for skill in skills:
            for t in skill.get_tools():
                if t.__name__ not in seen:
                    tools.append(t)
                    seen.add(t.__name__)
        return tools

    # ── Internal helpers ───────────────────────────────────────

    def _parse_frontmatter(self, skill_md: Path, skill_dir: Path) -> SkillSummary:
        """Parse YAML frontmatter from SKILL.md."""
        content = skill_md.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(content)
        if not match:
            raise ValueError(f"No YAML frontmatter found in {skill_md}")

        fm = yaml.safe_load(match.group(1)) or {}

        # Extract allowed-tools (space-delimited string → list)
        allowed_raw = fm.get("allowed-tools", "")
        allowed_tools = allowed_raw.split() if isinstance(allowed_raw, str) else []

        # Extract metadata block
        metadata = fm.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        return SkillSummary(
            name=fm.get("name", skill_dir.name),
            description=fm.get("description", ""),
            path=skill_dir.resolve(),
            version=str(metadata.get("version", fm.get("version", "0.1.0"))),
            license=fm.get("license", "Apache-2.0"),
            author=metadata.get("author", "agenticaiops"),
            allowed_tools=allowed_tools,
            metadata=metadata,
        )

    @staticmethod
    def _parse_instructions(skill_md: Path) -> str:
        """Extract Markdown body (everything after frontmatter)."""
        content = skill_md.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(content)
        if match:
            return match.group(2).strip()
        # No frontmatter — treat entire file as instructions
        return content.strip()

    @staticmethod
    def _discover_tools(scripts_dir: Path) -> List[Callable]:
        """Find all @tool-decorated functions in scripts/*.py.

        Uses importlib to dynamically load each module and inspect
        for the ``strands.tool`` marker attribute.
        """
        tools: List[Callable] = []
        if not scripts_dir.is_dir():
            return tools

        for py_file in sorted(scripts_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"skill_scripts.{py_file.stem}", py_file
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]

                for _name, obj in inspect.getmembers(module):
                    # Strands @tool wraps functions into DecoratedFunctionTool
                    if _is_strands_tool(obj):
                        tools.append(obj)
                        logger.debug("Found @tool: %s in %s", _name, py_file.name)
            except Exception:
                logger.warning("Failed to load scripts/%s", py_file.name, exc_info=True)

        return tools

    @staticmethod
    def _load_safety(safety_dir: Path) -> SafetyConfig:
        """Load safety/ configuration files."""
        config = SafetyConfig()
        if not safety_dir.is_dir():
            return config

        # safety_tier.yaml
        tier_file = safety_dir / "safety_tier.yaml"
        if tier_file.is_file():
            data = yaml.safe_load(tier_file.read_text(encoding="utf-8")) or {}
            tier_str = data.get("tier", "read-only")
            try:
                config.tier = SafetyTier(tier_str)
            except ValueError:
                logger.warning("Unknown safety tier '%s', defaulting to read-only", tier_str)
            config.requires_approval = data.get("requires_approval", [])
            config.deny_by_default = data.get("deny_by_default", True)

        # command_allowlist (can also live in assets/)
        for candidate in [
            safety_dir / "command_allowlist.yaml",
            safety_dir.parent / "assets" / "command_allowlist.yaml",
        ]:
            if candidate.is_file():
                data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
                config.command_allowlist = data.get("allow", [])
                config.command_blocklist = data.get("block", [])
                break

        # blast_radius.yaml
        blast_file = safety_dir / "blast_radius.yaml"
        if blast_file.is_file():
            config.blast_radius = yaml.safe_load(
                blast_file.read_text(encoding="utf-8")
            ) or {}

        return config

    @staticmethod
    def _list_references(ref_dir: Path) -> List[Path]:
        """List reference doc paths."""
        if not ref_dir.is_dir():
            return []
        return sorted(f for f in ref_dir.iterdir() if f.is_file())


def _is_strands_tool(func: Callable) -> bool:
    """Check if a function is decorated with @strands.tool.

    Strands @tool decorator typically sets __wrapped__ or a
    custom attribute. We check multiple indicators.
    """
    # strands.tool sets tool_name attribute
    if hasattr(func, "tool_name"):
        return True
    # Check for tool_handler attribute (Strands convention)
    if hasattr(func, "tool_handler"):
        return True
    # Fallback: check if decorated (has __wrapped__)
    if hasattr(func, "__wrapped__"):
        wrapped = func.__wrapped__
        if hasattr(wrapped, "tool_name") or hasattr(wrapped, "tool_handler"):
            return True
    return False
