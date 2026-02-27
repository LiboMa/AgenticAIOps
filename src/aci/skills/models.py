"""
Skill data models — SkillSummary, SkillDefinition, SafetyTier.

SkillSummary is the lightweight frontmatter-only view (~100 tokens)
used for progressive disclosure during skill discovery.

SkillDefinition is the fully-loaded skill with instructions,
tools, safety config, and references.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class SafetyTier(str, enum.Enum):
    """Skill safety classification (maps to SecurityFilter behavior)."""

    READ_ONLY = "read-only"
    """Skill only performs read/query operations."""

    GUARDED = "guarded"
    """Skill can mutate but has an allowlist + approval gate."""

    DESTRUCTIVE = "destructive"
    """Skill can perform destructive ops — requires explicit approval."""


@dataclass(frozen=True)
class SkillSummary:
    """Lightweight skill metadata from SKILL.md frontmatter.

    Designed for progressive disclosure: only ``name`` + ``description``
    are required.  Agent startup loads all summaries (~100 tokens each)
    and selects matching skills by semantic description match.
    """

    name: str
    """Unique skill identifier (lowercase + hyphens)."""

    description: str
    """What this skill does — used for semantic routing (max 1024 chars)."""

    path: Path
    """Absolute path to the skill directory."""

    version: str = "0.1.0"
    license: str = "Apache-2.0"
    author: str = "agenticaiops"

    # allowed-tools is documentary (human-readable), not runtime binding
    allowed_tools: List[str] = field(default_factory=list)

    # Optional metadata from frontmatter
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Skill name is required")
        if not self.description:
            raise ValueError("Skill description is required")
        if len(self.description) > 1024:
            raise ValueError(
                f"Skill description exceeds 1024 chars ({len(self.description)})"
            )


@dataclass
class SafetyConfig:
    """Per-skill safety configuration loaded from references/safety/ directory."""

    tier: SafetyTier = SafetyTier.READ_ONLY
    """Default safety tier for this skill."""

    requires_approval: List[str] = field(default_factory=list)
    """Operations that require explicit approval (e.g. ['delete', 'drain'])."""

    deny_by_default: bool = True
    """If True, unlisted commands are blocked (allowlist mode)."""

    command_allowlist: List[str] = field(default_factory=list)
    """Explicitly allowed commands/patterns."""

    command_blocklist: List[str] = field(default_factory=list)
    """Explicitly blocked commands/patterns (checked first)."""

    blast_radius: Dict[str, Any] = field(default_factory=dict)
    """Impact scope definitions for destructive ops."""


@dataclass
class SkillDefinition:
    """Fully-loaded skill — instructions + tools + safety + references.

    Created by ``SkillLoader.load()`` after a skill is selected.
    """

    summary: SkillSummary
    """Frontmatter metadata."""

    instructions: str
    """Full Markdown body from SKILL.md (excluding frontmatter).

    This becomes the Strands Agent system_prompt when the skill is active.
    """

    safety: SafetyConfig = field(default_factory=SafetyConfig)
    """Per-skill safety configuration."""

    _tools: List[Callable] = field(default_factory=list, repr=False)
    """Discovered @tool callables from scripts/ (or tools/)."""

    _reference_paths: List[Path] = field(default_factory=list, repr=False)
    """Paths to reference docs (loaded on demand)."""

    # ── Public API ──────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.summary.name

    @property
    def path(self) -> Path:
        return self.summary.path

    def get_tools(self) -> List[Callable]:
        """Return @tool callables for Strands Agent registration.

        Usage::

            skill = loader.load("kubernetes")
            agent = Agent(tools=skill.get_tools(), system_prompt=skill.instructions)
        """
        return list(self._tools)

    def get_reference(self, name: str) -> Optional[str]:
        """Load a reference doc by filename (lazy read).

        Args:
            name: Filename within references/ (e.g. 'TROUBLESHOOT.md')

        Returns:
            File contents as string, or None if not found.
        """
        ref_dir = self.path / "references"
        ref_path = ref_dir / name
        if ref_path.is_file():
            return ref_path.read_text(encoding="utf-8")
        return None

    def list_references(self) -> List[str]:
        """List available reference doc names."""
        ref_dir = self.path / "references"
        if ref_dir.is_dir():
            return sorted(f.name for f in ref_dir.iterdir() if f.is_file())
        return []
