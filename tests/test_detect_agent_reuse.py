"""
Tests for Detect Agent Data Reuse — DetectResult interface

Validates:
  - detect_result parameter in incident_orchestrator.handle_incident()
  - DetectResult data structure (TTL, staleness, freshness)
  - R1: Stale detection → fallback to fresh collection
  - R2: Manual trigger → always fresh collection
  - Backward compatibility: no detect_result → fresh collection

Ref: DETECT_AGENT_DATA_REUSE_DESIGN.md
"""

import asyncio
import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import dataclass, field
from typing import List, Dict, Any

# ── Import the modules under test ──────────────────────────────────
from src.incident_orchestrator import (
    IncidentOrchestrator,
    IncidentRecord,
    IncidentStatus,
    TriggerType,
)
from src.detect_agent import DetectResult


# ── Helper: run async in sync test ─────────────────────────────────
def run(coro):
    """Run an async coroutine in a new event loop (for sync pytest)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Helper: Build a mock CorrelatedEvent ───────────────────────────
@dataclass
class MockCorrelatedEvent:
    """
    Mimics src.event_correlator.CorrelatedEvent with the fields
    accessed by handle_incident's detect_result path.
    """
    collection_id: str = "detect-mock-001"
    timestamp: str = "2026-02-13T12:00:00Z"
    duration_ms: int = 350
    region: str = "ap-southeast-1"
    metrics: list = field(default_factory=lambda: [Mock(metric_name="CPUUtilization", value=92.5, resource_id="i-abc123")])
    alarms: list = field(default_factory=lambda: [Mock(name="HighCPU", state="ALARM", reason="threshold breach")])
    trail_events: list = field(default_factory=lambda: [Mock(event_name="StopInstances", error_code=None, error_message="", read_only=False)])
    anomalies: list = field(default_factory=lambda: [{"type": "cpu_spike", "description": "CPU > 90% for 10m"}])
    health_events: list = field(default_factory=list)
    source_status: dict = field(default_factory=lambda: {"cloudwatch": "ok", "cloudtrail": "ok"})
    recent_changes: list = field(default_factory=list)

    def to_dict(self):
        return {"collection_id": self.collection_id, "region": self.region}

    def to_rca_telemetry(self):
        return {
            "events": [{"reason": "CPU spike", "type": "Warning", "source": "metric_anomaly"}],
            "metrics": {"i-abc123:CPUUtilization": 92.5},
            "logs": [],
        }


# ── Helper: Build a DetectResult ───────────────────────────────────
def make_detect_result(
    source="proactive_scan",
    age_seconds=0,
    ttl_seconds=300,
    event=None,
):
    """Create a DetectResult with controllable age."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return DetectResult(
        detect_id=f"det-test-{id(event) % 10000:04d}",
        timestamp=ts,
        source=source,
        correlated_event=event or MockCorrelatedEvent(),
        anomalies_detected=[{"type": "cpu_spike"}],
        ttl_seconds=ttl_seconds,
    )


# ── Fixtures ───────────────────────────────────────────────────────
@pytest.fixture
def orchestrator():
    return IncidentOrchestrator(region="ap-southeast-1")


@pytest.fixture
def mock_event():
    return MockCorrelatedEvent()


@pytest.fixture
def fresh_detect_result(mock_event):
    """A fresh (0s old) DetectResult."""
    return make_detect_result(event=mock_event, age_seconds=0)


@pytest.fixture
def stale_detect_result(mock_event):
    """A stale (10min old, TTL=5min) DetectResult."""
    return make_detect_result(event=mock_event, age_seconds=600, ttl_seconds=300)


@pytest.fixture
def mock_event_large():
    """A larger event simulating rich Detect Agent output."""
    return MockCorrelatedEvent(
        collection_id="detect-large-002",
        duration_ms=1200,
        metrics=[Mock(metric_name=f"Metric{i}", value=float(i), resource_id=f"r-{i}") for i in range(20)],
        alarms=[Mock(name=f"Alarm{i}", state="ALARM" if i < 3 else "OK", reason=f"reason-{i}") for i in range(5)],
        trail_events=[Mock(event_name=f"Event{i}", error_code="AccessDenied" if i == 0 else None, error_message="" if i != 0 else "Denied", read_only=(i > 2)) for i in range(10)],
        anomalies=[{"type": f"anomaly_{i}", "description": f"desc {i}"} for i in range(4)],
        health_events=[Mock(service="ec2", event_type="maintenance", status="open", description="instance reboot")],
    )


# ── Mock RCA + SOP dependencies (Stage 2-4) ───────────────────────
def _create_stage_mocks():
    mock_rca_result = Mock()
    mock_rca_result.to_dict.return_value = {
        "root_cause": "CPU overload due to runaway process",
        "severity": "high",
        "confidence": 0.9,
        "pattern_id": "PAT-CPU-001",
        "evidence": ["CPU > 90%"],
    }
    mock_rca_result.confidence = 0.9
    mock_rca_result.severity = Mock(value="high")
    mock_rca_result.pattern_id = "PAT-CPU-001"
    mock_rca_result.root_cause = "CPU overload due to runaway process"
    mock_rca_result.matched_symptoms = ["i-abc123"]

    mock_engine = AsyncMock()
    mock_engine.analyze.return_value = mock_rca_result

    mock_bridge = Mock()
    mock_bridge.match_sops.return_value = [
        {
            "sop_id": "SOP-CPU-001",
            "name": "Kill Runaway Process",
            "match_confidence": 0.88,
            "severity": "low",
        }
    ]

    mock_safety_result = Mock()
    mock_safety_result.passed = True
    mock_safety_result.execution_mode = "auto"
    mock_safety_result.to_dict.return_value = {
        "risk_level": "low",
        "execution_mode": "auto",
        "passed": True,
    }

    mock_safety = Mock()
    mock_safety.check.return_value = mock_safety_result
    mock_safety._classify_risk.return_value = Mock(value="low")

    return mock_engine, mock_bridge, mock_safety, mock_rca_result


# ═══════════════════════════════════════════════════════════════════
#  Test Suite 1: DetectResult Data Structure
# ═══════════════════════════════════════════════════════════════════

class TestDetectResultStructure:
    """Tests for DetectResult TTL, staleness, and freshness labels."""

    def test_fresh_result_not_stale(self):
        dr = make_detect_result(age_seconds=0)
        assert not dr.is_stale
        assert dr.freshness_label == "fresh"

    def test_warm_result(self):
        dr = make_detect_result(age_seconds=120, ttl_seconds=300)
        assert not dr.is_stale
        assert dr.freshness_label == "warm"

    def test_stale_result(self):
        dr = make_detect_result(age_seconds=600, ttl_seconds=300)
        assert dr.is_stale
        assert dr.freshness_label == "stale"

    def test_age_seconds_positive(self):
        dr = make_detect_result(age_seconds=30)
        assert dr.age_seconds >= 29  # allow small timing delta

    def test_to_dict_includes_freshness(self):
        dr = make_detect_result(age_seconds=0)
        d = dr.to_dict()
        assert "freshness" in d
        assert "is_stale" in d
        assert "detect_id" in d
        assert d["is_stale"] is False

    def test_default_ttl_is_300(self):
        dr = make_detect_result()
        assert dr.ttl_seconds == 300

    def test_custom_ttl(self):
        dr = make_detect_result(ttl_seconds=60, age_seconds=90)
        assert dr.is_stale  # 90s > 60s TTL


# ═══════════════════════════════════════════════════════════════════
#  Test Suite 2: Reuse Path (fresh detect_result + non-manual)
# ═══════════════════════════════════════════════════════════════════

class TestDetectResultReuse:
    """Tests for the Detect Agent data reuse path."""

    def test_skips_stage1_with_fresh_detect_result(self, orchestrator, fresh_detect_result):
        """Fresh detect_result + non-manual trigger → skip Stage 1."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator") as mock_get_correlator, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_detect_result,
            ))

            mock_get_correlator.assert_not_called()
            mock_engine.analyze.assert_called_once()
            assert result.status == IncidentStatus.COMPLETED

    def test_source_tagged_as_detect_agent_reuse(self, orchestrator, fresh_detect_result):
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_detect_result,
            ))
            assert result.collection_summary["source"] == "detect_agent_reuse"

    def test_detect_id_in_collection_summary(self, orchestrator, fresh_detect_result):
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_detect_result,
            ))
            assert result.collection_summary.get("detect_id") == fresh_detect_result.detect_id

    def test_collection_summary_counts_match(self, orchestrator, fresh_detect_result):
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_detect_result,
            ))
            cs = result.collection_summary
            event = fresh_detect_result.correlated_event
            assert cs["metrics"] == len(event.metrics)
            assert cs["alarms"] == len(event.alarms)
            assert cs["trail_events"] == len(event.trail_events)

    def test_stage1_timing_near_zero(self, orchestrator, fresh_detect_result):
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_detect_result,
            ))
            assert result.stage_timings.get("collect", 999) < 100

    def test_all_auto_trigger_types_reuse(self, orchestrator, mock_event):
        """All non-manual trigger types should reuse fresh detect_result."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            for trigger in ["alarm", "anomaly", "health_event", "proactive"]:
                dr = make_detect_result(event=mock_event, age_seconds=0)
                result = run(orchestrator.handle_incident(
                    trigger_type=trigger,
                    detect_result=dr,
                ))
                assert result.collection_summary["source"] == "detect_agent_reuse"


# ═══════════════════════════════════════════════════════════════════
#  Test Suite 3: R1 — Stale Detection → Fallback
# ═══════════════════════════════════════════════════════════════════

class TestStaleDetectResultFallback:
    """R1: When detect_result is stale, fall back to fresh collection."""

    def test_stale_detect_result_triggers_fresh_collection(self, orchestrator, stale_detect_result):
        mock_fresh_event = MockCorrelatedEvent(collection_id="fresh-fallback-001")
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_fresh_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator) as mock_gc, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=stale_detect_result,
            ))

            mock_gc.assert_called_once()
            mock_correlator.collect.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"

    def test_stale_at_boundary(self, orchestrator, mock_event):
        """detect_result at exactly TTL+1s should be stale."""
        dr = make_detect_result(event=mock_event, age_seconds=301, ttl_seconds=300)
        assert dr.is_stale

        mock_fresh_event = MockCorrelatedEvent(collection_id="boundary-fresh")
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_fresh_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator), \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=dr,
            ))
            assert result.collection_summary["source"] == "fresh_collection"


# ═══════════════════════════════════════════════════════════════════
#  Test Suite 4: R2 — Manual Trigger → Always Fresh
# ═══════════════════════════════════════════════════════════════════

class TestManualTriggerAlwaysFresh:
    """R2: Manual trigger never uses cached detect_result."""

    def test_manual_ignores_fresh_detect_result(self, orchestrator, fresh_detect_result):
        """Even with a fresh detect_result, manual trigger must collect fresh data."""
        mock_fresh_event = MockCorrelatedEvent(collection_id="manual-fresh-001")
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_fresh_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator) as mock_gc, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="manual",
                detect_result=fresh_detect_result,
            ))

            mock_gc.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"

    def test_manual_without_detect_result(self, orchestrator):
        """Standard manual trigger without detect_result → fresh collection."""
        mock_event = MockCorrelatedEvent()
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator) as mock_gc, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(trigger_type="manual"))
            mock_gc.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"


# ═══════════════════════════════════════════════════════════════════
#  Test Suite 5: Backward Compatibility
# ═══════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """No detect_result → same behavior as before."""

    def test_no_detect_result_calls_correlator(self, orchestrator):
        mock_event = MockCorrelatedEvent()
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator) as mock_gc, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(trigger_type="manual"))
            mock_gc.assert_called_once()
            mock_correlator.collect.assert_called_once()

    def test_explicit_none_triggers_fresh(self, orchestrator):
        mock_event = MockCorrelatedEvent()
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator) as mock_gc, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="manual",
                detect_result=None,
            ))
            mock_gc.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"

    def test_reuse_then_fresh_no_leakage(self, orchestrator, mock_event):
        """Same orchestrator: reuse then fresh — no state pollution."""
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = MockCorrelatedEvent(collection_id="fresh-004")
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            dr = make_detect_result(event=mock_event, age_seconds=0)
            result1 = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=dr,
            ))

            with patch("src.event_correlator.get_correlator", return_value=mock_correlator):
                result2 = run(orchestrator.handle_incident(trigger_type="manual"))

            assert result1.collection_summary["source"] == "detect_agent_reuse"
            assert result2.collection_summary["source"] == "fresh_collection"
            assert result1.incident_id != result2.incident_id


# ═══════════════════════════════════════════════════════════════════
#  Test Suite 6: Error Handling
# ═══════════════════════════════════════════════════════════════════

class TestErrorHandling:

    def test_rca_failure_preserves_collection_summary(self, orchestrator, fresh_detect_result):
        mock_engine = AsyncMock()
        mock_engine.analyze.side_effect = RuntimeError("RCA model unavailable")

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine):
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_detect_result,
            ))
            assert result.status == IncidentStatus.FAILED
            assert "RCA model unavailable" in result.error
            assert result.collection_summary["source"] == "detect_agent_reuse"

    def test_detect_result_without_correlated_event(self, orchestrator):
        """detect_result with correlated_event=None → fresh collection."""
        dr = DetectResult(
            detect_id="det-no-event",
            timestamp=datetime.now(timezone.utc),
            source="proactive_scan",
            correlated_event=None,  # No event!
        )
        mock_event = MockCorrelatedEvent()
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator) as mock_gc, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=dr,
            ))
            mock_gc.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"


# ═══════════════════════════════════════════════════════════════════
#  Test Suite 7: Serialization
# ═══════════════════════════════════════════════════════════════════

class TestSerialization:

    def test_to_dict_includes_source(self, orchestrator, fresh_detect_result):
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_detect_result,
            ))
            d = result.to_dict()
            assert d["collection_summary"]["source"] == "detect_agent_reuse"

    def test_to_markdown_works_with_reuse(self, orchestrator, fresh_detect_result):
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_detect_result,
            ))
            md = result.to_markdown()
            assert "事件" in md
            assert result.incident_id[:12] in md
