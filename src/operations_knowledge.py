"""
Operations Knowledge Module - Compatibility Shim

DEPRECATED: This module is retained for API compatibility.
All new code should use:
  - src.knowledge_search.KnowledgeSearchService (unified search + index)
  - src.s3_knowledge_base.S3KnowledgeBase (pattern CRUD)

This shim delegates to the unified modules while maintaining
the existing api_server.py interface.

Migration ref: docs/designs/UNIFIED_PIPELINE_DESIGN.md
"""

import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# Pattern Categories (kept for API compatibility)
class PatternCategory:
    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    SECURITY = "security"
    COST = "cost"
    CONFIGURATION = "configuration"


@dataclass
class IncidentRecord:
    """Record of an incident for learning."""
    incident_id: str
    title: str
    description: str
    service: str
    severity: str
    symptoms: List[str] = field(default_factory=list)
    root_cause: str = ""
    resolution: str = ""
    resolution_steps: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    start_time: str = ""
    end_time: str = ""
    resolved_by: str = "agent"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearnedPattern:
    """A pattern learned from incidents — wraps AnomalyPattern for compatibility."""
    pattern_id: str
    title: str
    description: str
    category: str
    service: str
    severity: str
    symptoms: List[str] = field(default_factory=list)
    symptom_keywords: List[str] = field(default_factory=list)
    root_cause: str = ""
    remediation: str = ""
    remediation_steps: List[str] = field(default_factory=list)
    related_sops: List[str] = field(default_factory=list)
    related_runbooks: List[str] = field(default_factory=list)
    confidence: float = 0.7
    match_count: int = 0
    success_count: int = 0
    feedback_score: float = 0.0
    created_at: str = ""
    updated_at: str = ""
    last_matched: str = ""
    source_incidents: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LearnedPattern':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_anomaly_pattern(cls, ap) -> 'LearnedPattern':
        """Convert AnomalyPattern to LearnedPattern for compatibility."""
        return cls(
            pattern_id=ap.pattern_id,
            title=ap.title,
            description=ap.description,
            category=ap.resource_type,
            service=ap.resource_type,
            severity=ap.severity,
            symptoms=ap.symptoms,
            symptom_keywords=ap.tags,
            root_cause=ap.root_cause,
            remediation=ap.remediation,
            confidence=ap.confidence,
            created_at=ap.created_at,
            updated_at=ap.updated_at,
        )


class IncidentLearner:
    """
    Learn patterns from incidents — delegates to KnowledgeSearchService.
    """

    def __init__(self, knowledge_store):
        self.knowledge_store = knowledge_store

    def learn_from_incident(self, incident: IncidentRecord) -> Optional[LearnedPattern]:
        """Extract a pattern from a resolved incident."""
        category = self._determine_category(incident)

        pattern_id = hashlib.sha256(
            f"{incident.service}:{incident.title}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:12]

        pattern = LearnedPattern(
            pattern_id=pattern_id,
            title=f"[Auto-learned] {incident.title}",
            description=incident.description,
            category=category,
            service=incident.service,
            severity=incident.severity,
            symptoms=incident.symptoms,
            root_cause=incident.root_cause,
            remediation=incident.resolution,
            remediation_steps=incident.resolution_steps,
            confidence=0.7,
            match_count=1,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            source_incidents=[incident.incident_id],
        )

        # Persist via unified KnowledgeSearchService (S3 + OpenSearch dual-write)
        try:
            from src.s3_knowledge_base import AnomalyPattern
            from src.knowledge_search import get_knowledge_search
            import asyncio

            ap = AnomalyPattern(
                pattern_id=pattern.pattern_id,
                title=pattern.title,
                description=pattern.description,
                resource_type=pattern.service,
                severity=pattern.severity,
                symptoms=pattern.symptoms,
                root_cause=pattern.root_cause,
                remediation=pattern.remediation,
                tags=[category, "auto-learned"],
                confidence=pattern.confidence,
                source="incident_learner",
            )

            ks = get_knowledge_search()
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(ks.index(ap, quality_score=pattern.confidence))
                else:
                    loop.run_until_complete(ks.index(ap, quality_score=pattern.confidence))
            except RuntimeError:
                asyncio.run(ks.index(ap, quality_score=pattern.confidence))

            logger.info(f"Learned pattern {pattern.pattern_id} persisted via KnowledgeSearchService")
        except Exception as e:
            logger.warning(f"Failed to persist learned pattern: {e}")

        # Also save in local store
        self.knowledge_store.save_pattern(pattern)
        return pattern

    def _determine_category(self, incident: IncidentRecord) -> str:
        text = f"{incident.title} {incident.description} {incident.root_cause}".lower()
        if any(k in text for k in ['cpu', 'memory', 'latency', 'slow', 'performance']):
            return PatternCategory.PERFORMANCE
        elif any(k in text for k in ['down', 'unavailable', 'failure', 'timeout']):
            return PatternCategory.AVAILABILITY
        elif any(k in text for k in ['security', 'iam', 'permission', 'access']):
            return PatternCategory.SECURITY
        elif any(k in text for k in ['cost', 'unused', 'oversized']):
            return PatternCategory.COST
        elif any(k in text for k in ['config', 'misconfigur', 'setting']):
            return PatternCategory.CONFIGURATION
        return PatternCategory.AVAILABILITY


class PatternFeedback:
    """Handle pattern feedback — delegates to KnowledgeSearchService."""

    def __init__(self, knowledge_store):
        self.knowledge_store = knowledge_store

    def submit_feedback(self, pattern_id: str, helpful: bool, comment: str = "") -> bool:
        pattern = self.knowledge_store.get_pattern(pattern_id)
        if not pattern:
            return False

        if helpful:
            pattern.success_count += 1
            pattern.feedback_score = min(1.0, pattern.feedback_score + 0.1)
            pattern.confidence = min(0.95, pattern.confidence + 0.02)
        else:
            pattern.feedback_score = max(-1.0, pattern.feedback_score - 0.1)
            pattern.confidence = max(0.5, pattern.confidence - 0.05)

        pattern.updated_at = datetime.now(timezone.utc).isoformat()
        self.knowledge_store.save_pattern(pattern)
        logger.info(f"Feedback for {pattern_id}: helpful={helpful}")
        return True


class KnowledgeStore:
    """
    Local knowledge store — delegates persistence to S3 via s3_knowledge_base.
    """

    def __init__(self, s3_bucket: str = "agentic-aiops-knowledge-base"):
        self.s3_bucket = s3_bucket
        self.patterns: Dict[str, LearnedPattern] = {}
        self._loaded = False
        self._load_from_s3()

    def _load_from_s3(self):
        """Load patterns from S3."""
        try:
            import boto3
            s3 = boto3.client('s3')
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix='learned/'):
                for obj in page.get('Contents', []):
                    try:
                        response = s3.get_object(Bucket=self.s3_bucket, Key=obj['Key'])
                        data = json.loads(response['Body'].read().decode())
                        pattern = LearnedPattern.from_dict(data)
                        self.patterns[pattern.pattern_id] = pattern
                    except Exception as e:
                        logger.warning(f"Failed to load pattern {obj['Key']}: {e}")
            self._loaded = True
            logger.info(f"Loaded {len(self.patterns)} learned patterns from S3")
        except Exception as e:
            logger.warning(f"S3 load failed: {e}. Using empty store.")
            self._loaded = True

    def save_pattern(self, pattern: LearnedPattern) -> bool:
        self.patterns[pattern.pattern_id] = pattern
        try:
            import boto3
            s3 = boto3.client('s3')
            key = f"learned/{pattern.service}/{pattern.pattern_id}.json"
            s3.put_object(
                Bucket=self.s3_bucket,
                Key=key,
                Body=json.dumps(pattern.to_dict(), indent=2),
                ContentType='application/json',
            )
            return True
        except Exception as e:
            logger.warning(f"S3 save failed: {e}")
            return False

    def get_pattern(self, pattern_id: str) -> Optional[LearnedPattern]:
        return self.patterns.get(pattern_id)

    def search_patterns(
        self,
        service: Optional[str] = None,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        severity: Optional[str] = None,
        limit: int = 10,
    ) -> List[LearnedPattern]:
        results = []
        for pattern in self.patterns.values():
            if service and pattern.service != service:
                continue
            if category and pattern.category != category:
                continue
            if severity and pattern.severity != severity:
                continue
            score = 0
            if keywords:
                overlap = len(set(keywords) & set(pattern.symptom_keywords))
                if overlap == 0:
                    continue
                score = overlap
            else:
                score = pattern.confidence
            results.append((score, pattern))
        results.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in results[:limit]]

    def get_stats(self) -> Dict[str, Any]:
        categories = {}
        services = {}
        for p in self.patterns.values():
            categories[p.category] = categories.get(p.category, 0) + 1
            services[p.service] = services.get(p.service, 0) + 1
        return {
            "total_patterns": len(self.patterns),
            "by_category": categories,
            "by_service": services,
            "avg_confidence": sum(p.confidence for p in self.patterns.values()) / max(1, len(self.patterns)),
        }


# Singletons
_knowledge_store: Optional[KnowledgeStore] = None
_incident_learner: Optional[IncidentLearner] = None
_feedback_handler: Optional[PatternFeedback] = None


def get_knowledge_store() -> KnowledgeStore:
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = KnowledgeStore()
    return _knowledge_store


def get_incident_learner() -> IncidentLearner:
    global _incident_learner
    if _incident_learner is None:
        _incident_learner = IncidentLearner(get_knowledge_store())
    return _incident_learner


def get_feedback_handler() -> PatternFeedback:
    global _feedback_handler
    if _feedback_handler is None:
        _feedback_handler = PatternFeedback(get_knowledge_store())
    return _feedback_handler
