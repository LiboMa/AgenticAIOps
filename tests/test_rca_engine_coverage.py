"""
Tests to boost rca/engine.py coverage from 81% → 90%+.

Targets 30 uncovered lines across:
- Lazy-load ACI/Voting properties (L64-68, L78-79)
- analyze() high-confidence + voting fallback paths (L110, L127-133)
- _collect_telemetry ACI success + exception paths (L309-310, L333-347, L358)
- _voting_analysis full path (L406-426)
- _generate_analysis CrashLoop branch (L446)
- get_pattern (L473)
"""

import pytest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

from src.rca.engine import RCAEngine
from src.rca.models import RCAResult, Severity, Remediation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(confidence: float = 0.9, pattern_id: str = "test-001") -> RCAResult:
    return RCAResult(
        pattern_id=pattern_id,
        pattern_name="Test Pattern",
        root_cause="test root cause",
        severity=Severity.MEDIUM,
        confidence=confidence,
        matched_symptoms=["symptom1"],
        remediation=Remediation(action="test", auto_execute=False),
        evidence=["evidence1"],
    )


class _FakeACIResult:
    """Minimal ACI result stub."""
    def __init__(self, data=None, success=True):
        self.data = data
        self.status = MagicMock()
        self.status.value = "success" if success else "error"


# ===========================================================================
# Lazy-load property tests  (L64-68, L78-79)
# ===========================================================================

class TestLazyLoadProperties:
    """Cover the ImportError branches in aci / voting properties."""

    def test_aci_lazy_load_import_error(self):
        """L64-68: ACI lazy-load falls back to None on ImportError."""
        engine = RCAEngine()
        with patch.dict("sys.modules", {"src.aci": None}):
            # Force reimport failure
            with patch("builtins.__import__", side_effect=ImportError("no aci")):
                result = engine.aci
        assert result is None

    def test_voting_lazy_load_import_error(self):
        """L78-79: Voting lazy-load falls back to None on ImportError."""
        engine = RCAEngine()
        with patch("builtins.__import__", side_effect=ImportError("no voting")):
            result = engine.voting
        assert result is None

    def test_aci_lazy_load_success(self):
        """ACI lazy-load succeeds when module is available."""
        engine = RCAEngine()
        mock_aci = MagicMock()
        with patch("src.rca.engine.AgentCloudInterface", mock_aci, create=True):
            with patch.dict("sys.modules", {"src.aci": MagicMock(AgentCloudInterface=mock_aci)}):
                # Reset to force lazy load
                engine._aci = None
                # Directly patch the import inside the property
                with patch("builtins.__import__") as mock_import:
                    mock_module = MagicMock()
                    mock_module.AgentCloudInterface = mock_aci
                    mock_import.return_value = mock_module
                    result = engine.aci
        # Should have attempted to create an instance
        assert result is not None or engine._aci is not None


# ===========================================================================
# analyze() paths  (L110, L127-133)
# ===========================================================================

class TestAnalyzeVotingFallback:
    """Cover the voting fallback logic in analyze()."""

    def test_high_confidence_pattern_match_returns_early(self):
        """L110: High-confidence match (>=0.85) returns immediately."""
        engine = RCAEngine()
        high_conf_result = _make_result(confidence=0.90, pattern_id="oom-001")
        # Ensure bool(result) is True and confidence >= 0.85
        assert high_conf_result.confidence >= 0.85
        engine.matcher = MagicMock()
        engine.matcher.match.return_value = high_conf_result

        result = engine.analyze(namespace="test-ns", telemetry={"events": [], "metrics": {}, "logs": []})

        assert result is high_conf_result
        assert result.pattern_id == "oom-001"
        assert result.confidence == 0.90

    def test_voting_fallback_when_pattern_low_confidence(self):
        """L127-133: Low pattern confidence triggers voting; voting wins if higher."""
        engine = RCAEngine()
        low_conf_result = _make_result(confidence=0.5, pattern_id="low-conf")

        engine.matcher = MagicMock()
        engine.matcher.match.return_value = low_conf_result

        # Set up a real voting mock that returns consensus
        mock_voting = MagicMock()
        from src.voting import VotingResult, TaskType, Vote
        consensus_result = VotingResult(
            task_type=TaskType.ANALYSIS,
            query="test",
            votes=[],
            final_answer="Network partition detected",
            total_score=0.80,
            consensus=True,
            agreement_ratio=0.80,
            metadata={},
        )
        mock_voting.vote.return_value = consensus_result
        engine._voting = mock_voting

        result = engine.analyze(
            namespace="test-ns",
            telemetry={"events": [{"reason": "NodeNotReady"}], "metrics": {}, "logs": []},
        )

        # Voting result (confidence=0.80) > pattern result (0.50) → voting wins
        assert result.pattern_id == "voting-analysis"
        assert result.confidence == 0.80

    def test_voting_fallback_when_no_pattern_match(self):
        """L127-133: No pattern match → voting fallback."""
        engine = RCAEngine()
        engine.matcher = MagicMock()
        engine.matcher.match.return_value = None

        # Use real voting mock
        mock_voting = MagicMock()
        from src.voting import VotingResult, TaskType
        consensus_result = VotingResult(
            task_type=TaskType.ANALYSIS,
            query="test",
            votes=[],
            final_answer="OOM detected",
            total_score=0.75,
            consensus=True,
            agreement_ratio=0.75,
            metadata={},
        )
        mock_voting.vote.return_value = consensus_result
        engine._voting = mock_voting

        result = engine.analyze(
            namespace="test-ns",
            telemetry={"events": [{"reason": "OOMKilled"}], "metrics": {}, "logs": []},
        )

        assert result.pattern_id == "voting-analysis"

    def test_analyze_collects_telemetry_then_votes(self):
        """L309-310 + L132-133: Full path — collect telemetry via ACI → low-conf pattern → voting wins."""
        mock_aci = MagicMock()
        mock_aci.get_events.return_value = _FakeACIResult(
            data=[{"reason": "NodeNotReady", "message": "node down"}]
        )
        mock_aci.get_metrics.return_value = _FakeACIResult(data={"cpu": 0.9})

        mock_voting = MagicMock()
        from src.voting import VotingResult, TaskType
        mock_voting.vote.return_value = VotingResult(
            task_type=TaskType.ANALYSIS, query="test", votes=[],
            final_answer="Node failure", total_score=0.85,
            consensus=True, agreement_ratio=0.85, metadata={},
        )

        engine = RCAEngine(aci=mock_aci, voting=mock_voting)
        # Pattern matcher returns low confidence
        engine.matcher = MagicMock()
        engine.matcher.match.return_value = _make_result(confidence=0.4, pattern_id="low-pat")

        # Don't pass telemetry → forces _collect_telemetry (L309-310)
        result = engine.analyze(namespace="test-ns")

        assert result.pattern_id == "voting-analysis"
        assert result.confidence == 0.85
        mock_aci.get_events.assert_called_once()

    def test_voting_lower_than_pattern_keeps_pattern(self):
        """Voting returns lower confidence → keep pattern result."""
        engine = RCAEngine()
        pattern_result = _make_result(confidence=0.70, pattern_id="pattern-mid")

        engine.matcher = MagicMock()
        engine.matcher.match.return_value = pattern_result
        engine._voting = MagicMock()

        with patch.object(engine, '_voting_analysis') as mock_va:
            mock_va.return_value = _make_result(confidence=0.50, pattern_id="voting-low")

            result = engine.analyze(
                namespace="test-ns",
                telemetry={"events": [], "metrics": {}, "logs": []},
            )

        assert result.pattern_id == "pattern-mid"


# ===========================================================================
# _collect_telemetry  (L309-310, L333-347, L358)
# ===========================================================================

class TestCollectTelemetry:
    """Cover ACI data collection paths."""

    def test_collect_events_and_metrics_success(self):
        """L309-310, L333-340: ACI returns events + metrics successfully."""
        mock_aci = MagicMock()
        mock_aci.get_events.return_value = _FakeACIResult(
            data=[{"reason": "OOMKilled", "message": "OOM"}]
        )
        mock_aci.get_metrics.return_value = _FakeACIResult(
            data={"cpu_usage": 0.8}
        )

        engine = RCAEngine(aci=mock_aci)
        telemetry = engine._collect_telemetry("test-ns", pod=None)

        assert len(telemetry["events"]) == 1
        assert telemetry["metrics"]["cpu_usage"] == 0.8
        assert telemetry["logs"] == []

    def test_collect_with_pod_logs(self):
        """L341-347: When pod is specified, logs are collected."""
        mock_aci = MagicMock()
        mock_aci.get_events.return_value = _FakeACIResult(data=[])
        mock_aci.get_metrics.return_value = _FakeACIResult(data={})
        mock_aci.get_logs.return_value = _FakeACIResult(
            data=[{"message": "error log 1"}, {"message": "error log 2"}]
        )

        engine = RCAEngine(aci=mock_aci)
        telemetry = engine._collect_telemetry("test-ns", pod="web-pod-1")

        assert len(telemetry["logs"]) == 2
        assert "error log 1" in telemetry["logs"]

    def test_collect_logs_fallback_to_str(self):
        """L341-347: Logs without 'message' key fall back to str(log)."""
        mock_aci = MagicMock()
        mock_aci.get_events.return_value = _FakeACIResult(data=[])
        mock_aci.get_metrics.return_value = _FakeACIResult(data={})
        mock_aci.get_logs.return_value = _FakeACIResult(
            data=[{"level": "error", "detail": "something broke"}]
        )

        engine = RCAEngine(aci=mock_aci)
        telemetry = engine._collect_telemetry("test-ns", pod="web-pod-1")

        assert len(telemetry["logs"]) == 1
        # Falls back to str(log)
        assert "something broke" in telemetry["logs"][0]

    def test_collect_telemetry_exception(self):
        """L358: ACI raises exception → empty telemetry, no crash."""
        mock_aci = MagicMock()
        mock_aci.get_events.side_effect = RuntimeError("ACI connection failed")

        engine = RCAEngine(aci=mock_aci)
        telemetry = engine._collect_telemetry("test-ns", pod=None)

        assert telemetry["events"] == []
        assert telemetry["metrics"] == {}
        assert telemetry["logs"] == []

    def test_collect_events_none_data(self):
        """ACI returns success but data=None → default to empty list."""
        mock_aci = MagicMock()
        mock_aci.get_events.return_value = _FakeACIResult(data=None)
        mock_aci.get_metrics.return_value = _FakeACIResult(data=None)

        engine = RCAEngine(aci=mock_aci)
        telemetry = engine._collect_telemetry("test-ns", pod=None)

        assert telemetry["events"] == []
        assert telemetry["metrics"] == {}


# ===========================================================================
# _voting_analysis  (L406-426)
# ===========================================================================

class TestVotingAnalysis:
    """Cover the full voting analysis path."""

    def test_voting_analysis_with_consensus(self):
        """L406-426: Full voting path with consensus."""
        mock_voting = MagicMock()
        voting_result = MagicMock()
        voting_result.consensus = True
        voting_result.final_answer = "Memory exhaustion issue - OOMKilled detected"
        voting_result.agreement_ratio = 0.85
        mock_voting.vote.return_value = voting_result

        engine = RCAEngine(voting=mock_voting)

        telemetry = {
            "events": [{"reason": "OOMKilled", "message": "OOM"}],
            "metrics": {"cpu_usage": 0.9},
            "logs": ["error: out of memory"],
        }

        result = engine._voting_analysis(telemetry, "test-ns")

        assert result is not None
        assert result.pattern_id == "voting-analysis"
        assert result.confidence == 0.85
        assert "OOMKilled" in result.root_cause

    def test_voting_analysis_no_consensus(self):
        """Voting returns no consensus → None."""
        mock_voting = MagicMock()
        voting_result = MagicMock()
        voting_result.consensus = False
        mock_voting.vote.return_value = voting_result

        engine = RCAEngine(voting=mock_voting)
        telemetry = {"events": [], "metrics": {}, "logs": []}

        result = engine._voting_analysis(telemetry, "test-ns")
        assert result is None

    def test_voting_analysis_exception(self):
        """Voting raises exception → None, no crash."""
        mock_voting = MagicMock()
        mock_voting.vote.side_effect = RuntimeError("voting failed")

        engine = RCAEngine(voting=mock_voting)
        telemetry = {"events": [], "metrics": {}, "logs": []}

        result = engine._voting_analysis(telemetry, "test-ns")
        assert result is None

    def test_voting_analysis_no_voting(self):
        """No voting instance → None."""
        engine = RCAEngine()
        engine._voting = None
        # Also prevent lazy-load
        with patch.object(type(engine), 'voting', new_callable=PropertyMock, return_value=None):
            result = engine._voting_analysis({"events": [], "metrics": {}, "logs": []}, "test-ns")
        assert result is None


# ===========================================================================
# _generate_analysis branches  (L446)
# ===========================================================================

class TestGenerateAnalysis:
    """Cover heuristic analysis branches."""

    def test_crashloop_backoff(self):
        """L446: CrashLoop/BackOff branch."""
        engine = RCAEngine()
        telemetry = {"events": [{"reason": "CrashLoopBackOff", "message": "crash"}]}
        result = engine._generate_analysis("developer", telemetry)
        assert "crash loop" in result.lower()

    def test_backoff_variant(self):
        """L446: BackOff variant."""
        engine = RCAEngine()
        telemetry = {"events": [{"reason": "BackOff", "message": "restarting"}]}
        result = engine._generate_analysis("tester", telemetry)
        assert "crash loop" in result.lower() or "startup failure" in result.lower()

    def test_image_pull_branch(self):
        """ImagePull branch — use reason without BackOff to avoid CrashLoop match first."""
        engine = RCAEngine()
        telemetry = {"events": [{"reason": "ErrImagePull", "message": "pull error"}]}
        result = engine._generate_analysis("architect", telemetry)
        assert "image" in result.lower()

    def test_node_branch(self):
        """Node-level issue branch."""
        engine = RCAEngine()
        telemetry = {"events": [{"reason": "NodeNotReady", "message": "node down"}]}
        result = engine._generate_analysis("developer", telemetry)
        assert "node" in result.lower()

    def test_no_matching_reason(self):
        """No matching reason → fallback."""
        engine = RCAEngine()
        telemetry = {"events": [{"reason": "Unknown", "message": "something"}]}
        result = engine._generate_analysis("tester", telemetry)
        assert "unable to determine" in result.lower()

    def test_empty_events(self):
        """Empty events → fallback."""
        engine = RCAEngine()
        telemetry = {"events": []}
        result = engine._generate_analysis("developer", telemetry)
        assert "unable to determine" in result.lower()


# ===========================================================================
# _infer_severity
# ===========================================================================

class TestInferSeverity:
    """Cover severity inference branches."""

    def test_high_severity_keywords(self):
        engine = RCAEngine()
        assert engine._infer_severity("Node unreachable, network partition") == Severity.HIGH
        assert engine._infer_severity("PVC mount failure critical") == Severity.HIGH

    def test_low_severity_keywords(self):
        engine = RCAEngine()
        assert engine._infer_severity("Pod eviction due to cleanup") == Severity.LOW
        assert engine._infer_severity("CPU throttling detected") == Severity.LOW

    def test_medium_severity_default(self):
        engine = RCAEngine()
        assert engine._infer_severity("Some generic issue") == Severity.MEDIUM


# ===========================================================================
# get_pattern  (L473)
# ===========================================================================

class TestGetPattern:
    """Cover get_pattern wrapper."""

    def test_get_pattern_delegates_to_matcher(self):
        """L473: get_pattern delegates to matcher."""
        engine = RCAEngine()
        engine.matcher = MagicMock()
        engine.matcher.get_pattern.return_value = {"id": "oom-001"}

        result = engine.get_pattern("oom-001")
        assert result["id"] == "oom-001"
        engine.matcher.get_pattern.assert_called_once_with("oom-001")

    def test_get_patterns_delegates_to_matcher(self):
        """get_patterns delegates to matcher.list_patterns."""
        engine = RCAEngine()
        engine.matcher = MagicMock()
        engine.matcher.list_patterns.return_value = [{"id": "p1"}, {"id": "p2"}]

        result = engine.get_patterns()
        assert len(result) == 2
