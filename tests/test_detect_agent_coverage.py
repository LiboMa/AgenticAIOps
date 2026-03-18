"""Targeted tests for DetectAgent uncovered lines.

Covers:
- _write_dead_letter (lines 433-434)
- trigger_incident (lines 465-480)
- _enrich_topology (lines 556-592)
- _extract_vpc_id / _extract_failed_resource (lines 632-651)
- get_detect_agent_async singleton (lines 686-689)
- process_alert with AlertIngressService (lines 484-495, 529-530)
- _dispatch non-retryable errors & dead-letter (lines 352-357)
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.detect_agent import DetectAgent, DetectResult, get_detect_agent_async
from src.event_correlator import CorrelatedEvent


# ── Helpers ──────────────────────────────────────────────────────────

def _make_detect_result(**overrides) -> DetectResult:
    defaults = dict(
        detect_id="det-test-cov",
        timestamp=datetime.now(timezone.utc).isoformat(),
        source="test",
        region="ap-southeast-1",
        anomalies_detected=[],
        error=None,
    )
    defaults.update(overrides)
    return DetectResult(**defaults)


def _make_correlated_event(**overrides) -> CorrelatedEvent:
    defaults = dict(
        collection_id="test-collect-cov",
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_ms=100,
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


@pytest.fixture
def agent(tmp_path):
    """DetectAgent with mocked correlator and temp dirs."""
    mock_corr = MagicMock()
    mock_corr.collect = AsyncMock(return_value=_make_correlated_event())
    with patch("src.event_correlator.get_correlator", return_value=mock_corr):
        ag = DetectAgent(region="us-east-1")
    ag._correlator = mock_corr
    ag._cache_dir = tmp_path / "cache"
    ag._dead_letter_dir = tmp_path / "dead-letter"
    return ag


# ── _write_dead_letter ───────────────────────────────────────────────

class TestWriteDeadLetter:
    def test_writes_dead_letter_file(self, agent, tmp_path):
        result = _make_detect_result(detect_id="det-dl-001")
        agent._write_dead_letter(result, "test error")
        dl_path = agent._dead_letter_dir / "dl-det-dl-001.json"
        assert dl_path.exists()
        data = json.loads(dl_path.read_text())
        assert data["detect_id"] == "det-dl-001"
        assert data["error"] == "test error"

    def test_dead_letter_handles_exception(self, agent):
        """Writing to invalid path logs but doesn't raise."""
        agent._dead_letter_dir = Path("/proc/nonexistent/nope")
        result = _make_detect_result()
        # Should not raise
        agent._write_dead_letter(result, "err")


# ── trigger_incident ─────────────────────────────────────────────────

class TestTriggerIncident:
    @pytest.mark.asyncio
    async def test_trigger_incident_calls_orchestrator(self, agent):
        mock_orch = MagicMock()
        mock_orch.handle_incident = AsyncMock(return_value=MagicMock(id="inc-001"))

        with patch("src.incident_orchestrator.get_orchestrator", return_value=mock_orch) as mock_get:
            incident = await agent.trigger_incident(
                trigger_type="manual",
                services=["web"],
                auto_execute=False,
                dry_run=True,
            )
            mock_get.assert_called_once_with("us-east-1")
            mock_orch.handle_incident.assert_awaited_once()
            call_kwargs = mock_orch.handle_incident.call_args[1]
            assert call_kwargs["trigger_type"] == "manual"
            assert call_kwargs["dry_run"] is True


# ── _dispatch with non-retryable errors ──────────────────────────────

class TestDispatchRetry:
    @pytest.mark.asyncio
    async def test_non_retryable_error_no_retry(self, agent, tmp_path):
        """ValueError should not be retried."""
        mock_orch = MagicMock()
        mock_orch.handle_incident = AsyncMock(side_effect=ValueError("bad input"))

        result = _make_detect_result(
            anomalies_detected=[{"resource": "x", "severity": "critical"}]
        )

        with patch("src.incident_orchestrator.get_orchestrator", return_value=mock_orch):
            await agent._dispatch(result)

        # Should have been called only once (no retry on ValueError)
        assert mock_orch.handle_incident.await_count == 1
        assert agent._dispatch_failures == 1

    @pytest.mark.asyncio
    async def test_transient_error_retries_then_dead_letters(self, agent):
        """Transient errors should retry and eventually dead-letter."""
        mock_orch = MagicMock()
        mock_orch.handle_incident = AsyncMock(side_effect=ConnectionError("timeout"))

        result = _make_detect_result()
        agent._dispatch_base_delay = 0.01  # Fast for test

        with patch("src.incident_orchestrator.get_orchestrator", return_value=mock_orch):
            await agent._dispatch(result)

        assert mock_orch.handle_incident.await_count == agent._dispatch_max_retries
        assert agent._dispatch_failures == 1


# ── process_alert ────────────────────────────────────────────────────

class TestProcessAlert:
    @pytest.mark.asyncio
    async def test_process_alert_with_ingress_success(self, agent):
        mock_ingress = MagicMock()
        expected_result = _make_detect_result(detect_id="ingress-001")
        mock_ingress.process = AsyncMock(return_value=expected_result)
        agent._alert_ingress = mock_ingress

        alert = MagicMock(alert_id="alert-001")
        result = await agent.process_alert(alert)
        assert result.detect_id == "ingress-001"

    @pytest.mark.asyncio
    async def test_process_alert_duplicate_suppressed(self, agent):
        mock_ingress = MagicMock()
        mock_ingress.process = AsyncMock(return_value=None)  # Duplicate suppressed
        agent._alert_ingress = mock_ingress

        alert = MagicMock(alert_id="dup-alert")
        result = await agent.process_alert(alert)
        assert result.detect_id.startswith("dup-")

    @pytest.mark.asyncio
    async def test_process_alert_ingress_failure_fallback(self, agent):
        mock_ingress = MagicMock()
        mock_ingress.process = AsyncMock(side_effect=RuntimeError("boom"))
        agent._alert_ingress = mock_ingress

        alert = MagicMock(alert_id="fallback-alert")
        result = await agent.process_alert(alert)
        # Should fallback to run_detection
        assert result is not None
        assert result.source == "alarm_trigger"


# ── _enrich_topology ────────────────────────────────────────────────

class TestEnrichTopology:
    def test_enrich_skips_without_vpc_id(self, agent):
        result = _make_detect_result(
            anomalies_detected=[{"resource": "x"}]
        )
        # No VPC ID extractable → should skip gracefully
        agent._enrich_topology("det-1", result)
        assert result.topology_context is None

    def test_enrich_with_vpc_id(self, agent):
        result = _make_detect_result(
            anomalies_detected=[{"resource": "x", "node_id": "i-abc"}],
            raw_data={"vpc_id": "vpc-123"},
        )
        mock_ctx = MagicMock()
        mock_ctx.to_dict.return_value = {"vpc": "vpc-123"}
        mock_ctx.critical_anomalies = []

        with patch("src.rca.network_context.NetworkContextEnricher") as MockEnricher, \
             patch("src.aci.topology.cache.graph_cache") as mock_cache:
            MockEnricher.return_value.enrich.return_value = mock_ctx
            mock_cache.get_current.return_value = None
            agent._enrich_topology("det-2", result)

        assert result.topology_context == {"vpc": "vpc-123"}

    def test_enrich_handles_exception(self, agent):
        result = _make_detect_result(
            anomalies_detected=[{"resource": "x"}],
            raw_data={"vpc_id": "vpc-err"},
        )
        with patch("src.rca.network_context.NetworkContextEnricher", side_effect=ImportError("no module")):
            agent._enrich_topology("det-3", result)
        # Should not raise — non-fatal
        assert result.topology_context is None


# ── _extract_vpc_id / _extract_failed_resource ──────────────────────

class TestExtractHelpers:
    def test_extract_vpc_id_from_raw_data(self):
        result = _make_detect_result(raw_data={"vpc_id": "vpc-abc"})
        assert DetectAgent._extract_vpc_id(result) == "vpc-abc"

    def test_extract_vpc_id_from_event(self):
        event = MagicMock()
        event.vpc_id = "vpc-ev1"
        result = _make_detect_result()
        result.correlated_event = event
        assert DetectAgent._extract_vpc_id(result) == "vpc-ev1"

    def test_extract_vpc_id_none(self):
        result = _make_detect_result()
        assert DetectAgent._extract_vpc_id(result) is None

    def test_extract_failed_resource(self):
        result = _make_detect_result(
            anomalies_detected=[
                {"type": "cpu", "resource_id": "i-123"},
            ]
        )
        assert DetectAgent._extract_failed_resource(result) == "i-123"

    def test_extract_failed_resource_node_id(self):
        result = _make_detect_result(
            anomalies_detected=[{"type": "net", "node_id": "node-x"}]
        )
        assert DetectAgent._extract_failed_resource(result) == "node-x"

    def test_extract_failed_resource_none(self):
        result = _make_detect_result(anomalies_detected=[])
        assert DetectAgent._extract_failed_resource(result) is None


# ── get_detect_agent_async singleton ─────────────────────────────────

class TestSingleton:
    @pytest.mark.asyncio
    async def test_async_singleton(self):
        import src.detect_agent as mod
        old = mod._detect_agent
        mod._detect_agent = None
        try:
            with patch("src.event_correlator.get_correlator", return_value=MagicMock()):
                a1 = await get_detect_agent_async("us-west-2")
                a2 = await get_detect_agent_async("us-west-2")
                assert a1 is a2
        finally:
            mod._detect_agent = old
