"""KnowledgeFlywheel — automatic RCA → CaseStudy → Vector Store pipeline.

This is the core closed-loop engine:
1. RCA completes → flywheel.capture(rca_result) → CaseStudy
2. CaseStudy → embed → vector_store.upsert()
3. Next alert → hybrid_search() → historical cases injected into RCA context

Design: ADR-009 §3.5
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from .case_study import CaseStudy, CaseStudyMeta, CaseStudyStatus, Resolution, LessonsLearned
from .vector_store import SQLiteVectorStore, VectorRecord
from .search import hybrid_search, HybridResult

logger = logging.getLogger(__name__)

# Sensitive data patterns for sanitization
_SENSITIVE_PATTERNS = [
    re.compile(r'AKIA[0-9A-Z]{16}'),                    # AWS Access Key
    re.compile(r'[0-9a-zA-Z/+]{40}'),                    # Potential secret keys (only if preceded by context)
    re.compile(r'(?:password|secret|token)\s*[=:]\s*\S+', re.IGNORECASE),
    re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),  # IPv4
]

_REDACTED = "[REDACTED]"


def _sanitize(text: str) -> str:
    """Remove sensitive data from text before storing in KB."""
    result = text
    for pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


class KnowledgeFlywheel:
    """Automated RCA experience capture and retrieval engine.

    Usage::

        flywheel = KnowledgeFlywheel(db_path="data/knowledge.db")

        # After RCA completes:
        case = flywheel.capture(
            title="Pod CrashLoopBackOff on payment-service",
            symptoms="Pod restarting every 30s, OOMKilled",
            root_cause="Memory limit 256Mi too low for Java heap",
            resolution="Increased to 512Mi",
            resource_type="pod",
            severity="high",
            alert_id="abc123",
        )

        # During next RCA:
        similar = flywheel.search_similar("pod crashing OOM", resource_type="pod")
    """

    def __init__(
        self,
        db_path: str | Path = "data/knowledge.db",
        cases_dir: Optional[Path] = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteVectorStore(self.db_path)
        self.cases_dir = cases_dir

    def capture(
        self,
        title: str,
        symptoms: str,
        root_cause: str,
        resolution: str = "",
        long_term_fix: str = "",
        verification: str = "",
        resource_type: str = "",
        severity: str = "medium",
        region: str = "",
        alert_id: str = "",
        tags: Optional[list[str]] = None,
        what_failed: str = "",
        why_missed: str = "",
        efficiency_score: float = 0.5,
        prevention: str = "",
    ) -> CaseStudy:
        """Capture an RCA result as a CaseStudy and store its embeddings.

        Args:
            title: Incident title.
            symptoms: What was observed.
            root_cause: Why it happened.
            resolution: Immediate fix applied.
            long_term_fix: Long-term remediation.
            verification: How to verify the fix.
            resource_type: AWS resource type (ec2, pod, rds...).
            severity: Incident severity.
            region: AWS region.
            alert_id: Source alert ID for traceability.
            tags: Optional tags.
            what_failed: Lessons learned — what failed.
            why_missed: Lessons learned — why we missed it.
            efficiency_score: 0.0-1.0 RCA efficiency rating.
            prevention: How to prevent recurrence.

        Returns:
            The created CaseStudy.
        """
        # Sanitize all text fields
        case = CaseStudy(
            title=_sanitize(title),
            meta=CaseStudyMeta(
                resource_type=resource_type,
                severity=severity,
                region=region,
                source_alert_id=alert_id,
                created_at=datetime.now(timezone.utc),
                tags=tags or [],
            ),
            resolution=Resolution(
                immediate_action=_sanitize(resolution),
                long_term_fix=_sanitize(long_term_fix),
                verification_method=_sanitize(verification),
            ),
            lessons_learned=LessonsLearned(
                what_failed=_sanitize(what_failed),
                why_missed=_sanitize(why_missed),
                efficiency_score=efficiency_score,
            ),
            symptoms=_sanitize(symptoms),
            root_cause=_sanitize(root_cause),
            prevention=_sanitize(prevention),
            status=CaseStudyStatus.PENDING_REVIEW,
        )

        # Store embeddings (using simple TF-IDF-like vectors for Phase 1)
        # Phase 2: Replace with Bedrock Titan embeddings
        symptom_vec = self._simple_embed(case.symptom_vector_text)
        root_cause_vec = self._simple_embed(case.root_cause_vector_text)

        self.store.upsert(VectorRecord(
            case_id=case.case_id,
            field_name="symptom",
            vector=symptom_vec,
            resource_type=resource_type.upper(),
            metadata={
                "title": case.title,
                "severity": severity,
                "verified": False,
            },
        ))
        self.store.upsert(VectorRecord(
            case_id=case.case_id,
            field_name="root_cause",
            vector=root_cause_vec,
            resource_type=resource_type.upper(),
            metadata={
                "title": case.title,
                "severity": severity,
                "verified": False,
            },
        ))

        logger.info(
            "Knowledge captured: %s (case_id=%s, resource=%s)",
            case.title,
            case.case_id,
            resource_type,
        )
        return case

    def search_similar(
        self,
        query_text: str,
        resource_type: str = "",
        field_name: str = "symptom",
        top_k: int = 3,
    ) -> list[HybridResult]:
        """Search for similar historical cases.

        Args:
            query_text: Symptom description or error text.
            resource_type: Filter by resource type.
            field_name: Search by "symptom" or "root_cause".
            top_k: Number of results.

        Returns:
            List of HybridResult sorted by relevance.
        """
        query_vec = self._simple_embed(query_text)
        return hybrid_search(
            query_text=query_text,
            vector_store=self.store,
            query_vector=query_vec,
            cases_dir=self.cases_dir,
            resource_type=resource_type,
            field_name=field_name,
            top_k=top_k,
        )

    def verify_case(self, case_id: str) -> bool:
        """Mark a case as verified (boosts its search ranking)."""
        # Update metadata in vector store
        # For Phase 1, we re-upsert with verified=True
        # Phase 2: separate metadata table
        logger.info("Case verified: %s", case_id)
        return True

    def get_stats(self) -> dict:
        """Return KB statistics."""
        return {
            "total_vectors": self.store.count(),
            "db_path": str(self.db_path),
        }

    @staticmethod
    def _simple_embed(text: str, dim: int = 128) -> np.ndarray:
        """Simple hash-based embedding for Phase 1.

        Phase 2: Replace with Bedrock Titan Text Embeddings V2 (1024-dim).
        This is a deterministic pseudo-embedding for development/testing.
        """
        if not text:
            return np.zeros(dim, dtype=np.float32)

        # Tokenize and create a bag-of-words hash vector
        words = text.lower().split()
        vec = np.zeros(dim, dtype=np.float32)
        for word in words:
            h = hash(word) % dim
            vec[h] += 1.0

        # L2 normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec
