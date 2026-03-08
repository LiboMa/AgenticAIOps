"""
Tests for RCA Pattern Module
"""

import pytest
import tempfile
from pathlib import Path

from src.rca import (
    Pattern, RCAResult, Severity, Remediation, Symptom,
    PatternMatcher, RCAEngine
)


class TestRCAModels:
    """Tests for RCA data models."""
    
    def test_severity_enum(self):
        """Test severity enum values."""
        assert Severity.LOW.value == "low"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.HIGH.value == "high"
    
    def test_remediation_creation(self):
        """Test remediation model."""
        rem = Remediation(
            action="increase_memory_limit",
            auto_execute=True,
            params={"increase_ratio": 1.5}
        )
        
        assert rem.action == "increase_memory_limit"
        assert rem.auto_execute is True
        assert rem.params["increase_ratio"] == 1.5
    
    def test_rca_result_to_dict(self):
        """Test RCA result serialization."""
        result = RCAResult(
            pattern_id="oom-001",
            pattern_name="OOM Kill",
            root_cause="Memory limit too low",
            severity=Severity.MEDIUM,
            confidence=0.9,
            matched_symptoms=["OOMKilled"],
            remediation=Remediation(action="increase_memory", auto_execute=True),
            evidence=["Event: OOMKilled"]
        )
        
        data = result.to_dict()
        
        assert data["pattern_id"] == "oom-001"
        assert data["severity"] == "medium"
        assert data["remediation"]["auto_execute"] is True
    
    def test_should_auto_fix_low_severity(self):
        """Test auto-fix for low severity."""
        result = RCAResult(
            pattern_id="cpu-001",
            pattern_name="CPU Throttling",
            root_cause="CPU limit too low",
            severity=Severity.LOW,
            confidence=0.8,
            matched_symptoms=["Throttled"],
            remediation=Remediation(action="increase_cpu", auto_execute=True),
        )
        
        assert result.should_auto_fix() is True
    
    def test_should_not_auto_fix_high_severity(self):
        """Test no auto-fix for high severity."""
        result = RCAResult(
            pattern_id="node-001",
            pattern_name="Node NotReady",
            root_cause="Node failure",
            severity=Severity.HIGH,
            confidence=0.9,
            matched_symptoms=["NodeNotReady"],
            remediation=Remediation(action="manual_review", auto_execute=False),
        )
        
        assert result.should_auto_fix() is False
    
    def test_should_not_auto_fix_low_confidence(self):
        """Test no auto-fix for low confidence."""
        result = RCAResult(
            pattern_id="unknown",
            pattern_name="Unknown",
            root_cause="Unknown issue",
            severity=Severity.MEDIUM,
            confidence=0.5,  # Below 0.7 threshold
            matched_symptoms=[],
            remediation=Remediation(action="restart", auto_execute=True),
        )
        
        assert result.should_auto_fix() is False


class TestPatternMatcher:
    """Tests for PatternMatcher."""
    
    @pytest.fixture
    def matcher(self):
        """Create matcher with default config."""
        return PatternMatcher()
    
    def test_patterns_loaded(self, matcher):
        """Test that patterns are loaded from config."""
        patterns = matcher.list_patterns()
        assert len(patterns) >= 7  # We defined 7 patterns
    
    def test_get_pattern(self, matcher):
        """Test getting pattern by ID."""
        pattern = matcher.get_pattern("oom-001")
        
        assert pattern is not None
        assert pattern.name == "OOM Kill - Memory Limit"
        assert pattern.severity == Severity.MEDIUM
    
    def test_match_oom_event(self, matcher):
        """Test matching OOMKilled event."""
        telemetry = {
            "events": [{"reason": "OOMKilled", "type": "Warning", "message": "Container killed"}],
            "metrics": {},
            "logs": []
        }
        
        result = matcher.match(telemetry)
        
        assert result is not None
        assert result.pattern_id == "oom-001"
        assert result.severity == Severity.MEDIUM
        assert result.remediation.auto_execute is True
    
    def test_match_crashloop_event(self, matcher):
        """Test matching CrashLoopBackOff event."""
        telemetry = {
            "events": [{"reason": "CrashLoopBackOff", "message": "Back-off restarting"}],
            "metrics": {},
            "logs": []
        }
        
        result = matcher.match(telemetry)
        
        assert result is not None
        assert result.pattern_id == "crash-001"
    
    def test_match_imagepull_event(self, matcher):
        """Test matching ImagePullBackOff event."""
        telemetry = {
            "events": [{"reason": "ImagePullBackOff", "message": "Failed to pull image"}],
            "metrics": {},
            "logs": []
        }
        
        result = matcher.match(telemetry)
        
        assert result is not None
        assert result.pattern_id == "image-001"
        assert result.severity == Severity.HIGH
        assert result.remediation.auto_execute is False  # Manual review required
    
    def test_match_node_notready(self, matcher):
        """Test matching NodeNotReady event."""
        telemetry = {
            "events": [{"reason": "NodeNotReady", "message": "Node is not ready"}],
            "metrics": {},
            "logs": []
        }
        
        result = matcher.match(telemetry)
        
        assert result is not None
        assert result.pattern_id == "node-001"
        assert result.severity == Severity.HIGH
    
    def test_no_match_unknown_event(self, matcher):
        """Test no match for unknown event."""
        telemetry = {
            "events": [{"reason": "SomeUnknownEvent", "message": "Unknown"}],
            "metrics": {},
            "logs": []
        }
        
        result = matcher.match(telemetry)
        
        # Should not match any pattern
        assert result is None
    
    def test_match_log_pattern(self, matcher):
        """Test matching via log pattern when event also matches."""
        telemetry = {
            "events": [{"message": "connection refused to service"}],
            "metrics": {},
            "logs": ["Connection refused to backend service"]
        }
        
        result = matcher.match(telemetry)
        
        assert result is not None
        assert result.pattern_id == "network-001"
    
    def test_evidence_collection(self, matcher):
        """Test that evidence is collected during match."""
        telemetry = {
            "events": [{"reason": "OOMKilled", "message": "Container killed due to OOM"}],
            "metrics": {},
            "logs": []
        }
        
        result = matcher.match(telemetry)
        
        assert result is not None
        assert len(result.evidence) > 0


class TestRCAEngine:
    """Tests for RCAEngine."""
    
    @pytest.fixture
    def engine(self):
        """Create engine without ACI/Voting for unit tests."""
        return RCAEngine()
    
    def test_analyze_from_symptoms_oom(self, engine):
        """Test analyzing OOM symptoms."""
        result = engine.analyze_from_symptoms(["OOMKilled", "high memory usage"])
        
        assert result is not None
        assert result.pattern_id == "oom-001"
    
    def test_analyze_from_symptoms_crashloop(self, engine):
        """Test analyzing crashloop symptoms."""
        result = engine.analyze_from_symptoms(["CrashLoopBackOff"])
        
        assert result is not None
        assert result.pattern_id == "crash-001"
    
    def test_analyze_from_symptoms_unknown(self, engine):
        """Test analyzing unknown symptoms — voting engine may return consensus."""
        result = engine.analyze_from_symptoms(["some_random_symptom"])
        
        assert result is not None
        # Voting engine may reach consensus even for random symptoms
        assert result.pattern_id in ("unknown", "voting-analysis")
    
    def test_analyze_event(self, engine):
        """Test analyzing a single event."""
        event = {
            "reason": "OOMKilled",
            "message": "Container killed",
            "namespace": "test",
        }
        
        result = engine.analyze_event(event)
        
        assert result is not None
        assert result.pattern_id == "oom-001"
    
    def test_get_patterns(self, engine):
        """Test getting available patterns."""
        patterns = engine.get_patterns()
        
        assert len(patterns) >= 7
        assert any(p["id"] == "oom-001" for p in patterns)
    
    def test_infer_severity_high(self, engine):
        """Test severity inference for high-priority keywords."""
        severity = engine._infer_severity("Node is down and network is unreachable")
        assert severity == Severity.HIGH
    
    def test_infer_severity_low(self, engine):
        """Test severity inference for low-priority keywords."""
        severity = engine._infer_severity("CPU is being throttled, minor performance impact")
        assert severity == Severity.LOW
    
    def test_infer_severity_medium(self, engine):
        """Test severity inference for medium priority."""
        severity = engine._infer_severity("Memory usage is high, pod may be killed")
        assert severity == Severity.MEDIUM
