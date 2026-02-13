"""
Tests for s3_knowledge_base.py — S3 Pattern 存储 + 匹配

Coverage targets:
- AnomalyPattern dataclass: creation, serialization
- S3KnowledgeBase: add/get/search/match patterns
- Quality gate (score < 0.7 rejection)
- Match scoring algorithm
- Default patterns seeding
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from src.s3_knowledge_base import (
    AnomalyPattern,
    RCAResult,
    S3KnowledgeBase,
    DEFAULT_PATTERNS,
    get_knowledge_base,
    S3_BUCKET_NAME,
    S3_PREFIX,
)


def _make_kb(s3_client=None):
    """Create a S3KnowledgeBase without hitting real AWS."""
    kb = S3KnowledgeBase.__new__(S3KnowledgeBase)
    kb.bucket_name = S3_BUCKET_NAME
    kb.prefix = S3_PREFIX
    kb.s3_client = s3_client
    kb._local_cache = {}
    kb._cache_loaded = False
    return kb


def _make_seeded_kb():
    """Create a KB pre-loaded with DEFAULT_PATTERNS."""
    kb = _make_kb()
    kb._cache_loaded = True
    for p in DEFAULT_PATTERNS:
        kb._local_cache[p.pattern_id] = p
    return kb


# ─── AnomalyPattern Tests ────────────────────────────────────────────────────

class TestAnomalyPattern:
    def test_creation_defaults(self):
        p = AnomalyPattern(
            pattern_id="test_001",
            title="Test Pattern",
            description="A test pattern",
            resource_type="ec2",
            severity="high",
        )
        assert p.pattern_id == "test_001"
        assert p.symptoms == []
        assert p.root_cause == ""
        assert p.remediation == ""
        assert p.metrics == {}
        assert p.tags == []
        assert p.confidence == 0.8
        assert p.source == "agent"

    def test_creation_full(self):
        p = AnomalyPattern(
            pattern_id="test_002",
            title="Full Pattern",
            description="Complete pattern",
            resource_type="s3",
            severity="critical",
            symptoms=["public access", "no encryption"],
            root_cause="Misconfigured bucket policy",
            remediation="Enable block public access",
            metrics={"risk_score": 9.5},
            tags=["s3", "security"],
            confidence=0.95,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
            source="manual",
        )
        assert p.severity == "critical"
        assert len(p.symptoms) == 2
        assert p.confidence == 0.95

    def test_to_dict(self):
        p = AnomalyPattern(
            pattern_id="test_003",
            title="Dict Test",
            description="For serialization",
            resource_type="rds",
            severity="medium",
        )
        d = p.to_dict()
        assert isinstance(d, dict)
        assert d["pattern_id"] == "test_003"
        assert d["title"] == "Dict Test"
        assert d["resource_type"] == "rds"
        assert d["confidence"] == 0.8

    def test_from_dict(self):
        data = {
            "pattern_id": "test_004",
            "title": "From Dict",
            "description": "Deserialized",
            "resource_type": "lambda",
            "severity": "low",
            "symptoms": ["timeout"],
            "root_cause": "cold start",
            "remediation": "increase memory",
            "metrics": {},
            "tags": ["lambda"],
            "confidence": 0.7,
            "created_at": "",
            "updated_at": "",
            "source": "imported",
        }
        p = AnomalyPattern.from_dict(data)
        assert p.pattern_id == "test_004"
        assert p.symptoms == ["timeout"]
        assert p.source == "imported"

    def test_roundtrip_serialization(self):
        original = AnomalyPattern(
            pattern_id="roundtrip",
            title="Roundtrip",
            description="Test roundtrip",
            resource_type="ec2",
            severity="high",
            symptoms=["high cpu", "slow response"],
            confidence=0.88,
        )
        restored = AnomalyPattern.from_dict(original.to_dict())
        assert restored.pattern_id == original.pattern_id
        assert restored.symptoms == original.symptoms
        assert restored.confidence == original.confidence


class TestRCAResult:
    def test_creation(self):
        r = RCAResult(
            issue_id="issue-001",
            matched_pattern=None,
            confidence=0.0,
            analysis="No match found",
            recommendations=["Manual investigation"],
            timestamp="2026-01-01T00:00:00",
        )
        assert r.issue_id == "issue-001"
        assert r.matched_pattern is None
        assert len(r.recommendations) == 1


# ─── Default Patterns ─────────────────────────────────────────────────────────

class TestDefaultPatterns:
    def test_default_patterns_count(self):
        assert len(DEFAULT_PATTERNS) == 6

    def test_default_pattern_ids(self):
        ids = {p.pattern_id for p in DEFAULT_PATTERNS}
        assert "ec2_high_cpu" in ids
        assert "s3_public_bucket" in ids
        assert "iam_root_mfa" in ids
        assert "ec2_sg_open_ssh" in ids
        assert "lambda_deprecated_runtime" in ids
        assert "rds_public_access" in ids

    def test_default_patterns_have_symptoms(self):
        for p in DEFAULT_PATTERNS:
            assert len(p.symptoms) > 0, f"Pattern {p.pattern_id} has no symptoms"

    def test_default_patterns_have_root_cause(self):
        for p in DEFAULT_PATTERNS:
            assert p.root_cause, f"Pattern {p.pattern_id} has no root_cause"

    def test_default_patterns_have_remediation(self):
        for p in DEFAULT_PATTERNS:
            assert p.remediation, f"Pattern {p.pattern_id} has no remediation"

    def test_default_patterns_confidence_range(self):
        for p in DEFAULT_PATTERNS:
            assert 0.0 <= p.confidence <= 1.0


# ─── S3KnowledgeBase Init ─────────────────────────────────────────────────────

class TestS3KnowledgeBaseInit:
    def test_init_with_mock_boto3(self):
        with patch("boto3.client") as mock_client:
            kb = S3KnowledgeBase()
            assert kb.bucket_name == S3_BUCKET_NAME
            assert kb.s3_client is not None

    def test_init_custom_bucket(self):
        with patch("boto3.client"):
            kb = S3KnowledgeBase(bucket_name="custom-bucket")
            assert kb.bucket_name == "custom-bucket"

    def test_init_s3_failure(self):
        with patch("boto3.client", side_effect=Exception("No AWS credentials")):
            kb = S3KnowledgeBase()
            assert kb.s3_client is None


# ─── Quality Gate ──────────────────────────────────────────────────────────────

class TestQualityGate:
    @pytest.mark.asyncio
    async def test_reject_low_quality(self):
        kb = _make_kb()
        pattern = AnomalyPattern(
            pattern_id="low_q", title="Low Quality", description="Below threshold",
            resource_type="ec2", severity="low",
        )
        result = await kb.add_pattern(pattern, quality_score=0.5)
        assert result is False
        assert "low_q" not in kb._local_cache

    @pytest.mark.asyncio
    async def test_reject_zero_quality(self):
        kb = _make_kb()
        pattern = AnomalyPattern(
            pattern_id="zero_q", title="Zero", description="Zero score",
            resource_type="ec2", severity="low",
        )
        result = await kb.add_pattern(pattern, quality_score=0.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_accept_high_quality(self):
        kb = _make_kb()
        pattern = AnomalyPattern(
            pattern_id="high_q", title="High Quality", description="Above threshold",
            resource_type="ec2", severity="high",
        )
        result = await kb.add_pattern(pattern, quality_score=0.8)
        assert result is True
        assert "high_q" in kb._local_cache

    @pytest.mark.asyncio
    async def test_accept_boundary_quality(self):
        kb = _make_kb()
        pattern = AnomalyPattern(
            pattern_id="boundary_q", title="Boundary", description="At threshold",
            resource_type="ec2", severity="medium",
        )
        result = await kb.add_pattern(pattern, quality_score=0.7)
        assert result is True


# ─── Pattern CRUD ──────────────────────────────────────────────────────────────

class TestPatternCRUD:
    @pytest.mark.asyncio
    async def test_add_sets_timestamps(self):
        kb = _make_kb()
        pattern = AnomalyPattern(
            pattern_id="ts_test", title="Timestamp", description="Check timestamps",
            resource_type="ec2", severity="low",
        )
        await kb.add_pattern(pattern, quality_score=1.0)
        stored = kb._local_cache["ts_test"]
        assert stored.created_at != ""
        assert stored.updated_at != ""

    @pytest.mark.asyncio
    async def test_add_generates_id(self):
        kb = _make_kb()
        pattern = AnomalyPattern(
            pattern_id="", title="Auto ID", description="Generate ID",
            resource_type="ec2", severity="low",
        )
        await kb.add_pattern(pattern, quality_score=1.0)
        assert pattern.pattern_id != ""
        assert len(pattern.pattern_id) == 12

    @pytest.mark.asyncio
    async def test_get_pattern_from_cache(self):
        kb = _make_kb()
        pattern = AnomalyPattern(
            pattern_id="cache_test", title="Cache", description="Test cache",
            resource_type="s3", severity="high",
        )
        await kb.add_pattern(pattern, quality_score=1.0)
        retrieved = await kb.get_pattern("cache_test")
        assert retrieved is not None
        assert retrieved.title == "Cache"

    @pytest.mark.asyncio
    async def test_get_nonexistent_pattern(self):
        kb = _make_kb()
        kb._cache_loaded = True
        retrieved = await kb.get_pattern("nonexistent")
        assert retrieved is None


# ─── Search Patterns ──────────────────────────────────────────────────────────

class TestSearchPatterns:
    @pytest.mark.asyncio
    async def test_search_by_resource_type(self):
        kb = _make_seeded_kb()
        results = await kb.search_patterns(resource_type="ec2")
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_search_by_severity(self):
        kb = _make_seeded_kb()
        results = await kb.search_patterns(severity="critical")
        assert len(results) >= 3

    @pytest.mark.asyncio
    async def test_search_by_keywords(self):
        kb = _make_seeded_kb()
        results = await kb.search_patterns(keywords=["public"])
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_search_combined_filters(self):
        kb = _make_seeded_kb()
        results = await kb.search_patterns(resource_type="s3", severity="critical")
        assert len(results) >= 1
        for r in results:
            assert r.resource_type == "s3"
            assert r.severity == "critical"

    @pytest.mark.asyncio
    async def test_search_limit(self):
        kb = _make_seeded_kb()
        results = await kb.search_patterns(limit=2)
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_search_no_match(self):
        kb = _make_seeded_kb()
        results = await kb.search_patterns(resource_type="nonexistent_service")
        assert len(results) == 0


# ─── Match Pattern (RCA) ─────────────────────────────────────────────────────

class TestMatchPattern:
    @pytest.mark.asyncio
    async def test_match_ec2_high_cpu(self):
        kb = _make_seeded_kb()
        issue = {
            "id": "issue-001",
            "resource_type": "ec2",
            "title": "EC2 High CPU",
            "description": "Instance showing high cpu utilization and performance degradation",
        }
        result = await kb.match_pattern(issue)
        assert isinstance(result, RCAResult)
        assert result.issue_id == "issue-001"
        if result.matched_pattern:
            assert result.matched_pattern.resource_type == "ec2"

    @pytest.mark.asyncio
    async def test_match_no_pattern_found(self):
        kb = _make_seeded_kb()
        issue = {
            "id": "issue-999",
            "resource_type": "unknown_service",
            "title": "Something completely unrelated",
            "description": "No symptoms match anything",
        }
        result = await kb.match_pattern(issue)
        assert result.issue_id == "issue-999"

    @pytest.mark.asyncio
    async def test_match_s3_public_bucket(self):
        kb = _make_seeded_kb()
        issue = {
            "id": "issue-002",
            "resource_type": "s3",
            "title": "S3 Public Bucket",
            "description": "bucket has public access enabled and acl public",
        }
        result = await kb.match_pattern(issue)
        if result.matched_pattern:
            assert result.matched_pattern.pattern_id == "s3_public_bucket"


# ─── Match Scoring ────────────────────────────────────────────────────────────

class TestMatchScoring:
    def test_resource_type_match(self):
        kb = _make_kb()
        issue = {"resource_type": "ec2", "title": "", "description": ""}
        pattern = AnomalyPattern(
            pattern_id="test", title="Test", description="",
            resource_type="ec2", severity="high", confidence=1.0,
        )
        score = kb._calculate_match_score(issue, pattern)
        assert score >= 0.3

    def test_title_overlap(self):
        kb = _make_kb()
        issue = {"resource_type": "ec2", "title": "High CPU Usage", "description": ""}
        pattern = AnomalyPattern(
            pattern_id="test", title="EC2 High CPU Utilization", description="",
            resource_type="ec2", severity="high", confidence=1.0,
        )
        score = kb._calculate_match_score(issue, pattern)
        assert score > 0.3

    def test_symptom_matching(self):
        kb = _make_kb()
        issue = {
            "resource_type": "ec2", "title": "CPU Issue",
            "description": "high cpu utilization and performance degradation",
        }
        pattern = AnomalyPattern(
            pattern_id="test", title="CPU Issue", description="",
            resource_type="ec2", severity="high",
            symptoms=["high cpu", "performance degradation"], confidence=1.0,
        )
        score = kb._calculate_match_score(issue, pattern)
        assert score > 0.5

    def test_confidence_scales_score(self):
        kb = _make_kb()
        issue = {"resource_type": "ec2", "title": "Test", "description": ""}
        high_conf = AnomalyPattern(
            pattern_id="high", title="Test", description="",
            resource_type="ec2", severity="high", confidence=1.0,
        )
        low_conf = AnomalyPattern(
            pattern_id="low", title="Test", description="",
            resource_type="ec2", severity="high", confidence=0.5,
        )
        assert kb._calculate_match_score(issue, high_conf) >= kb._calculate_match_score(issue, low_conf)

    def test_score_capped_at_one(self):
        kb = _make_kb()
        issue = {
            "resource_type": "ec2",
            "title": "EC2 High CPU Utilization",
            "description": "high cpu utilization cpu above 80 performance degradation",
        }
        pattern = AnomalyPattern(
            pattern_id="test", title="EC2 High CPU Utilization", description="",
            resource_type="ec2", severity="high",
            symptoms=["high cpu", "cpu utilization", "cpu above 80", "performance degradation"],
            confidence=1.0,
        )
        assert kb._calculate_match_score(issue, pattern) <= 1.0


# ─── S3 Storage ───────────────────────────────────────────────────────────────

class TestS3Storage:
    @pytest.mark.asyncio
    async def test_store_to_s3_calls_put_object(self):
        mock_client = MagicMock()
        kb = _make_kb(s3_client=mock_client)
        pattern = AnomalyPattern(
            pattern_id="s3_test", title="S3 Store", description="Test S3",
            resource_type="ec2", severity="high",
        )
        result = await kb._store_to_s3(pattern)
        assert result is True
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == S3_BUCKET_NAME
        assert "ec2/s3_test.json" in call_kwargs["Key"]

    @pytest.mark.asyncio
    async def test_store_to_s3_failure(self):
        mock_client = MagicMock()
        mock_client.put_object.side_effect = Exception("S3 error")
        kb = _make_kb(s3_client=mock_client)
        pattern = AnomalyPattern(
            pattern_id="fail_test", title="Fail", description="Should fail",
            resource_type="ec2", severity="high",
        )
        result = await kb._store_to_s3(pattern)
        assert result is False

    @pytest.mark.asyncio
    async def test_store_to_s3_no_client(self):
        kb = _make_kb(s3_client=None)
        pattern = AnomalyPattern(
            pattern_id="no_client", title="No Client", description="No S3",
            resource_type="ec2", severity="low",
        )
        result = await kb._store_to_s3(pattern)
        assert result is True  # local-only mode


# ─── KB Stats ─────────────────────────────────────────────────────────────────

class TestKBStats:
    def test_empty_stats(self):
        kb = _make_kb()
        stats = kb.get_stats()
        assert stats["total_patterns"] == 0
        assert stats["cache_loaded"] is False

    def test_stats_with_patterns(self):
        kb = _make_seeded_kb()
        stats = kb.get_stats()
        assert stats["total_patterns"] == 6
        assert "ec2" in stats["by_resource_type"]
        assert "critical" in stats["by_severity"]


# ─── Singleton ─────────────────────────────────────────────────────────────────

class TestGetKnowledgeBase:
    @pytest.mark.asyncio
    async def test_singleton_seeded(self):
        import src.s3_knowledge_base as kb_mod
        kb_mod._knowledge_base = None
        with patch("boto3.client"):
            kb = await get_knowledge_base()
            assert len(kb._local_cache) == len(DEFAULT_PATTERNS)
        kb_mod._knowledge_base = None

    @pytest.mark.asyncio
    async def test_singleton_returns_same(self):
        import src.s3_knowledge_base as kb_mod
        kb_mod._knowledge_base = None
        with patch("boto3.client"):
            kb1 = await get_knowledge_base()
            kb2 = await get_knowledge_base()
            assert kb1 is kb2
        kb_mod._knowledge_base = None
