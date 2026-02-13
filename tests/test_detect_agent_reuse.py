"""
Tests for Detect Agent Data Reuse (commit fe5673e)

Validates the `pre_collected_event` parameter in `incident_orchestrator.handle_incident()`:
  - When provided: Stage 1 (collection) is skipped, data reused from Detect Agent
  - When absent: Falls back to fresh collection (backward compatible)
  - Edge cases: data integrity, timing, source tagging

Ref: Ma Ronnie's architecture feedback — Detect Agent 数据复用
"""

import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import dataclass, field
from typing import List, Dict, Any

# ── Import the orchestrator under test ─────────────────────────────
from src.incident_orchestrator import (
    IncidentOrchestrator,
    IncidentRecord,
    IncidentStatus,
    TriggerType,
)


# ── Helper: run async in sync test ─────────────────────────────────
def run(coro):
    """Run an async coroutine in a new event loop (for sync pytest)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Helper: Build a mock CorrelatedEvent ───────────────────────────
@dataclass
class MockCorrelatedEvent:
    """
    Mimics src.event_correlator.CorrelatedEvent with the fields
    accessed by handle_incident's pre_collected_event path.
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


# ── Fixtures ───────────────────────────────────────────────────────
@pytest.fixture
def orchestrator():
    return IncidentOrchestrator(region="ap-southeast-1")


@pytest.fixture
def mock_event():
    return MockCorrelatedEvent()


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
    """
    Creates mock objects for Stage 2 (RCA), Stage 3 (SOP), Stage 4 (Safety).
    Returns patches list, mock rca_result, mock rca engine.
    """
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
#  Test Suite: pre_collected_event Reuse Path
# ═══════════════════════════════════════════════════════════════════

class TestPreCollectedEventReuse:
    """Tests for the Detect Agent data reuse path (pre_collected_event != None)."""

    def test_skips_stage1_when_pre_collected(self, orchestrator, mock_event):
        """Core test: pre_collected_event skips Stage 1 fresh collection."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator") as mock_get_correlator, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))

            # get_correlator should NOT be called — Stage 1 was skipped
            mock_get_correlator.assert_not_called()

            # RCA engine should still receive the event
            mock_engine.analyze.assert_called_once_with(mock_event)

            assert result.status == IncidentStatus.COMPLETED

    def test_source_tagged_as_detect_agent_reuse(self, orchestrator, mock_event):
        """collection_summary.source must be 'detect_agent_reuse'."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))
            assert result.collection_summary is not None
            assert result.collection_summary["source"] == "detect_agent_reuse"

    def test_collection_summary_counts_match_event(self, orchestrator, mock_event):
        """collection_summary counts must reflect the pre-collected event's data."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))
            cs = result.collection_summary
            assert cs["collection_id"] == mock_event.collection_id
            assert cs["metrics"] == len(mock_event.metrics)
            assert cs["alarms"] == len(mock_event.alarms)
            assert cs["trail_events"] == len(mock_event.trail_events)
            assert cs["anomalies"] == len(mock_event.anomalies)
            assert cs["health_events"] == len(mock_event.health_events)
            assert cs["duration_ms"] == mock_event.duration_ms

    def test_collection_summary_with_large_event(self, orchestrator, mock_event_large):
        """Verify counts are correct for a richer event payload."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event_large,
            ))
            cs = result.collection_summary
            assert cs["metrics"] == 20
            assert cs["alarms"] == 5
            assert cs["trail_events"] == 10
            assert cs["anomalies"] == 4
            assert cs["health_events"] == 1
            assert cs["source"] == "detect_agent_reuse"

    def test_stage1_timing_near_zero(self, orchestrator, mock_event):
        """When reusing pre-collected data, Stage 1 timing should be near-zero (< 100ms)."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))
            collect_ms = result.stage_timings.get("collect", 999)
            assert collect_ms < 100, f"Stage 1 took {collect_ms}ms — should be near-zero for reuse"

    def test_all_trigger_types_accept_pre_collected(self, orchestrator, mock_event):
        """pre_collected_event should work with all trigger types."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            for trigger in ["alarm", "anomaly", "health_event", "proactive"]:
                result = run(orchestrator.handle_incident(
                    trigger_type=trigger,
                    pre_collected_event=mock_event,
                ))
                assert result.collection_summary["source"] == "detect_agent_reuse"
                assert result.status in (IncidentStatus.COMPLETED, IncidentStatus.WAITING_APPROVAL)


# ═══════════════════════════════════════════════════════════════════
#  Test Suite: Backward Compatibility (no pre_collected_event)
# ═══════════════════════════════════════════════════════════════════

class TestFreshCollectionFallback:
    """Tests that handle_incident() without pre_collected_event still works."""

    def test_fresh_collection_when_no_pre_collected(self, orchestrator):
        """Without pre_collected_event, Stage 1 should call get_correlator + collect."""
        mock_event = MockCorrelatedEvent()
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator) as mock_gc, \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(trigger_type="manual"))
            mock_gc.assert_called_once_with("ap-southeast-1")
            mock_correlator.collect.assert_called_once()

    def test_source_tagged_as_fresh_collection(self, orchestrator):
        """collection_summary.source must be 'fresh_collection' when no pre-collected."""
        mock_event = MockCorrelatedEvent()
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_event
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator), \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(trigger_type="manual"))
            assert result.collection_summary["source"] == "fresh_collection"

    def test_explicit_none_treated_as_no_pre_collected(self, orchestrator):
        """Explicitly passing pre_collected_event=None should trigger fresh collection."""
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
                pre_collected_event=None,
            ))
            mock_gc.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"


# ═══════════════════════════════════════════════════════════════════
#  Test Suite: Data Integrity & Edge Cases
# ═══════════════════════════════════════════════════════════════════

class TestDataIntegrity:
    """Edge cases and data integrity checks."""

    def test_empty_pre_collected_event(self, orchestrator):
        """An event with all empty lists should still be accepted and tagged as reuse."""
        empty_event = MockCorrelatedEvent(
            collection_id="detect-empty-003",
            metrics=[],
            alarms=[],
            trail_events=[],
            anomalies=[],
            health_events=[],
        )
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=empty_event,
            ))
            cs = result.collection_summary
            assert cs["source"] == "detect_agent_reuse"
            assert cs["metrics"] == 0
            assert cs["alarms"] == 0
            assert cs["trail_events"] == 0
            assert cs["anomalies"] == 0
            assert cs["health_events"] == 0

    def test_pre_collected_event_passed_to_rca(self, orchestrator, mock_event):
        """The exact pre_collected_event object must be passed to RCA analyze()."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))
            # Ensure the exact same object reference was passed to RCA
            args, _ = mock_engine.analyze.call_args
            assert args[0] is mock_event, "RCA must receive the exact pre-collected event object"

    def test_incident_record_persisted(self, orchestrator, mock_event):
        """Incident should be stored in orchestrator._incidents."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))
            assert result.incident_id in orchestrator._incidents
            stored = orchestrator.get_incident(result.incident_id)
            assert stored is result
            assert stored.collection_summary["source"] == "detect_agent_reuse"

    def test_reuse_then_fresh_same_orchestrator(self, orchestrator, mock_event):
        """
        Same orchestrator should handle both reuse and fresh collection calls.
        Verifies no state leakage between calls.
        """
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = MockCorrelatedEvent(collection_id="fresh-004")
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            # First: reuse
            result1 = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))

            # Second: fresh
            with patch("src.event_correlator.get_correlator", return_value=mock_correlator):
                result2 = run(orchestrator.handle_incident(trigger_type="manual"))

            assert result1.collection_summary["source"] == "detect_agent_reuse"
            assert result2.collection_summary["source"] == "fresh_collection"
            assert result1.incident_id != result2.incident_id

    def test_collection_id_preserved_from_detect_agent(self, orchestrator):
        """The detect agent's collection_id must be preserved through the pipeline."""
        event = MockCorrelatedEvent(collection_id="detect-unique-xyz-789")
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="proactive",
                pre_collected_event=event,
            ))
            assert result.collection_summary["collection_id"] == "detect-unique-xyz-789"


# ═══════════════════════════════════════════════════════════════════
#  Test Suite: Error Handling
# ═══════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Error handling when pre_collected_event has issues."""

    def test_rca_failure_with_pre_collected(self, orchestrator, mock_event):
        """If RCA fails after reuse, incident should be FAILED with error."""
        mock_engine = AsyncMock()
        mock_engine.analyze.side_effect = RuntimeError("RCA model unavailable")

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine):
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))
            assert result.status == IncidentStatus.FAILED
            assert "RCA model unavailable" in result.error
            # Even though failed, collection_summary should be populated
            assert result.collection_summary["source"] == "detect_agent_reuse"

    def test_missing_attribute_on_event(self, orchestrator):
        """If pre_collected_event lacks expected attributes, handle gracefully."""
        broken_event = Mock()
        broken_event.collection_id = "broken-001"
        broken_event.metrics = []
        broken_event.alarms = []
        broken_event.trail_events = []
        broken_event.anomalies = []
        broken_event.health_events = []
        broken_event.duration_ms = 0

        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=broken_event,
            ))
            # Should complete normally — the reuse path only reads these fields
            assert result.collection_summary["source"] == "detect_agent_reuse"


# ═══════════════════════════════════════════════════════════════════
#  Test Suite: IncidentRecord Serialization
# ═══════════════════════════════════════════════════════════════════

class TestSerialization:
    """Ensure reuse-path incidents serialize correctly."""

    def test_to_dict_includes_source(self, orchestrator, mock_event):
        """to_dict() must include the 'source' field in collection_summary."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))
            d = result.to_dict()
            assert d["collection_summary"]["source"] == "detect_agent_reuse"

    def test_to_markdown_works_with_reuse(self, orchestrator, mock_event):
        """to_markdown() should not error on reuse-path incidents."""
        mock_engine, mock_bridge, mock_safety, _ = _create_stage_mocks()

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety):

            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                pre_collected_event=mock_event,
            ))
            md = result.to_markdown()
            assert "事件" in md
            assert result.incident_id[:12] in md
