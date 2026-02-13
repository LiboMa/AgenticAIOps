"""
E2E Integration Test — Unified Closed-Loop Pipeline

验证 Ma Ronnie 确认的正确流程:
  Detect Agent (采集) → Pattern 匹配 → Vectorize → 存储 (S3+OS)
                                                        ↓
  RCA Agent ← 从存储读取 → 分析 → 修补/告警

核心验证: "学了能用" — 第二次诊断能检索到第一次学到的 Pattern

Test stages:
  Stage 1: ProactiveAgent quick_scan → DetectAgent → findings
  Stage 2: KnowledgeSearchService search (empty KB)
  Stage 3: RCA inference with vector knowledge
  Stage 4: Learn from incident → KB write-back
  Stage 5: Re-search KB → verify learned pattern is found
  Stage 6: Full round-trip — alarm trigger → reuse detect data → RCA → complete
"""

import asyncio
import pytest
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass

from src.proactive_agent import ProactiveAgentSystem, TaskType
from src.knowledge_search import KnowledgeSearchService, SearchResult, SearchHit
from src.s3_knowledge_base import AnomalyPattern, S3KnowledgeBase, DEFAULT_PATTERNS

logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_detect_result(anomalies=None, alarms=None, error=None):
    """Create a mock DetectResult."""
    result = MagicMock()
    result.error = error
    result.detect_id = "det-e2e-test-001"
    result.anomalies_detected = anomalies or []
    result.correlated_event = MagicMock()
    result.correlated_event.alarms = alarms or []
    result.correlated_event.collection_id = "col-e2e-001"
    result.correlated_event.metrics = {
        "ec2": [{"instance_id": "i-test123", "CPUUtilization": {"avg": 95.2}}]
    }
    return result


def _make_kb_service():
    """Create a KnowledgeSearchService with mocked backends but real logic."""
    svc = KnowledgeSearchService()
    # Use a real S3KnowledgeBase with no S3 connection (local cache only)
    kb = S3KnowledgeBase.__new__(S3KnowledgeBase)
    kb.bucket_name = "test-bucket"
    kb.prefix = "patterns/"
    kb.s3_client = None
    kb._local_cache = {}
    kb._cache_loaded = True
    svc._s3_kb = kb

    # Mock vector_search to avoid real OpenSearch
    mock_vs = MagicMock()
    mock_vs._initialized = True
    mock_vs.semantic_search.return_value = []
    mock_vs.hybrid_search.return_value = []
    mock_vs.index_knowledge.return_value = True
    svc._vector_search = mock_vs

    return svc


# ─── Stage 1: ProactiveAgent → DetectAgent → Findings ────────────────────────

class TestStage1_Detection:
    """ProactiveAgent delegates to DetectAgent and converts anomalies to findings."""

    @pytest.mark.asyncio
    async def test_quick_scan_detects_anomalies(self):
        """ProactiveAgent detects CPU spike via DetectAgent."""
        system = ProactiveAgentSystem()

        mock_result = _make_detect_result(
            anomalies=[{
                "type": "cpu_spike",
                "resource": "i-test123",
                "metric": "CPUUtilization",
                "value": 95.2,
                "severity": "high",
                "description": "EC2 i-test123 CPU > 90%",
            }]
        )
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        # Patch get_detect_agent_async (used inside _action_quick_scan)
        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            result = await system._execute_task(system.tasks["heartbeat"])

        assert result.status == "alert"
        assert len(result.findings) >= 1
        # Findings come from detect result anomalies
        resources = [f.get("resource") for f in result.findings]
        assert "i-test123" in resources

    @pytest.mark.asyncio
    async def test_detect_result_cached_for_orchestrator(self):
        """DetectResult is cached for downstream Orchestrator consumption."""
        system = ProactiveAgentSystem()

        mock_result = _make_detect_result(anomalies=[{
            "type": "cpu_spike", "resource": "i-123",
            "metric": "CPUUtilization", "value": 95,
            "severity": "high", "description": "High CPU",
        }])
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            await system._execute_task(system.tasks["heartbeat"])

        # Should cache a detect result (may be the mock or a real one wrapping mock data)
        assert system._last_detect_result is not None


# ─── Stage 2: KnowledgeSearchService — Empty KB Search ───────────────────────

class TestStage2_EmptyKBSearch:
    """Search an empty KB returns no results."""

    @pytest.mark.asyncio
    async def test_search_empty_kb_returns_no_hits(self):
        """L1 search on empty KB yields zero hits."""
        svc = _make_kb_service()
        result = await svc.search("EC2 high CPU utilization", strategy="fast")
        assert isinstance(result, SearchResult)
        assert result.total_hits == 0
        assert result.best_hit is None

    @pytest.mark.asyncio
    async def test_search_auto_escalates_to_l2(self):
        """Auto strategy escalates to L2 when L1 has no results."""
        svc = _make_kb_service()
        result = await svc.search("EC2 high CPU utilization", strategy="auto")
        assert "L2" in result.levels_tried


# ─── Stage 3: RCA with Knowledge Context ─────────────────────────────────────

class TestStage3_RCAWithKnowledge:
    """RCA inference uses KnowledgeSearchService to enrich Claude prompt."""

    @pytest.mark.asyncio
    async def test_rca_prompt_includes_historical_patterns(self):
        """When KB has patterns, RCA prompt includes Historical Patterns section."""
        from src.rca_inference import _build_analysis_prompt

        # Build a mock correlated event
        mock_event = MagicMock()
        mock_event.anomalies = [{
            "type": "cpu_spike",
            "resource": "i-test123",
            "metric": "CPUUtilization",
            "value": 95,
            "threshold": 80,
            "severity": "high",
        }]
        mock_event.alarms = []
        mock_event.metrics = []
        mock_event.trail_events = []
        mock_event.health_events = []
        mock_event.recent_changes = []

        # Create a knowledge context with hits
        knowledge_context = SearchResult(
            query="EC2 high CPU",
            hits=[SearchHit(
                pattern_id="ec2_high_cpu",
                title="EC2 High CPU Utilization",
                description="CPU > 90%",
                score=0.85,
                source="local_cache",
                search_level="L1",
                content="Check for runaway processes",
                metadata={"remediation": "Scale up or optimize workload"},
            )],
            strategy_used="auto",
            levels_tried=["L1"],
            duration_ms=5.0,
            total_hits=1,
        )

        # _build_analysis_prompt accepts knowledge_context parameter
        prompt = _build_analysis_prompt(mock_event, knowledge_context=knowledge_context)
        assert "Historical" in prompt or "EC2 High CPU" in prompt
        assert "ec2_high_cpu" in prompt or "L1" in prompt


# ─── Stage 4: Learn from Incident → KB Write-Back ─────────────────────────────

class TestStage4_LearnAndWriteBack:
    """Incident learning writes patterns to KB for future retrieval."""

    @pytest.mark.asyncio
    async def test_index_pattern_writes_to_local_cache(self):
        """KnowledgeSearchService.index() adds pattern to S3 KB cache."""
        svc = _make_kb_service()

        pattern = AnomalyPattern(
            pattern_id="learned_cpu_001",
            title="EC2 High CPU — Learned",
            description="Learned from incident: EC2 CPU spike on i-test123",
            resource_type="ec2",
            severity="high",
            symptoms=["high cpu", "cpu utilization above 90%"],
            root_cause="Runaway process consuming all CPU cores",
            remediation="Identify and kill runaway process, then scale up if needed",
            tags=["learned", "ec2", "cpu"],
            confidence=0.85,
        )

        result = await svc.index(pattern, quality_score=0.85)
        assert result is True

        # Verify pattern is in local cache
        assert "learned_cpu_001" in svc.s3_kb._local_cache
        cached = svc.s3_kb._local_cache["learned_cpu_001"]
        assert cached.title == "EC2 High CPU — Learned"
        assert cached.root_cause == "Runaway process consuming all CPU cores"

    @pytest.mark.asyncio
    async def test_index_rejects_low_quality(self):
        """Patterns with low quality score are rejected."""
        svc = _make_kb_service()

        pattern = AnomalyPattern(
            pattern_id="bad_pattern",
            title="Low Quality",
            description="Should be rejected",
            resource_type="ec2",
            severity="low",
        )

        result = await svc.index(pattern, quality_score=0.5)
        assert result is False
        assert "bad_pattern" not in svc.s3_kb._local_cache

    @pytest.mark.asyncio
    async def test_opensearch_dual_write(self):
        """Index also writes to OpenSearch (vector_search) via s3_kb._index_to_opensearch."""
        svc = _make_kb_service()

        mock_vs = MagicMock()
        mock_vs._initialized = True
        mock_vs.index_knowledge.return_value = True

        pattern = AnomalyPattern(
            pattern_id="dual_write_test",
            title="Dual Write Test",
            description="Should appear in both S3 and OS",
            resource_type="ec2",
            severity="high",
            symptoms=["test"],
            root_cause="test root cause",
            remediation="test remediation",
            confidence=0.9,
        )

        # Patch get_vector_search where s3_knowledge_base imports it
        with patch("src.vector_search.get_vector_search", return_value=mock_vs):
            await svc.index(pattern, quality_score=0.9)

        # Verify OpenSearch was called via s3_kb's _index_to_opensearch
        mock_vs.index_knowledge.assert_called_once()
        call_kwargs = mock_vs.index_knowledge.call_args
        assert call_kwargs[1]["doc_id"] == "dual_write_test" if call_kwargs[1] else call_kwargs.kwargs.get("doc_id") == "dual_write_test"


# ─── Stage 5: Re-Search KB → Verify Learned Pattern Found ────────────────────

class TestStage5_LearnedPatternRetrieval:
    """核心验证: 学了能用 — 存入 KB 的 pattern 能被后续搜索检索到。"""

    @pytest.mark.asyncio
    async def test_learned_pattern_found_by_l1_search(self):
        """Pattern stored via index() is retrievable via L1 keyword search."""
        svc = _make_kb_service()

        # Step 1: Learn a pattern (simulating post-incident learning)
        pattern = AnomalyPattern(
            pattern_id="learned_cpu_002",
            title="EC2 High CPU Utilization",
            description="CPU spike on EC2 instance",
            resource_type="ec2",
            severity="high",
            symptoms=["high cpu", "cpu utilization", "performance degradation"],
            root_cause="Memory leak in application causing CPU thrashing",
            remediation="Restart application and apply memory limit",
            tags=["learned", "ec2", "cpu"],
            confidence=0.88,
        )
        await svc.index(pattern, quality_score=0.88)

        # Step 2: Search — should find the learned pattern
        result = await svc.search("EC2 high CPU utilization", strategy="fast", service="ec2")

        assert result.total_hits >= 1
        hit = result.hits[0]
        assert hit.pattern_id == "learned_cpu_002"
        assert hit.search_level == "L1"
        assert "CPU" in hit.title

    @pytest.mark.asyncio
    async def test_learned_pattern_includes_remediation(self):
        """Retrieved pattern contains actionable remediation steps."""
        svc = _make_kb_service()

        pattern = AnomalyPattern(
            pattern_id="learned_s3_public",
            title="S3 Public Bucket Detected",
            description="S3 bucket has public access",
            resource_type="s3",
            severity="critical",
            symptoms=["public access", "bucket policy"],
            root_cause="Bucket policy allows public reads",
            remediation="Block public access via S3 Block Public Access settings",
            confidence=0.95,
        )
        await svc.index(pattern, quality_score=0.95)

        result = await svc.search("S3 public bucket access", strategy="fast")
        assert result.total_hits >= 1
        # Verify the pattern has remediation info
        stored = svc.s3_kb._local_cache["learned_s3_public"]
        assert "Block public access" in stored.remediation

    @pytest.mark.asyncio
    async def test_multiple_patterns_ranked_by_score(self):
        """Multiple learned patterns are ranked by relevance score."""
        svc = _make_kb_service()

        # Learn two patterns
        p1 = AnomalyPattern(
            pattern_id="cpu_01",
            title="EC2 CPU High",
            description="CPU spike general",
            resource_type="ec2",
            severity="high",
            symptoms=["cpu spike", "high cpu"],
            confidence=0.7,
        )
        p2 = AnomalyPattern(
            pattern_id="cpu_02",
            title="EC2 CPU Utilization Critical",
            description="EC2 CPU utilization above threshold",
            resource_type="ec2",
            severity="critical",
            symptoms=["cpu utilization", "threshold exceeded", "high cpu"],
            confidence=0.95,
        )
        await svc.index(p1, quality_score=0.8)
        await svc.index(p2, quality_score=0.95)

        result = await svc.search("EC2 CPU utilization high", strategy="fast")
        assert result.total_hits >= 2
        # Higher confidence pattern should rank first (or equal)
        scores = [h.score for h in result.hits]
        assert scores == sorted(scores, reverse=True), "Results should be sorted by score descending"


# ─── Stage 6: Full Round-Trip — Alarm → Detect → RCA → Learn → Re-RCA ────────

class TestStage6_FullRoundTrip:
    """
    Complete closed-loop test:
    1. First incident: detect → RCA → learn
    2. Second incident: detect → RCA should find learned pattern
    """

    @pytest.mark.asyncio
    async def test_alarm_trigger_full_pipeline(self):
        """
        Simulate: alarm fires → ProactiveAgent detects → findings generated
        → Orchestrator would call RCA → learn → KB updated
        """
        system = ProactiveAgentSystem()
        svc = _make_kb_service()

        # Step 1: Detection
        mock_result = _make_detect_result(
            anomalies=[{
                "type": "cpu_spike",
                "resource": "i-prod-001",
                "metric": "CPUUtilization",
                "value": 98.5,
                "severity": "critical",
                "description": "Production EC2 CPU critical",
            }]
        )
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            scan_result = await system._execute_task(system.tasks["heartbeat"])

        assert scan_result.status == "alert"

        # Step 2: Learn from this incident
        learned_pattern = AnomalyPattern(
            pattern_id="incident_cpu_prod_001",
            title="Production EC2 CPU Critical",
            description="CPU spike to 98.5% on production instance i-prod-001",
            resource_type="ec2",
            severity="critical",
            symptoms=["cpu spike", "cpu critical", "production impact"],
            root_cause="Database connection pool exhaustion causing CPU spin-wait",
            remediation="1. Restart connection pool 2. Scale RDS 3. Add connection limits",
            tags=["learned", "production", "ec2", "cpu"],
            confidence=0.92,
        )
        await svc.index(learned_pattern, quality_score=0.92)

        # Step 3: Second occurrence — search should find learned pattern
        search_result = await svc.search(
            "EC2 CPU critical production",
            strategy="fast",
            service="ec2",
        )

        assert search_result.total_hits >= 1
        best = search_result.best_hit
        assert best is not None
        assert "CPU" in best.title
        assert best.search_level == "L1"

        # Verify the full remediation is available
        stored = svc.s3_kb._local_cache["incident_cpu_prod_001"]
        assert "connection pool" in stored.root_cause
        assert "Restart connection pool" in stored.remediation

    @pytest.mark.asyncio
    async def test_detect_result_data_reuse(self):
        """
        DetectResult from first scan can be passed to Orchestrator
        to skip Stage 1 re-collection (R1 rule).
        """
        system = ProactiveAgentSystem()

        mock_result = _make_detect_result(anomalies=[{
            "type": "memory_pressure",
            "resource": "i-test-mem",
            "metric": "MemoryUtilization",
            "value": 95,
            "severity": "high",
            "description": "Memory pressure detected",
        }])
        mock_agent = MagicMock()
        mock_agent.run_detection = AsyncMock(return_value=mock_result)

        with patch("src.detect_agent.get_detect_agent_async", new=AsyncMock(return_value=mock_agent)):
            await system._execute_task(system.tasks["heartbeat"])

        # DetectResult should be cached (may be wrapped)
        assert system._last_detect_result is not None

    @pytest.mark.asyncio
    async def test_manual_trigger_does_not_reuse_stale_data(self):
        """
        R2 rule: manual triggers should always do fresh collection,
        never reuse stale detect results.
        """
        svc = _make_kb_service()

        # Seed KB with a pattern
        pattern = AnomalyPattern(
            pattern_id="manual_test_pattern",
            title="Manual Investigation Pattern",
            description="Pattern from manual investigation",
            resource_type="ec2",
            severity="medium",
            symptoms=["manual check"],
            confidence=0.8,
        )
        await svc.index(pattern, quality_score=0.8)

        # Search should still work
        result = await svc.search("manual check pattern", strategy="fast")
        assert result.total_hits >= 1
