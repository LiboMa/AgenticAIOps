"""Coverage tests for src/knowledge_search.py — targeting 38% → 90%+."""
import pytest
import asyncio
import json
import hashlib
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime, timezone
from dataclasses import asdict

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.knowledge_search import (
    SearchHit, SearchResult, KnowledgeSearchService,
    get_knowledge_search,
    PatternCategory, IncidentRecord, LearnedPattern,
    IncidentLearner, PatternFeedback, KnowledgeStore,
    get_knowledge_store, get_incident_learner, get_feedback_handler,
    L1_SUFFICIENT_SCORE, L2_SUFFICIENT_SCORE, QUALITY_GATE_MIN,
)


# ── Fixtures ──

@pytest.fixture
def service():
    """Fresh KnowledgeSearchService with mocked backends."""
    svc = KnowledgeSearchService()
    svc._s3_kb = MagicMock()
    svc._vector_search = MagicMock()
    svc._pattern_rag = None
    return svc


@pytest.fixture
def mock_pattern():
    """Mock AnomalyPattern-like object."""
    p = MagicMock()
    p.pattern_id = "pat-001"
    p.title = "High CPU on EKS pods"
    p.description = "CPU usage exceeds 90%"
    p.symptoms = ["high cpu", "pod restart"]
    p.root_cause = "Resource limits too low"
    p.remediation = "Increase CPU limits"
    p.resource_type = "eks"
    p.severity = "high"
    p.tags = ["cpu", "eks"]
    p.confidence = 0.9
    return p


@pytest.fixture
def sample_incident():
    return IncidentRecord(
        incident_id="inc-001",
        title="High CPU on EKS",
        description="CPU usage exceeds 90% on production pods",
        service="eks",
        severity="high",
        symptoms=["high cpu", "pod restart"],
        root_cause="Resource limits too low",
        resolution="Increased CPU limits",
        resolution_steps=["kubectl edit deployment", "set cpu limit to 2000m"],
    )


@pytest.fixture
def sample_pattern():
    return LearnedPattern(
        pattern_id="lp-001",
        title="Test Pattern",
        description="A test pattern",
        category="performance",
        service="eks",
        severity="high",
        symptoms=["slow response"],
        symptom_keywords=["slow", "timeout"],
        root_cause="Overloaded",
        remediation="Scale up",
        confidence=0.8,
        match_count=5,
        success_count=3,
        feedback_score=0.5,
        created_at="2026-03-01T00:00:00Z",
        updated_at="2026-03-09T00:00:00Z",
    )


# ══════════════════════════════════════════════════════════════════════
# SearchHit / SearchResult dataclass tests
# ══════════════════════════════════════════════════════════════════════

class TestSearchHitSearchResult:
    def test_search_hit_defaults(self):
        h = SearchHit(pattern_id="p1", title="T", description="D",
                      score=0.8, source="local_cache", search_level="L1")
        assert h.content is None
        assert h.metadata == {}

    def test_search_result_best_hit_empty(self):
        r = SearchResult(query="q", hits=[], strategy_used="auto",
                         levels_tried=["L1"], duration_ms=1.0, total_hits=0)
        assert r.best_hit is None
        assert r.has_high_confidence is False

    def test_search_result_best_hit_present(self):
        h = SearchHit(pattern_id="p1", title="T", description="D",
                      score=0.9, source="local_cache", search_level="L1")
        r = SearchResult(query="q", hits=[h], strategy_used="auto",
                         levels_tried=["L1"], duration_ms=1.0, total_hits=1)
        assert r.best_hit == h
        assert r.has_high_confidence is True

    def test_search_result_no_high_confidence(self):
        h = SearchHit(pattern_id="p1", title="T", description="D",
                      score=0.5, source="local_cache", search_level="L1")
        r = SearchResult(query="q", hits=[h], strategy_used="auto",
                         levels_tried=["L1"], duration_ms=1.0, total_hits=1)
        assert r.has_high_confidence is False


# ══════════════════════════════════════════════════════════════════════
# KnowledgeSearchService — search() method
# ══════════════════════════════════════════════════════════════════════

class TestKnowledgeSearchServiceSearch:
    @pytest.mark.asyncio
    async def test_search_fast_strategy(self, service, mock_pattern):
        """Fast strategy only uses L1."""
        mock_pattern.confidence = 0.9
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])

        result = await service.search("high cpu eks", strategy="fast")
        assert "L1" in result.levels_tried
        assert "L2" not in result.levels_tried
        assert result.strategy_used == "fast"

    @pytest.mark.asyncio
    async def test_search_auto_l1_sufficient(self, service, mock_pattern):
        """Auto strategy stops at L1 when score >= L1_SUFFICIENT_SCORE."""
        mock_pattern.confidence = 1.0
        mock_pattern.title = "high cpu eks pods restart"
        mock_pattern.description = "high cpu"
        mock_pattern.symptoms = ["high", "cpu", "eks"]
        mock_pattern.root_cause = "high cpu"
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])

        result = await service.search("high cpu eks", strategy="auto")
        assert "L1" in result.levels_tried

    @pytest.mark.asyncio
    async def test_search_semantic_strategy(self, service, mock_pattern):
        """Semantic strategy uses L1+L2."""
        mock_pattern.confidence = 0.3
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])
        service._vector_search._initialized = True
        service._vector_search.semantic_search.return_value = [
            {"id": "vs-1", "title": "Vec Result", "description": "Desc",
             "score": 0.8, "service": "eks", "category": "perf"}
        ]

        result = await service.search("high cpu", strategy="semantic")
        assert "L1" in result.levels_tried
        assert "L2" in result.levels_tried
        assert "L3" not in result.levels_tried

    @pytest.mark.asyncio
    async def test_search_deep_strategy_with_rag(self, service, mock_pattern):
        """Deep strategy uses L1+L2+L3."""
        mock_pattern.confidence = 0.3
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])
        service._vector_search._initialized = True
        service._vector_search.semantic_search.return_value = []

        mock_rag = MagicMock()
        mock_rag.search.return_value = [
            {"source": "s3://bucket/pat-rag.json", "content": "RAG result content here",
             "score": 0.75, "metadata": {"key": "val"}}
        ]
        service.set_pattern_rag(mock_rag)

        result = await service.search("cpu issue", strategy="deep")
        assert "L3" in result.levels_tried
        assert any(h.source == "bedrock_kb" for h in result.hits)

    @pytest.mark.asyncio
    async def test_search_auto_escalates_to_l2(self, service, mock_pattern):
        """Auto strategy escalates to L2 when L1 score < threshold."""
        mock_pattern.confidence = 0.3
        mock_pattern.title = "unrelated"
        mock_pattern.description = "nothing"
        mock_pattern.symptoms = []
        mock_pattern.root_cause = "unknown"
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])
        service._vector_search._initialized = True
        service._vector_search.semantic_search.return_value = [
            {"id": "v1", "title": "Match", "description": "Good match",
             "score": 0.75, "service": "eks", "category": "perf"}
        ]

        result = await service.search("high cpu eks", strategy="auto")
        assert "L2" in result.levels_tried

    @pytest.mark.asyncio
    async def test_search_l1_failure_returns_empty(self, service):
        """L1 search failure is handled gracefully."""
        service._s3_kb.search_patterns = AsyncMock(side_effect=Exception("S3 down"))
        service._vector_search._initialized = False

        result = await service.search("query", strategy="semantic")
        assert result.hits == [] or all(h.search_level != "L1" for h in result.hits)

    @pytest.mark.asyncio
    async def test_search_l2_not_initialized(self, service, mock_pattern):
        """L2 skipped when vector search not initialized."""
        mock_pattern.confidence = 0.3
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])
        service._vector_search._initialized = False

        result = await service.search("query", strategy="semantic")
        assert "L2" in result.levels_tried  # tried but returned empty

    @pytest.mark.asyncio
    async def test_search_l2_failure_handled(self, service, mock_pattern):
        """L2 search failure is handled gracefully."""
        mock_pattern.confidence = 0.3
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])
        service._vector_search._initialized = True
        service._vector_search.semantic_search.side_effect = Exception("OpenSearch down")

        result = await service.search("query", strategy="deep")
        # Should not raise, L2 failure handled

    @pytest.mark.asyncio
    async def test_search_l3_none_rag(self, service, mock_pattern):
        """L3 skipped when pattern_rag is None."""
        mock_pattern.confidence = 0.3
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])
        service._vector_search._initialized = True
        service._vector_search.semantic_search.return_value = []
        service._pattern_rag = None

        result = await service.search("query", strategy="deep")
        assert "L3" not in result.levels_tried

    @pytest.mark.asyncio
    async def test_search_l3_failure_handled(self, service, mock_pattern):
        """L3 search failure is handled gracefully."""
        mock_pattern.confidence = 0.3
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])
        service._vector_search._initialized = True
        service._vector_search.semantic_search.return_value = []
        mock_rag = MagicMock()
        mock_rag.search.side_effect = Exception("Bedrock down")
        service.set_pattern_rag(mock_rag)

        result = await service.search("query", strategy="deep")
        # Should not raise

    @pytest.mark.asyncio
    async def test_search_dedup_by_pattern_id(self, service, mock_pattern):
        """Duplicate pattern_ids are deduped, keeping highest score."""
        p1 = MagicMock()
        p1.pattern_id = "dup-1"
        p1.title = "dup title low"
        p1.description = "dup"
        p1.symptoms = ["dup"]
        p1.root_cause = "dup"
        p1.resource_type = "eks"
        p1.severity = "high"
        p1.confidence = 0.3
        p1.remediation = "fix"
        service._s3_kb.search_patterns = AsyncMock(return_value=[p1])
        service._vector_search._initialized = True
        service._vector_search.semantic_search.return_value = [
            {"id": "dup-1", "title": "dup title high", "description": "dup",
             "score": 0.9, "service": "eks", "category": "perf"}
        ]

        result = await service.search("dup query", strategy="semantic")
        ids = [h.pattern_id for h in result.hits]
        assert ids.count("dup-1") <= 1

    @pytest.mark.asyncio
    async def test_search_min_score_filter(self, service, mock_pattern):
        """Results below min_score are filtered out."""
        mock_pattern.confidence = 0.1
        mock_pattern.title = "unrelated"
        mock_pattern.description = "nothing"
        mock_pattern.symptoms = []
        mock_pattern.root_cause = ""
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])

        result = await service.search("query", strategy="fast", min_score=0.8)
        assert all(h.score >= 0.8 for h in result.hits)

    @pytest.mark.asyncio
    async def test_search_limit(self, service):
        """Limit parameter caps results."""
        patterns = []
        for i in range(10):
            p = MagicMock()
            p.pattern_id = f"pat-{i}"
            p.title = f"pattern {i} query match"
            p.description = "query match"
            p.symptoms = ["query"]
            p.root_cause = "query"
            p.resource_type = "eks"
            p.severity = "low"
            p.confidence = 0.9
            p.remediation = "fix"
            patterns.append(p)
        service._s3_kb.search_patterns = AsyncMock(return_value=patterns)

        result = await service.search("query match", strategy="fast", limit=3)
        assert len(result.hits) <= 3

    @pytest.mark.asyncio
    async def test_search_with_doc_type_and_service(self, service, mock_pattern):
        """doc_type and service params are passed through."""
        mock_pattern.confidence = 0.3
        service._s3_kb.search_patterns = AsyncMock(return_value=[mock_pattern])
        service._vector_search._initialized = True
        service._vector_search.semantic_search.return_value = []

        result = await service.search("query", strategy="semantic",
                                       doc_type="pattern", service="eks")
        service._vector_search.semantic_search.assert_called_once()
        call_kwargs = service._vector_search.semantic_search.call_args
        assert call_kwargs[1].get("doc_type") == "pattern" or call_kwargs.kwargs.get("doc_type") == "pattern"


# ══════════════════════════════════════════════════════════════════════
# KnowledgeSearchService — index(), rebuild_index(), get_stats()
# ══════════════════════════════════════════════════════════════════════

class TestKnowledgeSearchServiceOps:
    @pytest.mark.asyncio
    async def test_index_accepted(self, service):
        """Pattern with quality >= threshold is indexed."""
        pattern = MagicMock()
        service._s3_kb.add_pattern = AsyncMock(return_value=True)
        result = await service.index(pattern, quality_score=0.8)
        assert result is True
        service._s3_kb.add_pattern.assert_called_once()

    @pytest.mark.asyncio
    async def test_index_rejected_low_quality(self, service):
        """Pattern with quality < threshold is rejected."""
        pattern = MagicMock()
        result = await service.index(pattern, quality_score=0.5)
        assert result is False

    @pytest.mark.asyncio
    async def test_index_at_threshold(self, service):
        """Pattern at exactly QUALITY_GATE_MIN is accepted."""
        pattern = MagicMock()
        service._s3_kb.add_pattern = AsyncMock(return_value=True)
        result = await service.index(pattern, quality_score=QUALITY_GATE_MIN)
        assert result is True

    @pytest.mark.asyncio
    async def test_rebuild_index(self, service):
        """rebuild_index iterates cache and indexes to vector search."""
        mock_pattern = MagicMock()
        mock_pattern.pattern_id = "p1"
        mock_pattern.title = "T"
        mock_pattern.description = "D"
        mock_pattern.root_cause = "RC"
        mock_pattern.remediation = "R"
        mock_pattern.symptoms = ["s1"]
        mock_pattern.resource_type = "eks"
        mock_pattern.severity = "high"
        mock_pattern.tags = ["t1"]

        service._s3_kb._cache_loaded = True
        service._s3_kb._local_cache = {"p1": mock_pattern}
        service._vector_search.index_knowledge.return_value = True

        result = await service.rebuild_index()
        assert result["indexed"] == 1
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_rebuild_index_loads_cache(self, service):
        """rebuild_index loads cache if not loaded."""
        service._s3_kb._cache_loaded = False
        service._s3_kb._load_cache = AsyncMock()
        service._s3_kb._local_cache = {}

        result = await service.rebuild_index()
        service._s3_kb._load_cache.assert_called_once()
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_rebuild_index_handles_failure(self, service):
        """rebuild_index handles individual index failures."""
        mock_pattern = MagicMock()
        mock_pattern.pattern_id = "p1"
        mock_pattern.title = "T"
        mock_pattern.description = "D"
        mock_pattern.root_cause = "RC"
        mock_pattern.remediation = "R"
        mock_pattern.symptoms = ["s1"]
        mock_pattern.resource_type = "eks"
        mock_pattern.severity = "high"
        mock_pattern.tags = ["t1"]

        service._s3_kb._cache_loaded = True
        service._s3_kb._local_cache = {"p1": mock_pattern}
        service._vector_search.index_knowledge.side_effect = Exception("fail")

        result = await service.rebuild_index()
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_rebuild_index_false_return(self, service):
        """rebuild_index counts False returns as failed."""
        mock_pattern = MagicMock()
        mock_pattern.pattern_id = "p1"
        mock_pattern.title = "T"
        mock_pattern.description = "D"
        mock_pattern.root_cause = "RC"
        mock_pattern.remediation = "R"
        mock_pattern.symptoms = ["s1"]
        mock_pattern.resource_type = "eks"
        mock_pattern.severity = "high"
        mock_pattern.tags = ["t1"]

        service._s3_kb._cache_loaded = True
        service._s3_kb._local_cache = {"p1": mock_pattern}
        service._vector_search.index_knowledge.return_value = False

        result = await service.rebuild_index()
        assert result["failed"] == 1

    def test_get_stats(self, service):
        """get_stats returns stats from all levels."""
        service._s3_kb.get_stats.return_value = {"total": 10}
        service._vector_search.get_stats.return_value = {"indexed": 10}

        stats = service.get_stats()
        assert "L1" in stats["levels"]
        assert "L2" in stats["levels"]
        assert "L3" in stats["levels"]
        assert stats["levels"]["L3"]["status"] == "not_configured"

    def test_get_stats_with_rag(self, service):
        """get_stats shows L3 configured when rag is set."""
        service._s3_kb.get_stats.return_value = {}
        service._vector_search.get_stats.return_value = {}
        service.set_pattern_rag(MagicMock())

        stats = service.get_stats()
        assert stats["levels"]["L3"]["status"] == "configured"

    def test_get_stats_l1_error(self, service):
        """get_stats handles L1 error gracefully."""
        service._s3_kb.get_stats.side_effect = Exception("S3 error")
        service._vector_search.get_stats.return_value = {}

        stats = service.get_stats()
        assert stats["levels"]["L1"] == {"error": "unavailable"}

    def test_get_stats_l2_error(self, service):
        """get_stats handles L2 error gracefully."""
        service._s3_kb.get_stats.return_value = {}
        service._vector_search.get_stats.side_effect = Exception("OS error")

        stats = service.get_stats()
        assert stats["levels"]["L2"] == {"error": "unavailable"}


# ══════════════════════════════════════════════════════════════════════
# Lazy property tests
# ══════════════════════════════════════════════════════════════════════

class TestLazyProperties:
    def test_s3_kb_lazy_init(self):
        svc = KnowledgeSearchService()
        mock_kb = MagicMock()
        with patch.dict("sys.modules", {"src.s3_knowledge_base": MagicMock(S3KnowledgeBase=MagicMock(return_value=mock_kb))}):
            kb = svc.s3_kb
            assert kb is not None
            kb2 = svc.s3_kb
            assert kb is kb2

    def test_vector_search_lazy_init(self):
        svc = KnowledgeSearchService()
        mock_vs = MagicMock()
        with patch.dict("sys.modules", {"src.vector_search": MagicMock(get_vector_search=MagicMock(return_value=mock_vs))}):
            vs = svc.vector_search
            assert vs is not None

    def test_pattern_rag_default_none(self):
        svc = KnowledgeSearchService()
        assert svc.pattern_rag is None

    def test_set_pattern_rag(self):
        svc = KnowledgeSearchService()
        mock_rag = MagicMock()
        svc.set_pattern_rag(mock_rag)
        assert svc.pattern_rag is mock_rag


# ══════════════════════════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════════════════════════

class TestSingleton:
    def test_get_knowledge_search_singleton(self):
        import src.knowledge_search as ks_mod
        ks_mod._service = None
        s1 = get_knowledge_search()
        s2 = get_knowledge_search()
        assert s1 is s2
        ks_mod._service = None  # cleanup


# ══════════════════════════════════════════════════════════════════════
# Legacy: PatternCategory
# ══════════════════════════════════════════════════════════════════════

class TestPatternCategory:
    def test_categories(self):
        assert PatternCategory.PERFORMANCE == "performance"
        assert PatternCategory.AVAILABILITY == "availability"
        assert PatternCategory.SECURITY == "security"
        assert PatternCategory.COST == "cost"
        assert PatternCategory.CONFIGURATION == "configuration"


# ══════════════════════════════════════════════════════════════════════
# Legacy: IncidentRecord
# ══════════════════════════════════════════════════════════════════════

class TestIncidentRecord:
    def test_to_dict(self, sample_incident):
        d = sample_incident.to_dict()
        assert d["incident_id"] == "inc-001"
        assert d["title"] == "High CPU on EKS"
        assert isinstance(d["symptoms"], list)

    def test_defaults(self):
        ir = IncidentRecord(incident_id="i1", title="T", description="D",
                            service="s", severity="low")
        assert ir.symptoms == []
        assert ir.root_cause == ""
        assert ir.resolved_by == "agent"


# ══════════════════════════════════════════════════════════════════════
# Legacy: LearnedPattern
# ══════════════════════════════════════════════════════════════════════

class TestLearnedPattern:
    def test_to_dict(self, sample_pattern):
        d = sample_pattern.to_dict()
        assert d["pattern_id"] == "lp-001"
        assert d["category"] == "performance"

    def test_from_dict(self, sample_pattern):
        d = sample_pattern.to_dict()
        p = LearnedPattern.from_dict(d)
        assert p.pattern_id == "lp-001"
        assert p.category == "performance"

    def test_from_dict_extra_keys(self):
        """from_dict ignores unknown keys."""
        d = {"pattern_id": "x", "title": "T", "description": "D",
             "category": "c", "service": "s", "severity": "low",
             "unknown_field": "ignored"}
        p = LearnedPattern.from_dict(d)
        assert p.pattern_id == "x"

    def test_from_anomaly_pattern(self, mock_pattern):
        mock_pattern.created_at = "2026-01-01"
        mock_pattern.updated_at = "2026-01-02"
        lp = LearnedPattern.from_anomaly_pattern(mock_pattern)
        assert lp.pattern_id == "pat-001"
        assert lp.category == "eks"
        assert lp.service == "eks"

    def test_defaults(self):
        lp = LearnedPattern(pattern_id="x", title="T", description="D",
                            category="c", service="s", severity="low")
        assert lp.confidence == 0.7
        assert lp.match_count == 0
        assert lp.feedback_score == 0.0


# ══════════════════════════════════════════════════════════════════════
# Legacy: IncidentLearner
# ══════════════════════════════════════════════════════════════════════

class TestIncidentLearner:
    def test_learn_from_incident_performance(self, sample_incident):
        store = MagicMock()
        learner = IncidentLearner(store)

        with patch("src.knowledge_search.get_knowledge_search") as mock_ks:
            mock_svc = MagicMock()
            mock_ks.return_value = mock_svc
            mock_svc.index = AsyncMock(return_value=True)

            pattern = learner.learn_from_incident(sample_incident)

        assert pattern is not None
        assert pattern.category == PatternCategory.PERFORMANCE
        assert "[Auto-learned]" in pattern.title
        store.save_pattern.assert_called_once()

    def test_learn_from_incident_availability(self):
        store = MagicMock()
        learner = IncidentLearner(store)
        incident = IncidentRecord(
            incident_id="i2", title="Service Down",
            description="Service unavailable timeout failure",
            service="ec2", severity="critical",
        )

        with patch("src.knowledge_search.get_knowledge_search") as mock_ks:
            mock_svc = MagicMock()
            mock_ks.return_value = mock_svc
            mock_svc.index = AsyncMock(return_value=True)
            pattern = learner.learn_from_incident(incident)

        assert pattern.category == PatternCategory.AVAILABILITY

    def test_learn_from_incident_security(self):
        store = MagicMock()
        learner = IncidentLearner(store)
        incident = IncidentRecord(
            incident_id="i3", title="IAM Permission Breach",
            description="Unauthorized access via iam permission",
            service="iam", severity="critical",
        )

        with patch("src.knowledge_search.get_knowledge_search") as mock_ks:
            mock_svc = MagicMock()
            mock_ks.return_value = mock_svc
            mock_svc.index = AsyncMock(return_value=True)
            pattern = learner.learn_from_incident(incident)

        assert pattern.category == PatternCategory.SECURITY

    def test_learn_from_incident_cost(self):
        store = MagicMock()
        learner = IncidentLearner(store)
        incident = IncidentRecord(
            incident_id="i4", title="Unused Resources",
            description="Oversized cost unused instances",
            service="ec2", severity="low",
        )

        with patch("src.knowledge_search.get_knowledge_search") as mock_ks:
            mock_svc = MagicMock()
            mock_ks.return_value = mock_svc
            mock_svc.index = AsyncMock(return_value=True)
            pattern = learner.learn_from_incident(incident)

        assert pattern.category == PatternCategory.COST

    def test_learn_from_incident_configuration(self):
        store = MagicMock()
        learner = IncidentLearner(store)
        incident = IncidentRecord(
            incident_id="i5", title="Config Drift",
            description="Misconfiguration in setting",
            service="eks", severity="medium",
        )

        with patch("src.knowledge_search.get_knowledge_search") as mock_ks:
            mock_svc = MagicMock()
            mock_ks.return_value = mock_svc
            mock_svc.index = AsyncMock(return_value=True)
            pattern = learner.learn_from_incident(incident)

        assert pattern.category == PatternCategory.CONFIGURATION

    def test_learn_persist_failure_handled(self, sample_incident):
        """Persistence failure doesn't prevent pattern return."""
        store = MagicMock()
        learner = IncidentLearner(store)

        with patch("src.knowledge_search.get_knowledge_search") as mock_ks:
            mock_svc = MagicMock()
            mock_ks.return_value = mock_svc
            mock_svc.index = AsyncMock(side_effect=Exception("persist fail"))
            pattern = learner.learn_from_incident(sample_incident)

        assert pattern is not None
        store.save_pattern.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
# Legacy: PatternFeedback
# ══════════════════════════════════════════════════════════════════════

class TestPatternFeedback:
    def test_submit_helpful(self, sample_pattern):
        store = MagicMock()
        store.get_pattern.return_value = sample_pattern
        fb = PatternFeedback(store)

        old_success = sample_pattern.success_count
        old_score = sample_pattern.feedback_score
        old_conf = sample_pattern.confidence

        result = fb.submit_feedback("lp-001", helpful=True)
        assert result is True
        assert sample_pattern.success_count == old_success + 1
        assert sample_pattern.feedback_score > old_score
        assert sample_pattern.confidence > old_conf
        store.save_pattern.assert_called_once()

    def test_submit_not_helpful(self, sample_pattern):
        store = MagicMock()
        store.get_pattern.return_value = sample_pattern
        fb = PatternFeedback(store)

        old_score = sample_pattern.feedback_score
        old_conf = sample_pattern.confidence

        result = fb.submit_feedback("lp-001", helpful=False)
        assert result is True
        assert sample_pattern.feedback_score < old_score
        assert sample_pattern.confidence < old_conf

    def test_submit_pattern_not_found(self):
        store = MagicMock()
        store.get_pattern.return_value = None
        fb = PatternFeedback(store)

        result = fb.submit_feedback("nonexistent", helpful=True)
        assert result is False

    def test_feedback_score_capped_positive(self):
        store = MagicMock()
        p = LearnedPattern(pattern_id="x", title="T", description="D",
                           category="c", service="s", severity="low",
                           feedback_score=0.95, confidence=0.94)
        store.get_pattern.return_value = p
        fb = PatternFeedback(store)
        fb.submit_feedback("x", helpful=True)
        assert p.feedback_score <= 1.0
        assert p.confidence <= 0.95

    def test_feedback_score_capped_negative(self):
        store = MagicMock()
        p = LearnedPattern(pattern_id="x", title="T", description="D",
                           category="c", service="s", severity="low",
                           feedback_score=-0.95, confidence=0.51)
        store.get_pattern.return_value = p
        fb = PatternFeedback(store)
        fb.submit_feedback("x", helpful=False)
        assert p.feedback_score >= -1.0
        assert p.confidence >= 0.5


# ══════════════════════════════════════════════════════════════════════
# Legacy: KnowledgeStore
# ══════════════════════════════════════════════════════════════════════

class TestKnowledgeStore:
    def _make_store(self):
        """Create a KnowledgeStore with mocked S3."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            import importlib
            import src.knowledge_search as ksm
            # Directly create instance and skip __init__ S3 load
            store = object.__new__(KnowledgeStore)
            store.s3_bucket = "test-bucket"
            store.patterns = {}
            store._loaded = True
            return store

    def test_init_s3_failure(self):
        """KnowledgeStore handles S3 load failure gracefully."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}) as mods:
            mock_boto = mods["boto3"]
            mock_boto.client.side_effect = Exception("No creds")
            store = KnowledgeStore(s3_bucket="test-bucket")
            assert store._loaded is True
            assert len(store.patterns) == 0

    def test_init_loads_patterns(self):
        """KnowledgeStore loads patterns from S3."""
        import json as _json
        pattern_data = {
            "pattern_id": "p1", "title": "T", "description": "D",
            "category": "performance", "service": "eks", "severity": "high",
        }
        with patch.dict("sys.modules", {"boto3": MagicMock()}) as mods:
            mock_boto = mods["boto3"]
            mock_s3 = MagicMock()
            mock_boto.client.return_value = mock_s3
            paginator = MagicMock()
            mock_s3.get_paginator.return_value = paginator
            paginator.paginate.return_value = [
                {"Contents": [{"Key": "learned/eks/p1.json"}]}
            ]
            body = MagicMock()
            body.read.return_value = _json.dumps(pattern_data).encode()
            mock_s3.get_object.return_value = {"Body": body}

            store = KnowledgeStore(s3_bucket="test-bucket")
            assert "p1" in store.patterns

    def test_init_handles_bad_pattern(self):
        """KnowledgeStore skips corrupt patterns."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}) as mods:
            mock_boto = mods["boto3"]
            mock_s3 = MagicMock()
            mock_boto.client.return_value = mock_s3
            paginator = MagicMock()
            mock_s3.get_paginator.return_value = paginator
            paginator.paginate.return_value = [
                {"Contents": [{"Key": "learned/eks/bad.json"}]}
            ]
            body = MagicMock()
            body.read.return_value = b"not json"
            mock_s3.get_object.return_value = {"Body": body}

            store = KnowledgeStore(s3_bucket="test-bucket")
            assert len(store.patterns) == 0

    def test_save_pattern_success(self, sample_pattern):
        store = self._make_store()
        with patch.dict("sys.modules", {"boto3": MagicMock()}) as mods:
            result = store.save_pattern(sample_pattern)
            assert result is True
            assert sample_pattern.pattern_id in store.patterns

    def test_save_pattern_s3_failure(self, sample_pattern):
        store = self._make_store()
        with patch.dict("sys.modules", {"boto3": MagicMock()}) as mods:
            mock_boto = mods["boto3"]
            mock_boto.client.return_value.put_object.side_effect = Exception("fail")
            result = store.save_pattern(sample_pattern)
            assert result is False
            assert sample_pattern.pattern_id in store.patterns

    def test_get_pattern(self, sample_pattern):
        store = self._make_store()
        store.patterns["lp-001"] = sample_pattern
        assert store.get_pattern("lp-001") == sample_pattern
        assert store.get_pattern("nonexistent") is None

    def test_search_patterns_by_service(self, sample_pattern):
        store = self._make_store()
        store.patterns["lp-001"] = sample_pattern
        assert len(store.search_patterns(service="eks")) == 1
        assert len(store.search_patterns(service="lambda")) == 0

    def test_search_patterns_by_category(self, sample_pattern):
        store = self._make_store()
        store.patterns["lp-001"] = sample_pattern
        assert len(store.search_patterns(category="performance")) == 1
        assert len(store.search_patterns(category="security")) == 0

    def test_search_patterns_by_severity(self, sample_pattern):
        store = self._make_store()
        store.patterns["lp-001"] = sample_pattern
        assert len(store.search_patterns(severity="high")) == 1
        assert len(store.search_patterns(severity="low")) == 0

    def test_search_patterns_by_keywords(self, sample_pattern):
        store = self._make_store()
        store.patterns["lp-001"] = sample_pattern
        assert len(store.search_patterns(keywords=["slow", "timeout"])) == 1
        assert len(store.search_patterns(keywords=["unrelated"])) == 0

    def test_search_patterns_limit(self):
        store = self._make_store()
        for i in range(5):
            p = LearnedPattern(pattern_id=f"p{i}", title=f"T{i}", description="D",
                               category="performance", service="eks", severity="high",
                               symptom_keywords=["k1"], confidence=0.8)
            store.patterns[f"p{i}"] = p
        results = store.search_patterns(keywords=["k1"], limit=2)
        assert len(results) == 2

    def test_search_patterns_no_filters(self, sample_pattern):
        store = self._make_store()
        store.patterns["lp-001"] = sample_pattern
        results = store.search_patterns()
        assert len(results) == 1

    def test_get_stats(self, sample_pattern):
        store = self._make_store()
        store.patterns["lp-001"] = sample_pattern
        stats = store.get_stats()
        assert stats["total_patterns"] == 1
        assert "by_category" in stats
        assert "by_service" in stats
        assert stats["avg_confidence"] == sample_pattern.confidence

    def test_get_stats_empty(self):
        store = self._make_store()
        stats = store.get_stats()
        assert stats["total_patterns"] == 0
        assert stats["avg_confidence"] == 0.0


# ══════════════════════════════════════════════════════════════════════
# Legacy singletons
# ══════════════════════════════════════════════════════════════════════

class TestLegacySingletons:
    def test_get_knowledge_store(self):
        import src.knowledge_search as ks_mod
        ks_mod._knowledge_store = None
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            s1 = get_knowledge_store()
            s2 = get_knowledge_store()
            assert s1 is s2
        ks_mod._knowledge_store = None

    def test_get_incident_learner(self):
        import src.knowledge_search as ks_mod
        ks_mod._incident_learner = None
        ks_mod._knowledge_store = None
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            l1 = get_incident_learner()
            l2 = get_incident_learner()
            assert l1 is l2
        ks_mod._incident_learner = None
        ks_mod._knowledge_store = None

    def test_get_feedback_handler(self):
        import src.knowledge_search as ks_mod
        ks_mod._feedback_handler = None
        ks_mod._knowledge_store = None
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            f1 = get_feedback_handler()
            f2 = get_feedback_handler()
            assert f1 is f2
        ks_mod._feedback_handler = None
        ks_mod._knowledge_store = None
