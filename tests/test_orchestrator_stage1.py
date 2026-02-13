"""
Tests for IncidentOrchestrator Stage 1 — DetectResult integration (Step 2).

Covers:
- manual trigger → always fresh collection (R2)
- proactive + fresh DetectResult → reuse, Stage 1 ≈ 0ms
- proactive + stale DetectResult → fallback to fresh collection
- no DetectResult → fresh collection
- alarm + fresh DetectResult → reuse
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.detect_agent import DetectResult
from src.event_correlator import CorrelatedEvent
from src.incident_orchestrator import IncidentOrchestrator, IncidentStatus


# =============================================================================
# Helpers
# =============================================================================

def _make_correlated_event(**overrides) -> CorrelatedEvent:
    defaults = dict(
        collection_id="evt-test-001",
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_ms=800,
        region="ap-southeast-1",
        metrics=[],
        alarms=[],
        trail_events=[],
        health_events=[],
        source_status={"metrics": "ok"},
        anomalies=[],
        recent_changes=[],
    )
    defaults.update(overrides)
    return CorrelatedEvent(**defaults)


def _make_detect_result(
    age_seconds: float = 0,
    ttl_seconds: int = 300,
    source: str = "proactive_scan",
    with_event: bool = True,
) -> DetectResult:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    event = _make_correlated_event() if with_event else None
    return DetectResult(
        detect_id="det-test-s2",
        timestamp=ts.isoformat(),
        source=source,
        correlated_event=event,
        anomalies_detected=[],
        ttl_seconds=ttl_seconds,
        region="ap-southeast-1",
    )


@pytest.fixture
def orchestrator():
    return IncidentOrchestrator(region="ap-southeast-1")


@pytest.fixture
def mock_rca():
    """Mock RCA engine to avoid real Bedrock calls."""
    rca_result = MagicMock()
    rca_result.to_dict.return_value = {
        "root_cause": "test",
        "severity": "low",
        "confidence": 0.9,
        "pattern_id": "test-pat",
    }
    rca_result.confidence = 0.9
    rca_result.severity = "low"
    rca_result.pattern_id = "test-pat"
    rca_result.root_cause = "test"

    engine = MagicMock()
    engine.analyze = AsyncMock(return_value=rca_result)
    return engine


@pytest.fixture
def mock_bridge():
    """Mock RCA-SOP bridge."""
    bridge = MagicMock()
    bridge.match_sops.return_value = []
    return bridge


@pytest.fixture
def mock_fresh_collect():
    """Mock EventCorrelator for fresh collection path."""
    event = _make_correlated_event(collection_id="fresh-collect-001")
    correlator = MagicMock()
    correlator.collect = AsyncMock(return_value=event)
    return correlator


# =============================================================================
# Tests
# =============================================================================

class TestStage1Reuse:
    """Stage 1: DetectResult reuse vs fresh collection."""

    @pytest.mark.asyncio
    async def test_proactive_fresh_detect_result_reuses(self, orchestrator, mock_rca, mock_bridge):
        """proactive + fresh DetectResult → reuse, skip collection."""
        detect_result = _make_detect_result(age_seconds=30)  # fresh

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_rca), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge):
            incident = await orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=detect_result,
                dry_run=True,
            )

        # Should reuse — no fresh collection
        assert incident.collection_summary["source"] == "detect_agent_reuse"
        assert incident.collection_summary["detect_id"] == "det-test-s2"
        # Stage 1 should be near-instant (< 500ms — no AWS calls)
        assert incident.stage_timings["collect"] < 500

    @pytest.mark.asyncio
    async def test_manual_trigger_always_fresh(self, orchestrator, mock_rca, mock_bridge, mock_fresh_collect):
        """manual trigger → always fresh collection, even with fresh DetectResult."""
        detect_result = _make_detect_result(age_seconds=10)  # very fresh

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_rca), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.event_correlator.get_correlator", return_value=mock_fresh_collect):
            incident = await orchestrator.handle_incident(
                trigger_type="manual",
                detect_result=detect_result,
                dry_run=True,
            )

        # Should NOT reuse — manual always collects fresh
        assert incident.collection_summary["source"] == "fresh_collection"
        mock_fresh_collect.collect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_detect_result_falls_back(self, orchestrator, mock_rca, mock_bridge, mock_fresh_collect):
        """stale DetectResult → fallback to fresh collection."""
        detect_result = _make_detect_result(age_seconds=600, ttl_seconds=300)  # stale
        assert detect_result.is_stale  # sanity

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_rca), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.event_correlator.get_correlator", return_value=mock_fresh_collect):
            incident = await orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=detect_result,
                dry_run=True,
            )

        assert incident.collection_summary["source"] == "fresh_collection"
        mock_fresh_collect.collect.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_detect_result_fresh_collection(self, orchestrator, mock_rca, mock_bridge, mock_fresh_collect):
        """No DetectResult → fresh collection."""
        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_rca), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.event_correlator.get_correlator", return_value=mock_fresh_collect):
            incident = await orchestrator.handle_incident(
                trigger_type="manual",
                dry_run=True,
            )

        assert incident.collection_summary["source"] == "fresh_collection"
        mock_fresh_collect.collect.assert_called_once()

    @pytest.mark.asyncio
    async def test_alarm_fresh_detect_result_reuses(self, orchestrator, mock_rca, mock_bridge):
        """alarm + fresh DetectResult → reuse."""
        detect_result = _make_detect_result(age_seconds=60, source="alarm_trigger")

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_rca), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge):
            incident = await orchestrator.handle_incident(
                trigger_type="alarm",
                detect_result=detect_result,
                dry_run=True,
            )

        assert incident.collection_summary["source"] == "detect_agent_reuse"

    @pytest.mark.asyncio
    async def test_detect_result_without_event_fresh_collects(self, orchestrator, mock_rca, mock_bridge, mock_fresh_collect):
        """DetectResult with no correlated_event → fresh collection."""
        detect_result = _make_detect_result(age_seconds=10, with_event=False)

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_rca), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.event_correlator.get_correlator", return_value=mock_fresh_collect):
            incident = await orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=detect_result,
                dry_run=True,
            )

        assert incident.collection_summary["source"] == "fresh_collection"

    @pytest.mark.asyncio
    async def test_incident_completes_with_reuse(self, orchestrator, mock_rca, mock_bridge):
        """Full pipeline should complete successfully with reused data."""
        detect_result = _make_detect_result(age_seconds=30)

        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_rca), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge):
            incident = await orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=detect_result,
                dry_run=True,
            )

        assert incident.status in (IncidentStatus.COMPLETED, IncidentStatus.WAITING_APPROVAL)
        assert "collect" in incident.stage_timings
        assert "analyze" in incident.stage_timings
