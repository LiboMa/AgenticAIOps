"""SkillSpecBuilder — build Harness (ACP coding agent) tasks for Skill generation.

Design: ADR-009 §8.4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .gap_detector import SkillGap

logger = logging.getLogger(__name__)


@dataclass
class HarnessTask:
    """Task description for ACP coding agent."""

    task: str
    output_dir: str
    expected_files: list[str] = field(default_factory=list)
    timeout_seconds: int = 300


class SkillSpecBuilder:
    """Convert SkillGap into Harness-executable task.

    Design: ADR-009 §8.4
    """

    SKILL_TEMPLATE_PROMPT = """You are an SRE Skills generator. Generate a new Skill based on the following incident information.

## Requirements
1. Follow agentskills.io spec
2. SKILL.md must include YAML frontmatter (name, version, tools, tier)
3. Every function in tools.py must use @secure_tool decorator
4. All tools default to tier: T0_READONLY unless write operations are explicitly needed
5. Generate corresponding test_*.py file

## Constraints (MUST NOT violate)
- DO NOT import os.system / subprocess.Popen (use ShellExecutor)
- DO NOT modify _security.py / SecurityFilter / approval_token.py
- DO NOT use eval() / exec() / __import__()
- All external commands must go through ShellExecutor.run()

## Incident Context
{incident_context}

## Existing Skills (avoid duplication)
{existing_skills}

## Detected Coverage Gap
{skill_gap}

## Output Structure
```
src/skills/{domain}/
├── SKILL.md          # Skill definition with frontmatter
├── tools.py          # @secure_tool decorated functions
└── tests/
    └── test_{domain}.py  # Unit tests
```
"""

    def __init__(self, skill_registry: Optional[Any] = None):
        self.skill_registry = skill_registry

    def build_task(self, gap: SkillGap, incident: Any = None) -> HarnessTask:
        """Build an ACP coding agent task from a SkillGap.

        Args:
            gap: Detected skill coverage gap.
            incident: Optional incident record for context.

        Returns:
            HarnessTask ready for Harness invocation.
        """
        domain = gap.suggested_skill_domain or "general"
        incident_context = self._summarize_incident(incident) if incident else "N/A"
        existing_skills = self._list_existing_skills()

        prompt = self.SKILL_TEMPLATE_PROMPT.format(
            incident_context=incident_context,
            existing_skills=existing_skills,
            skill_gap=gap.to_dict(),
            domain=domain,
        )

        return HarnessTask(
            task=prompt,
            output_dir=f"src/skills/{domain}/",
            expected_files=[
                "SKILL.md",
                "tools.py",
                f"tests/test_{domain}.py",
            ],
            timeout_seconds=300,
        )

    async def build_and_invoke(
        self, gap: SkillGap, incident: Any = None, harness_invoker: Any = None
    ) -> Optional[Any]:
        """Build task and invoke Harness.

        Args:
            gap: Detected skill coverage gap.
            incident: Incident record.
            harness_invoker: Callable that invokes the ACP coding agent.

        Returns:
            SkillDraft if Harness succeeds, None otherwise.
        """
        task = self.build_task(gap, incident)

        if not harness_invoker:
            logger.warning("No harness_invoker configured, returning task only")
            return task

        try:
            result = await harness_invoker(task)
            logger.info("Harness skill generation completed for %s", gap.suggested_skill_domain)
            return result
        except Exception as e:
            logger.error("Harness invocation failed: %s", e)
            return None

    def _summarize_incident(self, incident: Any) -> str:
        """Summarize incident for Harness context."""
        if incident is None:
            return "N/A"
        if hasattr(incident, "to_dict"):
            d = incident.to_dict()
            return f"ID: {d.get('incident_id', 'N/A')}, Service: {d.get('service', 'N/A')}, Type: {d.get('alert_type', 'N/A')}"
        return str(incident)[:500]

    def _list_existing_skills(self) -> str:
        """List existing Skills for dedup context."""
        if self.skill_registry and hasattr(self.skill_registry, "skills"):
            return ", ".join(self.skill_registry.skills.keys())
        return "kubernetes, linux_admin, network_engineer, database_admin, storage, log_analysis"
