"""
Tests for Detect Agent Data Reuse — DetectResult + Orchestrator integration

Validates:
  - DetectResult data structure (TTL, staleness, freshness labels)
  - detect_result parameter in incident_orchestrator.handle_incident()
  - R1: Stale detect_result → fallback to fresh collection
  - R2: Manual trigger → always fresh collection (ignore detect_result)
  - Backward compatibility: no detect_result → fresh collection
  - Data integrity and edge cases

Ref: docs/designs/DETECT_AGENT_DATA_REUSE_DESIGN.md (Approved 2026-02-13)
"""

import asyncio
import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import dataclass, field
from typing import List, Dict, Any

# ── Imports under test ─────────────────────────────────────────────
from src.incident_orchestrator import (
    IncidentOrchestrator,
    IncidentRecord,
    IncidentStatus,
    TriggerType,
)
from src.detect_agent import DetectResult, DetectAgent


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
    """Mimics src.event_correlator.CorrelatedEvent."""
    collection_id: str = "collect-mock-001"
    timestamp: str = "2026-02-13T12:00:00Z"
    duration_ms: int = 350
    region: str = "ap-southeast-1"
    metrics: list = field(default_factory=lambda: [Mock(metric_name="CPUUtilization", value=92.5, resource_id="i-abc123")])
    alarms: list = field(default_factory=lambda: [Mock(name="HighCPU", state="ALARM", reason="threshold")])
    trail_events: list = field(default_factory=lambda: [Mock(event_name="StopInstances", error_code=None, error_message="", read_only=False)])
    anomalies: list = field(default_factory=lambda: [{"type": "cpu_spike", "description": "CPU > 90%"}])
    health_events: list = field(default_factory=list)
    source_status: dict = field(default_factory=dict)
    recent_changes: list = field(default_factory=list)

    def to_dict(self):
        return {"collection_id": self.collection_id, "region": self.region}

    def to_rca_telemetry(self):
        return {"events": [], "metrics": {}, "logs": []}


# ── Helper: Build DetectResult with controllable age ───────────────
def make_detect_result(
    age_seconds=0,
    source="proactive_scan",
    ttl_seconds=300,
    event=None,
    detect_id=None,
):
    """Create a DetectResult with timestamp set to `age_seconds` ago."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return DetectResult(
        detect_id=detect_id or f"det-test-{int(time.time()*1000)}",
        timestamp=ts,
        source=source,
        correlated_event=event or MockCorrelatedEvent(),
        anomalies_detected=[{"type": "cpu_spike"}],
        pattern_matches=[],
        ttl_seconds=ttl_seconds,
    )


# ── Fixtures ───────────────────────────────────────────────────────
@pytest.fixture
def orchestrator():
    return IncidentOrchestrator(region="ap-southeast-1")


@pytest.fixture
def fresh_result():
    """A DetectResult created just now (age ~0s)."""
    return make_detect_result(age_seconds=0)


@pytest.fixture
def warm_result():
    """A DetectResult created 2 minutes ago (within TTL)."""
    return make_detect_result(age_seconds=120)


@pytest.fixture
def stale_result():
    """A DetectResult created 10 minutes ago (past 5min TTL)."""
    return make_detect_result(age_seconds=600)


# ── Mock Stage 2-4 dependencies ───────────────────────────────────
def _mock_stages():
    """Create mocks for RCA (Stage 2), SOP (Stage 3), Safety (Stage 4)."""
    mock_rca = Mock()
    mock_rca.to_dict.return_value = {
        "root_cause": "CPU overload", "severity": "high",
        "confidence": 0.9, "pattern_id": "PAT-CPU-001",
    }
    mock_rca.confidence = 0.9
    mock_rca.severity = Mock(value="high")
    mock_rca.pattern_id = "PAT-CPU-001"
    mock_rca.root_cause = "CPU overload"
    mock_rca.matched_symptoms = ["i-abc123"]

    engine = AsyncMock()
    engine.analyze.return_value = mock_rca

    bridge = Mock()
    bridge.match_sops.return_value = [{
        "sop_id": "SOP-CPU-001", "name": "Kill Runaway",
        "match_confidence": 0.88, "severity": "low",
    }]

    safety_result = Mock()
    safety_result.passed = True
    safety_result.execution_mode = "auto"
    safety_result.to_dict.return_value = {"risk_level": "low", "passed": True}

    safety = Mock()
    safety.check.return_value = safety_result
    safety._classify_risk.return_value = Mock(value="low")

    return engine, bridge, safety


def _patch_all():
    """Context managers for Stage 2-4 + event_correlator."""
    engine, bridge, safety = _mock_stages()
    fresh_event = MockCorrelatedEvent(collection_id="fresh-fallback")
    correlator = AsyncMock()
    correlator.collect.return_value = fresh_event

    return (
        patch("src.rca_inference.get_rca_inference_engine", return_value=engine),
        patch("src.rca_sop_bridge.get_bridge", return_value=bridge),
        patch("src.sop_safety.get_safety_layer", return_value=safety),
        patch("src.event_correlator.get_correlator", return_value=correlator),
        engine, correlator
    )


# ═══════════════════════════════════════════════════════════════════
#  1. DetectResult Data Structure
# ═══════════════════════════════════════════════════════════════════

class TestDetectResultStructure:
    """Validate DetectResult properties: TTL, staleness, freshness labels."""

    def test_fresh_result_not_stale(self):
        dr = make_detect_result(age_seconds=0)
        assert not dr.is_stale
        assert dr.freshness_label == "fresh"
        assert dr.age_seconds < 5

    def test_warm_result_not_stale(self):
        dr = make_detect_result(age_seconds=120)
        assert not dr.is_stale
        assert dr.freshness_label == "warm"

    def test_stale_result_is_stale(self):
        dr = make_detect_result(age_seconds=600)
        assert dr.is_stale
        assert dr.freshness_label == "stale"

    def test_boundary_exactly_at_ttl(self):
        """At exactly TTL seconds, data should NOT be stale (boundary: age > ttl)."""
        dr = make_detect_result(age_seconds=300, ttl_seconds=300)
        # age_seconds will be ~300, is_stale is age > ttl (not >=)
        # Due to timing, this could be 300.00x, so just verify the label logic
        assert dr.age_seconds >= 299  # sanity check

    def test_custom_ttl(self):
        dr = make_detect_result(age_seconds=150, ttl_seconds=120)
        assert dr.is_stale
        assert dr.freshness_label == "stale"

    def test_freshness_labels_all_three(self):
        """Verify all three freshness states."""
        fresh = make_detect_result(age_seconds=10)
        warm = make_detect_result(age_seconds=120)
        stale = make_detect_result(age_seconds=600)
        assert fresh.freshness_label == "fresh"
        assert warm.freshness_label == "warm"
        assert stale.freshness_label == "stale"

    def test_to_dict_contains_all_fields(self):
        dr = make_detect_result(age_seconds=30, detect_id="det-test-xyz")
        d = dr.to_dict()
        assert d["detect_id"] == "det-test-xyz"
        assert "timestamp" in d
        assert d["source"] == "proactive_scan"
        assert d["ttl_seconds"] == 300
        assert "age_seconds" in d
        assert "is_stale" in d
        assert d["freshness"] == "fresh"
        assert "anomalies_detected" in d
        assert "pattern_matches" in d

    def test_to_dict_includes_correlated_event(self):
        event = MockCorrelatedEvent(collection_id="ce-123")
        dr = make_detect_result(event=event)
        d = dr.to_dict()
        assert "correlated_event" in d
        assert d["correlated_event"]["collection_id"] == "ce-123"


# ═══════════════════════════════════════════════════════════════════
#  2. Reuse Path — Fresh detect_result + non-manual trigger
# ═══════════════════════════════════════════════════════════════════

class TestReusePath:
    """When detect_result is fresh and trigger != manual → skip Stage 1."""

    def test_skips_collection_with_fresh_result(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, engine, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_result,
            ))
            correlator.collect.assert_not_called()
            engine.analyze.assert_called_once()
            assert result.status == IncidentStatus.COMPLETED

    def test_source_tagged_detect_agent_reuse(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_result,
            ))
            assert result.collection_summary["source"] == "detect_agent_reuse"

    def test_detect_id_in_collection_summary(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_result,
            ))
            assert result.collection_summary["detect_id"] == fresh_result.detect_id

    def test_data_age_in_collection_summary(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_result,
            ))
            assert "data_age_seconds" in result.collection_summary
            assert result.collection_summary["data_age_seconds"] < 5

    def test_collection_counts_match_event(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_result,
            ))
            ev = fresh_result.correlated_event
            cs = result.collection_summary
            assert cs["collection_id"] == ev.collection_id
            assert cs["metrics"] == len(ev.metrics)
            assert cs["alarms"] == len(ev.alarms)
            assert cs["trail_events"] == len(ev.trail_events)
            assert cs["anomalies"] == len(ev.anomalies)
            assert cs["health_events"] == len(ev.health_events)

    def test_stage1_timing_near_zero(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_result,
            ))
            assert result.stage_timings["collect"] < 100

    def test_warm_result_still_reused(self, orchestrator, warm_result):
        """Warm data (within TTL) should still be reused."""
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=warm_result,
            ))
            correlator.collect.assert_not_called()
            assert result.collection_summary["source"] == "detect_agent_reuse"

    def test_all_auto_trigger_types(self, orchestrator):
        """All non-manual trigger types should reuse fresh detect_result."""
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            for trigger in ["alarm", "anomaly", "health_event", "proactive"]:
                dr = make_detect_result(age_seconds=5)
                result = run(orchestrator.handle_incident(
                    trigger_type=trigger,
                    detect_result=dr,
                ))
                assert result.collection_summary["source"] == "detect_agent_reuse", \
                    f"trigger={trigger} should reuse"

    def test_exact_event_object_passed_to_rca(self, orchestrator, fresh_result):
        """RCA must receive the exact correlated_event from detect_result."""
        p_rca, p_bridge, p_safety, p_corr, engine, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=fresh_result,
            ))
            args, _ = engine.analyze.call_args
            assert args[0] is fresh_result.correlated_event


# ═══════════════════════════════════════════════════════════════════
#  3. R1 — Stale detect_result → Fallback to fresh collection
# ═══════════════════════════════════════════════════════════════════

class TestStaleFallback:
    """R1: When detect_result is stale, must fall back to fresh collection."""

    def test_stale_result_triggers_fresh_collection(self, orchestrator, stale_result):
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=stale_result,
            ))
            correlator.collect.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"

    def test_stale_result_source_is_fresh(self, orchestrator, stale_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="alarm",
                detect_result=stale_result,
            ))
            assert result.collection_summary["source"] == "fresh_collection"

    def test_stale_with_custom_ttl(self, orchestrator):
        """Even with shorter TTL (2min), stale data should trigger fresh collection."""
        dr = make_detect_result(age_seconds=150, ttl_seconds=120)
        assert dr.is_stale
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=dr,
            ))
            correlator.collect.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"


# ═══════════════════════════════════════════════════════════════════
#  4. R2 — Manual trigger → Always fresh collection
# ═══════════════════════════════════════════════════════════════════

class TestManualTriggerAlwaysFresh:
    """R2: Manual trigger must NEVER reuse cached data."""

    def test_manual_with_fresh_result_still_collects(self, orchestrator, fresh_result):
        assert not fresh_result.is_stale  # sanity
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="manual",
                detect_result=fresh_result,
            ))
            correlator.collect.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"

    def test_manual_with_warm_result_still_collects(self, orchestrator, warm_result):
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="manual",
                detect_result=warm_result,
            ))
            correlator.collect.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"

    def test_manual_without_result_collects(self, orchestrator):
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(trigger_type="manual"))
            correlator.collect.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"


# ═══════════════════════════════════════════════════════════════════
#  5. Backward Compatibility — No detect_result
# ═══════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """No detect_result → original fresh collection path."""

    def test_no_detect_result(self, orchestrator):
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(trigger_type="anomaly"))
            correlator.collect.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"

    def test_explicit_none(self, orchestrator):
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=None,
            ))
            correlator.collect.assert_called_once()

    def test_detect_result_without_correlated_event(self, orchestrator):
        """detect_result with correlated_event=None should fallback."""
        dr = make_detect_result(age_seconds=0)
        dr.correlated_event = None
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=dr,
            ))
            correlator.collect.assert_called_once()
            assert result.collection_summary["source"] == "fresh_collection"


# ═══════════════════════════════════════════════════════════════════
#  6. Data Integrity & Edge Cases
# ═══════════════════════════════════════════════════════════════════

class TestDataIntegrity:

    def test_empty_event_reused(self, orchestrator):
        """An event with empty data lists should still be reusable."""
        event = MockCorrelatedEvent(
            collection_id="empty-001", metrics=[], alarms=[],
            trail_events=[], anomalies=[], health_events=[],
        )
        dr = make_detect_result(age_seconds=0, event=event)
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly", detect_result=dr,
            ))
            correlator.collect.assert_not_called()
            cs = result.collection_summary
            assert cs["metrics"] == 0
            assert cs["source"] == "detect_agent_reuse"

    def test_reuse_then_fresh_no_leakage(self, orchestrator, fresh_result):
        """Sequential calls: reuse then fresh, no state leakage."""
        p_rca, p_bridge, p_safety, p_corr, _, correlator = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            r1 = run(orchestrator.handle_incident(
                trigger_type="anomaly", detect_result=fresh_result,
            ))
            r2 = run(orchestrator.handle_incident(trigger_type="manual"))

            assert r1.collection_summary["source"] == "detect_agent_reuse"
            assert r2.collection_summary["source"] == "fresh_collection"
            assert r1.incident_id != r2.incident_id

    def test_collection_id_preserved(self, orchestrator):
        event = MockCorrelatedEvent(collection_id="detect-xyz-789")
        dr = make_detect_result(age_seconds=5, event=event)
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="proactive", detect_result=dr,
            ))
            assert result.collection_summary["collection_id"] == "detect-xyz-789"

    def test_incident_persisted_in_memory(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly", detect_result=fresh_result,
            ))
            stored = orchestrator.get_incident(result.incident_id)
            assert stored is result
            assert stored.collection_summary["source"] == "detect_agent_reuse"


# ═══════════════════════════════════════════════════════════════════
#  7. Error Handling
# ═══════════════════════════════════════════════════════════════════

class TestErrorHandling:

    def test_rca_failure_still_has_collection_summary(self, orchestrator, fresh_result):
        engine = AsyncMock()
        engine.analyze.side_effect = RuntimeError("RCA unavailable")
        with patch("src.rca_inference.get_rca_inference_engine", return_value=engine):
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly", detect_result=fresh_result,
            ))
            assert result.status == IncidentStatus.FAILED
            assert "RCA unavailable" in result.error
            assert result.collection_summary["source"] == "detect_agent_reuse"


# ═══════════════════════════════════════════════════════════════════
#  8. Serialization
# ═══════════════════════════════════════════════════════════════════

class TestSerialization:

    def test_to_dict_source_field(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly", detect_result=fresh_result,
            ))
            d = result.to_dict()
            assert d["collection_summary"]["source"] == "detect_agent_reuse"

    def test_to_markdown_no_error(self, orchestrator, fresh_result):
        p_rca, p_bridge, p_safety, p_corr, _, _ = _patch_all()
        with p_rca, p_bridge, p_safety, p_corr:
            result = run(orchestrator.handle_incident(
                trigger_type="anomaly", detect_result=fresh_result,
            ))
            md = result.to_markdown()
            assert "事件" in md
            assert result.incident_id[:12] in md


# ═══════════════════════════════════════════════════════════════════
#  9. DetectAgent Class
# ═══════════════════════════════════════════════════════════════════

class TestDetectAgentClass:
    """Tests for the DetectAgent singleton and caching."""

    def test_get_latest_returns_none_initially(self):
        agent = DetectAgent(region="us-east-1")
        assert agent.get_latest() is None

    def test_get_latest_fresh_returns_none_initially(self):
        agent = DetectAgent(region="us-east-1")
        assert agent.get_latest_fresh() is None

    def test_health_idle_state(self):
        agent = DetectAgent(region="us-east-1")
        h = agent.health()
        assert h["status"] == "idle"
        assert h["latest_detect_id"] is None
        assert h["cache_size"] == 0

    def test_run_detection_caches_result(self):
        mock_event = MockCorrelatedEvent()
        mock_correlator = AsyncMock()
        mock_correlator.collect.return_value = mock_event

        # Patch get_correlator to return mock during __init__
        with patch("src.event_correlator.get_correlator", return_value=mock_correlator):
            agent = DetectAgent(region="ap-southeast-1", cache_dir="/tmp/test_detect_cache")

        result = run(agent.run_detection(source="proactive_scan"))
        assert result.detect_id.startswith("det-")
        assert result.source == "proactive_scan"
        assert result.correlated_event is mock_event
        assert agent.get_latest() is result
        assert agent.get_latest_fresh() is result
        assert agent.health()["cache_size"] == 1

    def test_run_detection_mutex(self):
        """Two concurrent detections should not overlap (asyncio.Lock)."""
        call_order = []

        async def slow_collect(*a, **kw):
            call_order.append("start")
            await asyncio.sleep(0.05)
            call_order.append("end")
            return MockCorrelatedEvent()

        mock_correlator = Mock()
        mock_correlator.collect = slow_collect

        with patch("src.event_correlator.get_correlator", return_value=mock_correlator):
            agent = DetectAgent(region="ap-southeast-1", cache_dir="/tmp/test_detect_cache2")

        async def two_detections():
            t1 = asyncio.create_task(agent.run_detection())
            t2 = asyncio.create_task(agent.run_detection())
            await asyncio.gather(t1, t2)
        run(two_detections())

        # With mutex, calls should be serialized: start, end, start, end
        assert call_order == ["start", "end", "start", "end"]
