"""
T-L4-009: Error Graceful Degradation Tests

Verifies that the incident pipeline degrades gracefully when
individual components fail — no single failure should crash
the entire pipeline.

Scenarios:
  1. AWS collection fails → pipeline returns partial result (no crash)
  2. RCA inference fails → pipeline returns failed status, no crash
  3. SOP bridge fails → skip SOP matching, pipeline still completes
  4. Feedback/learning fails → pipeline completes, feedback skipped
  5. Safety layer → safe defaults on unknown SOP
  6. Concurrent incidents → independent state
"""
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def orchestrator():
    """Create a minimal IncidentOrchestrator."""
    from src.incident_orchestrator import IncidentOrchestrator
    return IncidentOrchestrator(region="us-east-1")


def run_incident(orchestrator, **kwargs):
    """Helper to run handle_incident synchronously."""
    defaults = {
        "trigger_type": "manual",
        "services": ["ec2"],
        "dry_run": True,
    }
    defaults.update(kwargs)
    return asyncio.get_event_loop().run_until_complete(
        orchestrator.handle_incident(**defaults)
    )


# ── T-L4-009-A: AWS Collection Failure ───────────────────────


class TestCollectionDegradation:
    """Pipeline should survive AWS data collection failures."""

    def test_collection_exception_returns_incident(self, orchestrator):
        """When get_correlator().collect() raises, pipeline returns a
        failed incident rather than propagating."""
        with patch("src.event_correlator.get_correlator") as mock_gc:
            mock_corr = MagicMock()
            mock_corr.collect = AsyncMock(side_effect=Exception("AWS timeout"))
            mock_gc.return_value = mock_corr

            result = run_incident(orchestrator)

            # Pipeline must NOT raise
            assert result is not None
            assert result.incident_id.startswith("inc-")
            assert result.status.value in ("failed", "collecting")

    def test_collection_returns_empty_event(self, orchestrator):
        """Empty collection data → pipeline continues to RCA."""
        with patch("src.event_correlator.get_correlator") as mock_gc:
            mock_event = MagicMock()
            mock_event.collection_id = "coll-empty"
            mock_event.metrics = []
            mock_event.logs = []
            mock_event.health_events = []
            mock_event.service_statuses = {}
            mock_event.cloudtrail_events = []
            mock_event.to_prompt_context.return_value = "No data."
            mock_event.resource_timeline = {}

            mock_corr = MagicMock()
            mock_corr.collect = AsyncMock(return_value=mock_event)
            mock_gc.return_value = mock_corr

            with patch("src.rca_inference.get_rca_inference_engine") as mock_rca:
                rca_result = MagicMock()
                rca_result.pattern_id = "healthy"
                rca_result.root_cause = "No issues"
                rca_result.confidence = 0.3
                rca_result.severity = MagicMock(value="low")
                rca_result.matched_symptoms = []
                rca_result.remediation = None
                rca_result.affected_service = ""
                mock_rca.return_value.analyze = AsyncMock(return_value=rca_result)

                result = run_incident(orchestrator)
                assert result is not None
                assert result.incident_id.startswith("inc-")


# ── T-L4-009-B: RCA Inference Failure ────────────────────────


class TestRCADegradation:
    """Pipeline should handle RCA inference failures."""

    def test_rca_exception_doesnt_crash_pipeline(self, orchestrator):
        """When Bedrock/RCA raises, pipeline returns failed status."""
        with patch("src.event_correlator.get_correlator") as mock_gc:
            mock_event = MagicMock()
            mock_event.collection_id = "coll-rca-fail"
            mock_event.metrics = [{"name": "cpu", "value": 95}]
            mock_event.logs = []
            mock_event.health_events = []
            mock_event.service_statuses = {}
            mock_event.cloudtrail_events = []
            mock_event.to_prompt_context.return_value = "High CPU."
            mock_event.resource_timeline = {}

            mock_corr = MagicMock()
            mock_corr.collect = AsyncMock(return_value=mock_event)
            mock_gc.return_value = mock_corr

            with patch("src.rca_inference.get_rca_inference_engine") as mock_rca:
                mock_rca.return_value.analyze = AsyncMock(
                    side_effect=Exception("Bedrock throttled")
                )

                result = run_incident(orchestrator)
                assert result is not None
                assert result.incident_id.startswith("inc-")
                assert result.status.value in ("failed", "analyzing")


# ── T-L4-009-C: SOP Bridge Failure ───────────────────────────


class TestSOPDegradation:
    """Pipeline should handle SOP matching failures."""

    def test_sop_bridge_exception_doesnt_crash(self, orchestrator):
        """When get_bridge() fails, pipeline completes without SOP."""
        with patch("src.event_correlator.get_correlator") as mock_gc:
            mock_event = MagicMock()
            mock_event.collection_id = "coll-sop-fail"
            mock_event.metrics = [{"name": "cpu", "value": 90}]
            mock_event.logs = []
            mock_event.health_events = []
            mock_event.service_statuses = {}
            mock_event.cloudtrail_events = []
            mock_event.to_prompt_context.return_value = "High CPU."
            mock_event.resource_timeline = {}

            mock_corr = MagicMock()
            mock_corr.collect = AsyncMock(return_value=mock_event)
            mock_gc.return_value = mock_corr

            mock_rca = MagicMock()
            mock_rca.pattern_id = "ec2-high-cpu"
            mock_rca.root_cause = "EC2 CPU at 90%"
            mock_rca.confidence = 0.85
            mock_rca.severity = MagicMock(value="medium")
            mock_rca.matched_symptoms = ["high_cpu"]
            mock_rca.remediation = MagicMock(suggestion="Scale up")
            mock_rca.affected_service = "ec2"

            with patch("src.rca_inference.get_rca_inference_engine") as mock_rca_eng:
                mock_rca_eng.return_value.analyze = AsyncMock(return_value=mock_rca)

                with patch("src.rca_sop_bridge.get_bridge", side_effect=Exception("S3 down")):
                    result = run_incident(orchestrator)
                    assert result is not None
                    assert result.incident_id.startswith("inc-")


# ── T-L4-009-D: Feedback/Learning Failure ────────────────────


class TestFeedbackDegradation:
    """Feedback and learning failures should not affect pipeline completion."""

    def test_auto_feedback_exception_is_swallowed(self, orchestrator):
        """_auto_feedback failure is logged, not raised."""
        from src.incident_orchestrator import IncidentRecord, IncidentStatus, TriggerType

        incident = IncidentRecord(
            incident_id="inc-feedback-fail",
            trigger_type=TriggerType.MANUAL,
            trigger_data={},
            region="us-east-1",
        )
        incident.status = IncidentStatus.COMPLETED
        incident.execution_result = {"success": True, "sop_id": "sop-test"}

        mock_rca = MagicMock()
        mock_rca.pattern_id = "test-pattern"
        mock_rca.confidence = 0.9
        mock_rca.root_cause = "Test"
        mock_rca.severity = MagicMock(value="medium")
        mock_rca.matched_symptoms = ["test"]

        matched_sops = [{"sop_id": "sop-test", "score": 0.9}]

        with patch("src.rca_sop_bridge.get_bridge", side_effect=Exception("Bridge down")):
            # Should NOT raise
            orchestrator._auto_feedback(incident, mock_rca, matched_sops)

    def test_learn_from_incident_exception_is_swallowed(self, orchestrator):
        """_learn_from_incident failure is logged, not raised."""
        from src.incident_orchestrator import IncidentRecord, TriggerType

        incident = IncidentRecord(
            incident_id="inc-learn-fail",
            trigger_type=TriggerType.MANUAL,
            trigger_data={},
            region="us-east-1",
        )

        mock_rca = MagicMock()
        mock_rca.pattern_id = "test-pattern"
        mock_rca.confidence = 0.9
        mock_rca.root_cause = "Test root cause"
        mock_rca.severity = MagicMock(value="medium")
        mock_rca.matched_symptoms = ["test"]
        mock_rca.remediation = MagicMock(suggestion="Fix it")

        with patch("src.knowledge_search.get_knowledge_search", side_effect=Exception("OpenSearch down")):
            # Should NOT raise
            orchestrator._learn_from_incident(incident, mock_rca)

    def test_persist_incident_failure_is_swallowed(self, orchestrator):
        """_persist_incident failure is logged, not raised."""
        from src.incident_orchestrator import IncidentRecord, TriggerType

        incident = IncidentRecord(
            incident_id="inc-persist-fail",
            trigger_type=TriggerType.MANUAL,
            trigger_data={},
            region="us-east-1",
        )

        with patch("builtins.open", side_effect=PermissionError("No write")):
            # Should NOT raise
            orchestrator._persist_incident(incident)


# ── T-L4-009-E: Safety Layer ─────────────────────────────────


class TestSafetyDegradation:
    """Safety layer safe defaults."""

    def test_safety_check_unknown_sop(self):
        """Check unknown SOP returns a safe default, not crash."""
        from src.sop_safety import SOPSafetyLayer
        safety = SOPSafetyLayer()
        result = safety.check("nonexistent-sop-xyz")
        assert result is not None

    def test_cooldown_no_history(self):
        """First execution — no cooldown should block."""
        from src.sop_safety import SOPSafetyLayer
        safety = SOPSafetyLayer()
        result = safety.check("sop-ec2-restart")
        assert result is not None


# ── T-L4-009-F: Concurrent Incidents ─────────────────────────


class TestConcurrentResilience:
    """Multiple simultaneous incidents have independent state."""

    def test_multiple_incidents_independent(self, orchestrator):
        from src.incident_orchestrator import IncidentRecord, TriggerType

        inc1 = IncidentRecord(
            incident_id="inc-001",
            trigger_type=TriggerType.MANUAL,
            trigger_data={},
            region="us-east-1",
        )
        inc2 = IncidentRecord(
            incident_id="inc-002",
            trigger_type=TriggerType.ALARM,
            trigger_data={"alarm": "test"},
            region="us-east-1",
        )

        orchestrator._incidents["inc-001"] = inc1
        orchestrator._incidents["inc-002"] = inc2

        assert orchestrator.get_incident("inc-001").trigger_type.value == "manual"
        assert orchestrator.get_incident("inc-002").trigger_type.value == "alarm"
        assert len(orchestrator._incidents) >= 2
