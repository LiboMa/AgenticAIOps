"""
Unified Knowledge Search Service

Single entry point for all knowledge retrieval and indexing.
Implements tiered search strategy:
  L1: Local cache + keyword matching (<50ms)
  L2: OpenSearch kNN vector search (<500ms)
  L3: Bedrock KB RAG (P2, <1s)

Design ref: docs/designs/UNIFIED_SEARCH_DESIGN.md
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Thresholds
L1_SUFFICIENT_SCORE = 0.85
L2_SUFFICIENT_SCORE = 0.70
QUALITY_GATE_MIN = 0.70


@dataclass
class SearchHit:
    """Single search result."""
    pattern_id: str
    title: str
    description: str
    score: float            # 0.0 - 1.0 normalized
    source: str             # "local_cache" | "opensearch" | "bedrock_kb"
    search_level: str       # "L1" | "L2" | "L3"
    content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Unified search result set."""
    query: str
    hits: List[SearchHit]
    strategy_used: str      # "fast" | "semantic" | "deep" | "auto"
    levels_tried: List[str]  # ["L1", "L2", ...]
    duration_ms: float
    total_hits: int

    @property
    def best_hit(self) -> Optional[SearchHit]:
        return self.hits[0] if self.hits else None

    @property
    def has_high_confidence(self) -> bool:
        return any(h.score >= L1_SUFFICIENT_SCORE for h in self.hits)


class KnowledgeSearchService:
    """
    Unified knowledge search and indexing service.

    Wraps L1 (s3_knowledge_base), L2 (vector_search), L3 (pattern_rag)
    behind a single interface with tiered search strategy.
    """

    def __init__(self):
        self._s3_kb = None
        self._vector_search = None
        self._pattern_rag = None

    @property
    def s3_kb(self):
        """Lazy-init S3 Knowledge Base (L1)."""
        if self._s3_kb is None:
            from src.s3_knowledge_base import S3KnowledgeBase
            self._s3_kb = S3KnowledgeBase()
        return self._s3_kb

    @property
    def vector_search(self):
        """Lazy-init OpenSearch vector search (L2)."""
        if self._vector_search is None:
            from src.vector_search import get_vector_search
            self._vector_search = get_vector_search()
        return self._vector_search

    @property
    def pattern_rag(self):
        """Lazy-init Bedrock KB RAG (L3). May be None if not configured."""
        return self._pattern_rag

    def set_pattern_rag(self, rag):
        """Inject PatternRAG instance (P2 stage)."""
        self._pattern_rag = rag

    async def search(
        self,
        query: str,
        strategy: str = "auto",
        doc_type: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 5,
        min_score: float = 0.5,
    ) -> SearchResult:
        """
        Unified search interface with tiered strategy.

        Args:
            query: Search text
            strategy: "fast" (L1 only) | "semantic" (L1+L2) | "deep" (L1+L2+L3) | "auto"
            doc_type: Filter by type (pattern/sop/runbook)
            service: Filter by AWS service
            limit: Max results
            min_score: Minimum score threshold

        Returns:
            SearchResult with hits sorted by score
        """
        start = time.time()
        all_hits: List[SearchHit] = []
        levels_tried: List[str] = []

        # L1: Local cache + keyword matching
        l1_hits = await self._search_l1(query, service, limit)
        all_hits.extend(l1_hits)
        levels_tried.append("L1")

        best_score = max((h.score for h in all_hits), default=0.0)

        if strategy == "fast" or (strategy == "auto" and best_score >= L1_SUFFICIENT_SCORE):
            return self._build_result(query, all_hits, strategy, levels_tried, start, min_score, limit)

        # L2: OpenSearch semantic search
        l2_hits = self._search_l2(query, doc_type, service, limit)
        all_hits.extend(l2_hits)
        levels_tried.append("L2")

        best_score = max((h.score for h in all_hits), default=0.0)

        if strategy == "semantic" or (strategy == "auto" and best_score >= L2_SUFFICIENT_SCORE):
            return self._build_result(query, all_hits, strategy, levels_tried, start, min_score, limit)

        # L3: Bedrock KB RAG (P2 — only if configured)
        if strategy in ("deep", "auto") and self.pattern_rag is not None:
            l3_hits = self._search_l3(query, limit)
            all_hits.extend(l3_hits)
            levels_tried.append("L3")

        return self._build_result(query, all_hits, strategy, levels_tried, start, min_score, limit)

    async def index(self, pattern, quality_score: float) -> bool:
        """
        Unified indexing — dual-write S3 + OpenSearch.

        Uses s3_knowledge_base.add_pattern() which already does dual-write
        (implemented in P0-3). This method is the public API entry point.
        """
        if quality_score < QUALITY_GATE_MIN:
            logger.info(f"Pattern rejected: quality {quality_score} < {QUALITY_GATE_MIN}")
            return False

        return await self.s3_kb.add_pattern(pattern, quality_score)

    async def rebuild_index(self) -> Dict[str, Any]:
        """Rebuild OpenSearch index from S3 (authority source)."""
        if not self.s3_kb._cache_loaded:
            await self.s3_kb._load_cache()

        indexed = 0
        failed = 0
        for pattern in self.s3_kb._local_cache.values():
            try:
                ok = self.vector_search.index_knowledge(
                    doc_id=pattern.pattern_id,
                    title=pattern.title,
                    description=pattern.description,
                    content=f"{pattern.root_cause}\n{pattern.remediation}\n{' '.join(pattern.symptoms)}",
                    doc_type="pattern",
                    category=pattern.resource_type,
                    service=pattern.resource_type,
                    severity=pattern.severity,
                    tags=pattern.tags,
                )
                if ok:
                    indexed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.warning(f"Failed to index {pattern.pattern_id}: {e}")
                failed += 1

        return {"indexed": indexed, "failed": failed, "total": indexed + failed}

    def get_stats(self) -> Dict[str, Any]:
        """Unified statistics."""
        stats = {"levels": {}}

        # L1 stats
        try:
            stats["levels"]["L1"] = self.s3_kb.get_stats()
        except Exception:
            stats["levels"]["L1"] = {"error": "unavailable"}

        # L2 stats
        try:
            stats["levels"]["L2"] = self.vector_search.get_stats()
        except Exception:
            stats["levels"]["L2"] = {"error": "unavailable"}

        # L3 stats
        stats["levels"]["L3"] = {"status": "configured" if self.pattern_rag else "not_configured"}

        return stats

    # =========================================================================
    # Internal search methods
    # =========================================================================

    async def _search_l1(
        self, query: str, service: Optional[str], limit: int
    ) -> List[SearchHit]:
        """L1: Local cache + keyword matching."""
        try:
            keywords = query.split()[:5]  # First 5 words as keywords
            patterns = await self.s3_kb.search_patterns(
                resource_type=service,
                keywords=keywords,
                limit=limit,
            )

            hits = []
            for pattern in patterns:
                # Calculate keyword match score
                query_lower = query.lower()
                match_text = f"{pattern.title} {pattern.description} {' '.join(pattern.symptoms)} {pattern.root_cause}"
                match_text_lower = match_text.lower()

                matched_words = sum(1 for w in keywords if w.lower() in match_text_lower)
                score = (matched_words / max(len(keywords), 1)) * pattern.confidence

                hits.append(SearchHit(
                    pattern_id=pattern.pattern_id,
                    title=pattern.title,
                    description=pattern.description,
                    score=min(score, 1.0),
                    source="local_cache",
                    search_level="L1",
                    content=pattern.root_cause,
                    metadata={
                        "service": pattern.resource_type,
                        "severity": pattern.severity,
                        "remediation": pattern.remediation,
                    },
                ))

            # Sort by score descending
            hits.sort(key=lambda h: h.score, reverse=True)
            return hits[:limit]

        except Exception as e:
            logger.warning(f"L1 search failed: {e}")
            return []

    def _search_l2(
        self, query: str, doc_type: Optional[str], service: Optional[str], limit: int
    ) -> List[SearchHit]:
        """L2: OpenSearch semantic search."""
        try:
            if not self.vector_search._initialized:
                logger.debug("L2 (OpenSearch) not initialized, skipping")
                return []

            results = self.vector_search.semantic_search(
                query=query,
                doc_type=doc_type,
                service=service,
                limit=limit,
            )

            hits = []
            for r in results:
                hits.append(SearchHit(
                    pattern_id=r.get("id", ""),
                    title=r.get("title", ""),
                    description=r.get("description", ""),
                    score=min(r.get("score", 0.0), 1.0),
                    source="opensearch",
                    search_level="L2",
                    content=r.get("description", ""),
                    metadata={
                        "service": r.get("service", ""),
                        "category": r.get("category", ""),
                    },
                ))

            return hits

        except Exception as e:
            logger.warning(f"L2 search failed: {e}")
            return []

    def _search_l3(self, query: str, limit: int) -> List[SearchHit]:
        """L3: Bedrock KB RAG search (P2)."""
        try:
            if self.pattern_rag is None:
                return []

            results = self.pattern_rag.search(query, max_results=limit)

            hits = []
            for r in results:
                hits.append(SearchHit(
                    pattern_id=r.get("source", "").split("/")[-1].replace(".json", ""),
                    title="",
                    description=r.get("content", "")[:200],
                    score=min(r.get("score", 0.0), 1.0),
                    source="bedrock_kb",
                    search_level="L3",
                    content=r.get("content", ""),
                    metadata=r.get("metadata", {}),
                ))

            return hits

        except Exception as e:
            logger.warning(f"L3 search failed: {e}")
            return []

    def _build_result(
        self,
        query: str,
        hits: List[SearchHit],
        strategy: str,
        levels_tried: List[str],
        start_time: float,
        min_score: float,
        limit: int,
    ) -> SearchResult:
        """Build final SearchResult with dedup and filtering."""
        # Deduplicate by pattern_id (keep highest score)
        seen = {}
        for h in hits:
            key = h.pattern_id
            if key and (key not in seen or h.score > seen[key].score):
                seen[key] = h

        # Filter by min_score, sort by score
        filtered = sorted(
            [h for h in seen.values() if h.score >= min_score],
            key=lambda h: h.score,
            reverse=True,
        )[:limit]

        duration_ms = (time.time() - start_time) * 1000

        return SearchResult(
            query=query,
            hits=filtered,
            strategy_used=strategy,
            levels_tried=levels_tried,
            duration_ms=round(duration_ms, 1),
            total_hits=len(filtered),
        )


# Singleton
_service: Optional[KnowledgeSearchService] = None


def get_knowledge_search() -> KnowledgeSearchService:
    """Get or create the singleton KnowledgeSearchService."""
    global _service
    if _service is None:
        _service = KnowledgeSearchService()
    return _service


# =============================================================================
# Legacy Compatibility Layer (migrated from operations_knowledge.py)
# =============================================================================
# These classes support api_server.py endpoints for incident learning,
# pattern feedback, and knowledge store CRUD. They persist to S3.

import json
import hashlib
from datetime import datetime, timezone


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
        from dataclasses import asdict
        return asdict(self)


@dataclass
class LearnedPattern:
    """A pattern learned from incidents."""
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
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LearnedPattern':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_anomaly_pattern(cls, ap) -> 'LearnedPattern':
        return cls(
            pattern_id=ap.pattern_id, title=ap.title, description=ap.description,
            category=ap.resource_type, service=ap.resource_type, severity=ap.severity,
            symptoms=ap.symptoms, symptom_keywords=ap.tags, root_cause=ap.root_cause,
            remediation=ap.remediation, confidence=ap.confidence,
            created_at=ap.created_at, updated_at=ap.updated_at,
        )


class IncidentLearner:
    """Learn patterns from incidents — delegates to KnowledgeSearchService."""

    def __init__(self, knowledge_store):
        self.knowledge_store = knowledge_store

    def learn_from_incident(self, incident: IncidentRecord) -> Optional[LearnedPattern]:
        category = self._determine_category(incident)
        pattern_id = hashlib.sha256(
            f"{incident.service}:{incident.title}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:12]

        pattern = LearnedPattern(
            pattern_id=pattern_id,
            title=f"[Auto-learned] {incident.title}",
            description=incident.description,
            category=category, service=incident.service, severity=incident.severity,
            symptoms=incident.symptoms, root_cause=incident.root_cause,
            remediation=incident.resolution, remediation_steps=incident.resolution_steps,
            confidence=0.7, match_count=1,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            source_incidents=[incident.incident_id],
        )

        try:
            from src.s3_knowledge_base import AnomalyPattern
            import asyncio

            ap = AnomalyPattern(
                pattern_id=pattern.pattern_id, title=pattern.title,
                description=pattern.description, resource_type=pattern.service,
                severity=pattern.severity, symptoms=pattern.symptoms,
                root_cause=pattern.root_cause, remediation=pattern.remediation,
                tags=[category, "auto-learned"], confidence=pattern.confidence,
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
    """Handle pattern feedback."""

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
    """Local knowledge store with S3 persistence."""

    def __init__(self, s3_bucket: str = "agentic-aiops-knowledge-base"):
        self.s3_bucket = s3_bucket
        self.patterns: Dict[str, LearnedPattern] = {}
        self._loaded = False
        self._load_from_s3()

    def _load_from_s3(self):
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
                Bucket=self.s3_bucket, Key=key,
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
        self, service: Optional[str] = None, category: Optional[str] = None,
        keywords: Optional[List[str]] = None, severity: Optional[str] = None,
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
        categories: Dict[str, int] = {}
        services: Dict[str, int] = {}
        for p in self.patterns.values():
            categories[p.category] = categories.get(p.category, 0) + 1
            services[p.service] = services.get(p.service, 0) + 1
        return {
            "total_patterns": len(self.patterns),
            "by_category": categories,
            "by_service": services,
            "avg_confidence": sum(p.confidence for p in self.patterns.values()) / max(1, len(self.patterns)),
        }


# Legacy singletons
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
