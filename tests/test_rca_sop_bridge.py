"""
Tests for RCA ↔ SOP Bridge — pattern matching, feedback loop, suggestions.

Covers:
- RCASOPResult: to_dict, to_markdown
- SOPFeedback dataclass
- RCASOPBridge: match_sops, _find_matching_sops, analyze_and_suggest
- _extract_service, _extract_keywords, _sop_to_suggestion
- _auto_execute_sop, _calculate_bridge_confidence
- submit_feedback, _strengthen_pattern, get_feedback_stats, get_history
- Singleton: get_bridge
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.rca_sop_bridge import (
    RCASOPBridge,
    RCASOPResult,
    SOPFeedback,
    RCA_SOP_MAPPING,
    AUTO_EXECUTE_POLICY,
    get_bridge,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_rca_result(**overrides):
    """Create a mock RCA result."""
    rca = MagicMock()
    rca.pattern_id = overrides.get("pattern_id", "cpu-001")
    rca.pattern_name = overrides.get("pattern_name", "CPU Spike")
    rca.root_cause = overrides.get("root_cause", "High CPU utilization on i-abc123")
    rca.severity = MagicMock()
    rca.severity.value = overrides.get("severity", "high")
    rca.confidence = overrides.get("confidence", 0.85)
    rca.evidence = overrides.get("evidence", ["CPU > 90%"])
    rca.matched_symptoms = overrides.get("matched_symptoms", ["high_cpu"])
    return rca


def _make_sop(**overrides):
    """Create a mock SOP."""
    sop = MagicMock()
    sop.sop_id = overrides.get("sop_id", "sop-ec2-high-cpu")
    sop.name = overrides.get("name", "EC2 High CPU Response")
    sop.description = overrides.get("description", "Handle high CPU")
    sop.service = overrides.get("service", "ec2")
    sop.severity = overrides.get("severity", "high")
    step1 = MagicMock()
    step1.estimated_minutes = 5
    step2 = MagicMock()
    step2.estimated_minutes = 10
    sop.steps = overrides.get("steps", [step1, step2])
    return sop


# =============================================================================
# RCASOPResult Tests
# =============================================================================

class TestRCASOPResult:

    def test_to_dict(self):
        result = RCASOPResult(
            rca_pattern_id="cpu-001",
            root_cause="High CPU",
            severity="high",
            confidence=0.9,
            evidence=["CPU > 90%"],
            suggested_sops=[{"sop_id": "sop-1", "name": "Fix CPU"}],
        )
        d = result.to_dict()
        assert d["rca_pattern_id"] == "cpu-001"
        assert d["confidence"] == 0.9
        assert len(d["suggested_sops"]) == 1

    def test_to_markdown_basic(self):
        result = RCASOPResult(
            rca_pattern_id="cpu-001",
            root_cause="High CPU on instance",
            severity="high",
            confidence=0.85,
            evidence=["CPU > 90%", "Load avg > 10"],
        )
        md = result.to_markdown()
        assert "High CPU" in md
        assert "🔴" in md
        assert "cpu-001" in md
        assert "CPU > 90%" in md

    def test_to_markdown_with_sops(self):
        result = RCASOPResult(
            rca_pattern_id="cpu-001",
            root_cause="CPU issue",
            severity="medium",
            confidence=0.7,
            evidence=[],
            suggested_sops=[{
                "sop_id": "sop-ec2-high-cpu",
                "name": "EC2 High CPU",
                "steps": 5,
                "est_minutes": 30,
                "auto_execute": False,
            }],
        )
        md = result.to_markdown()
        assert "🟡" in md  # medium severity
        assert "sop-ec2-high-cpu" in md
        assert "sop run" in md

    def test_to_markdown_with_auto_executed(self):
        result = RCASOPResult(
            rca_pattern_id="pat-1",
            root_cause="Low severity issue",
            severity="low",
            confidence=0.9,
            evidence=[],
            auto_executed_sop="sop-test",
            execution_id="exec-123",
        )
        md = result.to_markdown()
        assert "🟢" in md
        assert "Auto-Executed" in md
        assert "sop-test" in md
        assert "exec-123" in md


# =============================================================================
# SOPFeedback Tests
# =============================================================================

class TestSOPFeedback:

    def test_creation(self):
        fb = SOPFeedback(
            execution_id="exec-1",
            sop_id="sop-1",
            rca_pattern_id="pat-1",
            success=True,
            resolution_time_seconds=120,
            steps_completed=5,
            steps_total=5,
            root_cause_confirmed=True,
            notes="Resolved quickly",
        )
        assert fb.success is True
        assert fb.resolution_time_seconds == 120
        assert fb.root_cause_confirmed is True


# =============================================================================
# RCASOPBridge — match_sops / _find_matching_sops
# =============================================================================

class TestMatchSops:

    def test_pattern_match(self):
        """Direct pattern ID match returns correct SOPs."""
        bridge = RCASOPBridge()
        rca = _make_rca_result(pattern_id="cpu-001")

        mock_store = MagicMock()
        mock_store.get_sop.return_value = _make_sop()
        mock_store.suggest_sops.return_value = []

        with patch("src.sop_system.get_sop_store", return_value=mock_store):
            results = bridge.match_sops(rca)

        assert len(results) >= 1
        assert results[0]["sop_id"] == "sop-ec2-high-cpu"
        assert results[0]["match_type"] == "pattern_match"
        assert results[0]["match_confidence"] == 0.9

    def test_keyword_match(self):
        """Keyword in root_cause triggers keyword match."""
        bridge = RCASOPBridge()
        rca = _make_rca_result(
            pattern_id="unknown-pattern",
            root_cause="Database connection failure detected"
        )

        mock_store = MagicMock()
        mock_sop = _make_sop(sop_id="sop-rds-failover", name="RDS Failover")
        mock_store.get_sop.return_value = mock_sop
        mock_store.suggest_sops.return_value = []

        with patch("src.sop_system.get_sop_store", return_value=mock_store):
            results = bridge.match_sops(rca)

        sop_ids = [r["sop_id"] for r in results]
        assert "sop-rds-failover" in sop_ids

    def test_healthy_pattern_returns_empty(self):
        """Healthy pattern maps to empty SOP list."""
        bridge = RCASOPBridge()
        rca = _make_rca_result(pattern_id="healthy", root_cause="No issues detected")

        mock_store = MagicMock()
        mock_store.get_sop.return_value = None
        mock_store.suggest_sops.return_value = []

        with patch("src.sop_system.get_sop_store", return_value=mock_store):
            results = bridge.match_sops(rca)

        assert len(results) == 0

    def test_learned_mapping_used(self):
        """Historical success map boosts SOP suggestions."""
        bridge = RCASOPBridge()
        bridge._success_map = {"pat-custom": {"sop-ec2-high-cpu": 5}}

        rca = _make_rca_result(pattern_id="pat-custom", root_cause="custom issue")

        mock_store = MagicMock()
        mock_store.get_sop.return_value = _make_sop()
        mock_store.suggest_sops.return_value = []

        with patch("src.sop_system.get_sop_store", return_value=mock_store):
            results = bridge.match_sops(rca)

        learned = [r for r in results if r["match_type"] == "learned"]
        assert len(learned) >= 1
        assert learned[0]["match_confidence"] >= 0.6

    def test_max_5_results(self):
        """Results capped at 5."""
        bridge = RCASOPBridge()
        rca = _make_rca_result(root_cause="cpu memory disk database throttle storage lambda error")

        mock_store = MagicMock()
        mock_store.get_sop.return_value = _make_sop()
        mock_store.suggest_sops.return_value = [_make_sop(sop_id=f"sop-extra-{i}") for i in range(5)]

        with patch("src.sop_system.get_sop_store", return_value=mock_store):
            results = bridge.match_sops(rca)

        assert len(results) <= 5

    def test_sorted_by_confidence(self):
        """Results sorted by match_confidence descending."""
        bridge = RCASOPBridge()
        rca = _make_rca_result(pattern_id="cpu-001", root_cause="high cpu disk full")

        mock_store = MagicMock()
        sop1 = _make_sop(sop_id="sop-ec2-high-cpu")
        sop2 = _make_sop(sop_id="sop-ec2-disk-full")
        mock_store.get_sop.side_effect = lambda sid: sop1 if "cpu" in sid else sop2
        mock_store.suggest_sops.return_value = []

        with patch("src.sop_system.get_sop_store", return_value=mock_store):
            results = bridge.match_sops(rca)

        if len(results) >= 2:
            assert results[0]["match_confidence"] >= results[1]["match_confidence"]


# =============================================================================
# _sop_to_suggestion
# =============================================================================

class TestSopToSuggestion:

    def test_basic_conversion(self):
        bridge = RCASOPBridge()
        sop = _make_sop()
        result = bridge._sop_to_suggestion(sop, "pattern_match", 0.9)

        assert result["sop_id"] == "sop-ec2-high-cpu"
        assert result["name"] == "EC2 High CPU Response"
        assert result["steps"] == 2
        assert result["est_minutes"] == 15  # 5 + 10
        assert result["match_type"] == "pattern_match"
        assert result["match_confidence"] == 0.9


# =============================================================================
# _extract_service / _extract_keywords
# =============================================================================

class TestExtractors:

    def test_extract_service_ec2(self):
        bridge = RCASOPBridge()
        rca = _make_rca_result(root_cause="EC2 instance high CPU", pattern_name="CPU Spike")
        assert bridge._extract_service(rca) == "ec2"

    def test_extract_service_rds(self):
        bridge = RCASOPBridge()
        rca = _make_rca_result(root_cause="RDS database connection failure", pattern_name="DB Issue")
        assert bridge._extract_service(rca) == "rds"

    def test_extract_service_lambda(self):
        bridge = RCASOPBridge()
        rca = _make_rca_result(root_cause="Lambda function timeout", pattern_name="Timeout")
        assert bridge._extract_service(rca) == "lambda"

    def test_extract_service_none(self):
        bridge = RCASOPBridge()
        rca = _make_rca_result(root_cause="Unknown issue", pattern_name="Unknown")
        assert bridge._extract_service(rca) is None

    def test_extract_keywords(self):
        bridge = RCASOPBridge()
        rca = _make_rca_result(
            root_cause="High CPU with memory leak causing timeout",
            matched_symptoms=["cpu_spike", "oom"]
        )
        keywords = bridge._extract_keywords(rca)
        assert "high" in keywords
        assert "cpu" in keywords
        assert "memory" in keywords
        assert "timeout" in keywords


# =============================================================================
# _auto_execute_sop
# =============================================================================

class TestAutoExecuteSop:

    def test_auto_execute_success(self):
        bridge = RCASOPBridge()
        rca = _make_rca_result()

        mock_executor = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-auto-001"
        mock_executor.start_execution.return_value = mock_execution

        with patch("src.sop_system.get_sop_executor", return_value=mock_executor):
            result = bridge._auto_execute_sop("sop-test", rca)

        assert result is not None
        assert result.execution_id == "exec-auto-001"

    def test_auto_execute_failure(self):
        bridge = RCASOPBridge()
        rca = _make_rca_result()

        with patch("src.sop_system.get_sop_executor", side_effect=Exception("executor down")):
            result = bridge._auto_execute_sop("sop-test", rca)

        assert result is None


# =============================================================================
# _calculate_bridge_confidence
# =============================================================================

class TestBridgeConfidence:

    def test_no_sops_returns_zero(self):
        bridge = RCASOPBridge()
        assert bridge._calculate_bridge_confidence("pat-1", []) == 0.0

    def test_returns_best_match(self):
        bridge = RCASOPBridge()
        sops = [
            {"match_confidence": 0.9},
            {"match_confidence": 0.7},
        ]
        assert bridge._calculate_bridge_confidence("pat-1", sops) == 0.9

    def test_history_boost(self):
        bridge = RCASOPBridge()
        bridge._success_map = {"pat-1": {"sop-1": 3}}
        sops = [{"match_confidence": 0.8}]
        result = bridge._calculate_bridge_confidence("pat-1", sops)
        assert result > 0.8  # Should be boosted
        assert result <= 1.0


# =============================================================================
# submit_feedback / _strengthen_pattern
# =============================================================================

class TestFeedback:

    def test_submit_success_feedback(self):
        bridge = RCASOPBridge()
        fb = bridge.submit_feedback(
            execution_id="exec-1",
            sop_id="sop-ec2-high-cpu",
            rca_pattern_id="cpu-001",
            success=True,
            resolution_time_seconds=120,
        )

        assert fb.success is True
        assert len(bridge._feedbacks) == 1
        assert bridge._success_map["cpu-001"]["sop-ec2-high-cpu"] == 1

    def test_submit_multiple_success_accumulates(self):
        bridge = RCASOPBridge()
        bridge.submit_feedback("e1", "sop-1", "pat-1", success=True)
        bridge.submit_feedback("e2", "sop-1", "pat-1", success=True)
        bridge.submit_feedback("e3", "sop-1", "pat-1", success=True)

        assert bridge._success_map["pat-1"]["sop-1"] == 3

    def test_submit_failure_no_success_map(self):
        bridge = RCASOPBridge()
        bridge.submit_feedback("e1", "sop-1", "pat-1", success=False)

        assert "pat-1" not in bridge._success_map
        assert len(bridge._feedbacks) == 1

    def test_confirmed_root_cause_strengthens_pattern(self):
        bridge = RCASOPBridge()

        mock_engine = MagicMock()
        mock_pattern = MagicMock()
        mock_pattern.confidence = 0.8
        mock_engine.matcher.get_pattern.return_value = mock_pattern

        with patch("src.rca.engine.RCAEngine", return_value=mock_engine):
            bridge.submit_feedback(
                "e1", "sop-1", "pat-1",
                success=True,
                root_cause_confirmed=True,
            )

        assert mock_pattern.confidence == pytest.approx(0.85)  # +0.05

    def test_strengthen_pattern_exception_swallowed(self):
        bridge = RCASOPBridge()

        with patch("src.rca.engine.RCAEngine", side_effect=Exception("engine fail")):
            # Should not raise
            bridge._strengthen_pattern("pat-1")


# =============================================================================
# get_feedback_stats / get_history
# =============================================================================

class TestStats:

    def test_feedback_stats_empty(self):
        bridge = RCASOPBridge()
        stats = bridge.get_feedback_stats()
        assert stats["total_feedbacks"] == 0
        assert stats["success_rate"] == 0

    def test_feedback_stats_with_data(self):
        bridge = RCASOPBridge()
        bridge.submit_feedback("e1", "sop-1", "pat-1", success=True, resolution_time_seconds=100)
        bridge.submit_feedback("e2", "sop-2", "pat-2", success=False)
        bridge.submit_feedback("e3", "sop-1", "pat-1", success=True, resolution_time_seconds=200, root_cause_confirmed=True)

        stats = bridge.get_feedback_stats()
        assert stats["total_feedbacks"] == 3
        assert stats["successful"] == 2
        assert stats["failed"] == 1
        assert stats["root_cause_confirmed"] == 1
        assert stats["success_rate"] == pytest.approx(2/3)
        assert stats["avg_resolution_seconds"] == 150  # (100+200)/2

    def test_get_history_empty(self):
        bridge = RCASOPBridge()
        assert bridge.get_history() == []

    def test_get_history_with_limit(self):
        bridge = RCASOPBridge()
        for i in range(5):
            bridge._execution_history[f"ts-{i}"] = RCASOPResult(
                rca_pattern_id=f"pat-{i}",
                root_cause=f"Issue {i}",
                severity="high",
                confidence=0.8,
                evidence=[],
            )
        result = bridge.get_history(limit=3)
        assert len(result) == 3


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:

    def test_get_bridge_singleton(self):
        import src.rca_sop_bridge as mod
        mod._bridge = None

        b1 = get_bridge()
        b2 = get_bridge()
        assert b1 is b2

        mod._bridge = None  # cleanup


# =============================================================================
# Mapping Constants
# =============================================================================

class TestMappingConstants:

    def test_rca_sop_mapping_has_core_patterns(self):
        assert "cpu-001" in RCA_SOP_MAPPING
        assert "healthy" in RCA_SOP_MAPPING
        assert RCA_SOP_MAPPING["healthy"] == []

    def test_auto_execute_policy(self):
        assert AUTO_EXECUTE_POLICY["low"] is True
        assert AUTO_EXECUTE_POLICY["high"] is False
        assert AUTO_EXECUTE_POLICY["medium"] is False
