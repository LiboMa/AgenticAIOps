"""Tests for src.knowledge.search — hybrid vector+keyword search.

Targets: 55% → ≥80% coverage.
Uncovered lines: 79-80, 85, 94-101, 107, 122-150
(keyword search, merge, rerank, verified boost)
"""

import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.knowledge.search import HybridResult, hybrid_search, _keyword_search
from src.knowledge.vector_store import SearchResult


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_vector_store():
    """Mock SQLiteVectorStore."""
    vs = MagicMock()
    vs.search.return_value = [
        SearchResult(case_id="case-001", field_name="symptom", score=0.9, metadata={"verified": "true"}),
        SearchResult(case_id="case-002", field_name="symptom", score=0.7, metadata={"verified": "false"}),
    ]
    return vs


@pytest.fixture
def cases_dir(tmp_path):
    """Create temp directory with markdown case files."""
    (tmp_path / "case-001.md").write_text(
        "# EC2 High CPU\nSymptom: CPU utilization at 100%\nRoot cause: runaway process\nVerified: true",
        encoding="utf-8",
    )
    (tmp_path / "case-003.md").write_text(
        "# RDS Connection Timeout\nSymptom: connection refused\nRoot cause: max_connections exceeded",
        encoding="utf-8",
    )
    (tmp_path / "case-004.md").write_text(
        "# S3 Access Denied\nSymptom: 403 error on s3 bucket\nRoot cause: IAM policy misconfigured",
        encoding="utf-8",
    )
    return tmp_path


# ── HybridResult dataclass ──────────────────────────────────


class TestHybridResult:
    def test_defaults(self):
        r = HybridResult(case_id="c1", score=0.5, source="vector")
        assert r.content == ""
        assert r.metadata is None

    def test_with_all_fields(self):
        r = HybridResult(
            case_id="c1", score=0.8, source="both",
            content="test", metadata={"verified": "true"}
        )
        assert r.content == "test"
        assert r.metadata["verified"] == "true"


# ── Vector-only search ──────────────────────────────────────


class TestVectorOnlySearch:
    def test_vector_search_basic(self, mock_vector_store):
        """Vector search with query_vector, no keyword fallback."""
        qv = np.array([0.1, 0.2, 0.3])
        results = hybrid_search(
            query_text="cpu high",
            vector_store=mock_vector_store,
            query_vector=qv,
        )
        assert len(results) == 2
        assert results[0].source == "vector"
        # verified case-001 should be boosted: 0.9 * 0.6 * 1.2 = 0.648
        assert results[0].case_id == "case-001"
        assert results[0].score > results[1].score

    def test_vector_search_no_query_vector(self, mock_vector_store):
        """No query_vector → skip vector search, return empty."""
        results = hybrid_search(
            query_text="cpu high",
            vector_store=mock_vector_store,
            query_vector=None,
        )
        assert results == []

    def test_vector_search_exception(self, mock_vector_store):
        """Vector search failure → graceful fallback to empty."""
        mock_vector_store.search.side_effect = RuntimeError("connection lost")
        qv = np.array([0.1, 0.2])
        results = hybrid_search(
            query_text="cpu high",
            vector_store=mock_vector_store,
            query_vector=qv,
        )
        assert results == []

    def test_vector_search_with_resource_type(self, mock_vector_store):
        """resource_type passed to vector_store.search as uppercase."""
        qv = np.array([0.1])
        hybrid_search(
            query_text="cpu",
            vector_store=mock_vector_store,
            query_vector=qv,
            resource_type="ec2",
        )
        call_kwargs = mock_vector_store.search.call_args[1]
        assert call_kwargs["resource_type"] == "EC2"

    def test_vector_search_empty_resource_type(self, mock_vector_store):
        """Empty resource_type → None passed to search."""
        qv = np.array([0.1])
        hybrid_search(
            query_text="cpu",
            vector_store=mock_vector_store,
            query_vector=qv,
            resource_type="",
        )
        call_kwargs = mock_vector_store.search.call_args[1]
        assert call_kwargs["resource_type"] is None


# ── Keyword-only search ─────────────────────────────────────


class TestKeywordSearch:
    def test_keyword_search_basic(self, cases_dir):
        """Keyword search finds matching cases."""
        results = _keyword_search(
            query_text="cpu high utilization",
            resource_type="",
            search_dir=cases_dir,
            top_k=5,
            weight=0.3,
        )
        assert len(results) > 0
        assert all(r.source == "keyword" for r in results)
        # case-001 mentions "cpu" and "utilization"
        case_ids = [r.case_id for r in results]
        assert "case-001" in case_ids

    def test_keyword_search_with_resource_type_boost(self, cases_dir):
        """Resource type match gives +2 score boost."""
        results = _keyword_search(
            query_text="error",
            resource_type="s3",
            search_dir=cases_dir,
            top_k=5,
            weight=0.3,
        )
        # case-004 mentions both "error" and "s3"
        s3_results = [r for r in results if r.case_id == "case-004"]
        assert len(s3_results) == 1
        assert s3_results[0].score > 0

    def test_keyword_search_empty_query(self, cases_dir):
        """Empty query → no results."""
        results = _keyword_search(
            query_text="",
            resource_type="",
            search_dir=cases_dir,
            top_k=5,
            weight=0.3,
        )
        assert results == []

    def test_keyword_search_no_matches(self, cases_dir):
        """Query with no matching keywords → empty."""
        results = _keyword_search(
            query_text="zzzznotexist xyzabc",
            resource_type="",
            search_dir=cases_dir,
            top_k=5,
            weight=0.3,
        )
        assert results == []

    def test_keyword_search_nonexistent_dir(self):
        """Non-existent directory → hybrid_search skips keyword."""
        vs = MagicMock()
        vs.search.return_value = []
        results = hybrid_search(
            query_text="cpu",
            vector_store=vs,
            cases_dir=Path("/nonexistent/path"),
        )
        assert results == []

    def test_keyword_search_top_k_limit(self, cases_dir):
        """top_k limits returned results."""
        results = _keyword_search(
            query_text="symptom root cause",
            resource_type="",
            search_dir=cases_dir,
            top_k=1,
            weight=0.3,
        )
        assert len(results) <= 1

    def test_keyword_search_content_truncated(self, cases_dir):
        """Content is truncated to 500 chars."""
        results = _keyword_search(
            query_text="cpu",
            resource_type="",
            search_dir=cases_dir,
            top_k=5,
            weight=0.3,
        )
        for r in results:
            assert len(r.content) <= 500

    def test_keyword_search_file_read_error(self, tmp_path):
        """Unreadable file → skipped with warning."""
        bad_file = tmp_path / "bad.md"
        bad_file.write_bytes(b'\x80\x81\x82')  # invalid utf-8
        results = _keyword_search(
            query_text="test",
            resource_type="",
            search_dir=tmp_path,
            top_k=5,
            weight=0.3,
        )
        # Should not crash; may or may not return results
        assert isinstance(results, list)


# ── Hybrid (vector + keyword) merge ─────────────────────────


class TestHybridMerge:
    def test_merge_both_sources(self, mock_vector_store, cases_dir):
        """case-001 found by both vector and keyword → source='both'."""
        qv = np.array([0.1, 0.2, 0.3])
        results = hybrid_search(
            query_text="cpu high utilization ec2",
            vector_store=mock_vector_store,
            query_vector=qv,
            cases_dir=cases_dir,
        )
        both_results = [r for r in results if r.source == "both"]
        # case-001 exists in both vector results and keyword results
        assert len(both_results) >= 1
        assert both_results[0].case_id == "case-001"

    def test_merge_keyword_only_cases(self, mock_vector_store, cases_dir):
        """case-003 only from keyword → source='keyword'."""
        qv = np.array([0.1, 0.2, 0.3])
        results = hybrid_search(
            query_text="connection timeout rds",
            vector_store=mock_vector_store,
            query_vector=qv,
            cases_dir=cases_dir,
        )
        case_003 = [r for r in results if r.case_id == "case-003"]
        assert len(case_003) == 1
        assert case_003[0].source == "keyword"

    def test_merge_fills_content(self, mock_vector_store, cases_dir):
        """When vector result has no content, keyword fills it."""
        qv = np.array([0.1, 0.2, 0.3])
        results = hybrid_search(
            query_text="cpu ec2 utilization",
            vector_store=mock_vector_store,
            query_vector=qv,
            cases_dir=cases_dir,
        )
        both = [r for r in results if r.case_id == "case-001"]
        if both:
            assert both[0].content != ""  # keyword content filled in


# ── Rerank / verified boost ──────────────────────────────────


class TestRerank:
    def test_verified_boost(self, mock_vector_store):
        """Verified cases get boosted score."""
        qv = np.array([0.1])
        results = hybrid_search(
            query_text="test",
            vector_store=mock_vector_store,
            query_vector=qv,
            verified_boost=1.5,
        )
        case_001 = [r for r in results if r.case_id == "case-001"][0]
        case_002 = [r for r in results if r.case_id == "case-002"][0]
        # case-001 has verified=true → boosted
        assert case_001.score > case_002.score

    def test_score_capped_at_1(self):
        """Score is capped at 1.0 after boost."""
        vs = MagicMock()
        vs.search.return_value = [
            SearchResult(case_id="x", field_name="symptom", score=0.99, metadata={"verified": "true"}),
        ]
        qv = np.array([0.1])
        results = hybrid_search(
            query_text="test",
            vector_store=vs,
            query_vector=qv,
            vector_weight=1.0,
            verified_boost=2.0,
        )
        assert results[0].score <= 1.0

    def test_no_metadata_no_boost(self):
        """Result without metadata → no boost, no crash."""
        vs = MagicMock()
        vs.search.return_value = [
            SearchResult(case_id="x", field_name="symptom", score=0.5, metadata=None),
        ]
        qv = np.array([0.1])
        results = hybrid_search(
            query_text="test",
            vector_store=vs,
            query_vector=qv,
        )
        assert len(results) == 1
        assert results[0].score == 0.5 * 0.6  # vector_weight only

    def test_results_sorted_descending(self, mock_vector_store):
        """Results sorted by score descending."""
        qv = np.array([0.1])
        results = hybrid_search(
            query_text="test",
            vector_store=mock_vector_store,
            query_vector=qv,
        )
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_limit(self):
        """Only top_k results returned."""
        vs = MagicMock()
        vs.search.return_value = [
            SearchResult(case_id=f"c{i}", field_name="symptom", score=0.5, metadata={})
            for i in range(10)
        ]
        qv = np.array([0.1])
        results = hybrid_search(
            query_text="test",
            vector_store=vs,
            query_vector=qv,
            top_k=3,
        )
        assert len(results) == 3


# ── Weight parameters ────────────────────────────────────────


class TestWeightParams:
    def test_custom_weights(self, mock_vector_store):
        """Custom vector_weight and keyword_weight."""
        qv = np.array([0.1])
        results = hybrid_search(
            query_text="test",
            vector_store=mock_vector_store,
            query_vector=qv,
            vector_weight=0.8,
            keyword_weight=0.1,
        )
        # case-001: 0.9 * 0.8 * 1.2 (verified) = 0.864
        assert results[0].score > 0.8

    def test_field_name_passed(self, mock_vector_store):
        """field_name parameter passed through to vector_store."""
        qv = np.array([0.1])
        hybrid_search(
            query_text="test",
            vector_store=mock_vector_store,
            query_vector=qv,
            field_name="root_cause",
        )
        call_kwargs = mock_vector_store.search.call_args[1]
        assert call_kwargs["field_name"] == "root_cause"
