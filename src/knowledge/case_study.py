"""CaseStudy model — structured record of resolved incidents.

Adapted from agenticops-chat/src/agenticops/kb/case_study.py.
Changed: dataclass → Pydantic for validation consistency with StructuredAlert.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CaseStudyStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class CaseStudyMeta(BaseModel):
    """Metadata about the incident context."""
    resource_type: str = ""
    severity: str = "medium"
    region: str = ""
    source_alert_id: Optional[str] = None
    source_rca_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list)


class Resolution(BaseModel):
    """How the incident was resolved."""
    immediate_action: str = ""
    long_term_fix: str = ""
    verification_method: str = ""


class LessonsLearned(BaseModel):
    """What we learned from this incident."""
    what_failed: str = ""
    why_missed: str = ""
    efficiency_score: float = Field(default=0.5, ge=0.0, le=1.0)


class CaseStudy(BaseModel):
    """A structured record of a resolved incident.

    Created automatically by KnowledgeFlywheel from RCA results.
    Used for similarity search during future RCA cycles.
    """

    case_id: str = ""
    title: str = ""
    meta: CaseStudyMeta = Field(default_factory=CaseStudyMeta)
    resolution: Resolution = Field(default_factory=Resolution)
    lessons_learned: LessonsLearned = Field(default_factory=LessonsLearned)

    status: CaseStudyStatus = CaseStudyStatus.PENDING_REVIEW
    verified: bool = False
    reuse_count: int = 0

    # Full text fields for search
    symptoms: str = ""
    root_cause: str = ""
    prevention: str = ""

    def model_post_init(self, __context) -> None:
        """Auto-generate case_id if not provided."""
        if not self.case_id:
            raw = f"{self.title}:{self.meta.resource_type}:{self.symptoms[:100]}"
            self.case_id = f"case-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"

    @property
    def symptom_vector_text(self) -> str:
        """Text used for symptom embedding."""
        return f"{self.title} {self.symptoms}".strip()

    @property
    def root_cause_vector_text(self) -> str:
        """Text used for root cause embedding."""
        return f"{self.root_cause} {self.resolution.immediate_action}".strip()

    def to_search_text(self) -> str:
        """Full text for keyword search."""
        return " ".join([
            self.title,
            self.symptoms,
            self.root_cause,
            self.resolution.immediate_action,
            self.resolution.long_term_fix,
            self.prevention,
        ]).strip()
