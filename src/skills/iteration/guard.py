"""SkillIterationGuard — idempotency guard for skill iteration.

Design: ADR-009 §8.6
Prevents duplicate skill generation from the same gap type/domain.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .gap_detector import SkillGap

logger = logging.getLogger(__name__)


class SkillIterationGuard:
    """Prevent duplicate skill iterations.

    Dedup dimensions: (gap_type, domain, commands_hash)
    Window: 7 days (configurable)
    Max iterations per incident: 1 (Researcher recommendation)
    """

    DEDUP_WINDOW = timedelta(days=7)
    MAX_ITERATIONS_PER_INCIDENT = 1

    def __init__(self):
        self._recent_iterations: dict[str, datetime] = {}
        self._incident_counts: dict[str, int] = {}

    def should_iterate(self, gap: SkillGap) -> bool:
        """Check if this gap should trigger a new iteration.

        Args:
            gap: Detected skill gap.

        Returns:
            True if iteration should proceed, False if suppressed.
        """
        # Check per-incident limit
        if gap.incident_id:
            count = self._incident_counts.get(gap.incident_id, 0)
            if count >= self.MAX_ITERATIONS_PER_INCIDENT:
                logger.debug(
                    "Iteration suppressed: incident %s already has %d iterations",
                    gap.incident_id, count,
                )
                return False

        # Check dedup window
        key = self._make_key(gap)
        last = self._recent_iterations.get(key)
        now = datetime.now(timezone.utc)
        if last and (now - last) < self.DEDUP_WINDOW:
            logger.debug("Iteration suppressed: same gap within dedup window (%s)", key)
            return False

        return True

    def record_iteration(self, gap: SkillGap) -> None:
        """Record that an iteration was performed for this gap."""
        key = self._make_key(gap)
        self._recent_iterations[key] = datetime.now(timezone.utc)

        if gap.incident_id:
            self._incident_counts[gap.incident_id] = (
                self._incident_counts.get(gap.incident_id, 0) + 1
            )

        logger.info("Iteration recorded: %s (incident=%s)", key, gap.incident_id)

    def reset(self) -> None:
        """Clear all state (for testing)."""
        self._recent_iterations.clear()
        self._incident_counts.clear()

    @staticmethod
    def _make_key(gap: SkillGap) -> str:
        return f"{gap.gap_type}:{gap.suggested_skill_domain}:{gap.commands_hash}"
