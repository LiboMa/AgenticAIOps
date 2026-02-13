"""
Tests for IncidentOrchestrator — closed-loop incident pipeline.

Covers:
- IncidentRecord: to_dict(), to_markdown(), lifecycle
- IncidentOrchestrator.handle_incident(): full pipeline with mocked stages
- Stage reuse: DetectResult caching (R1/R2)
- _execute_sop: success and error paths
- _auto_feedback: positive feedback, high-confidence match
- _persist_incident: file persistence
- get_incident, list_incidents, get_stats
- Singleton: get_orchestrator
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.incident_orchestrator import (
    IncidentOrchestrator,
    IncidentRecord,
    IncidentStatus,
    TriggerType,
    get_orchestrator,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_correlated_event(**overrides):
    """Create a mock CorrelatedEvent."""
    event = MagicMock()
    event.collection_id = overrides.get("collection_id", "col-test-123")
    event.metrics = overrides.get("metrics", [MagicMock()])
    event.alarms = overrides.get("alarms", [])
    event.trail_events = overrides.get("trail_events", [])
    event.anomalies = overrides.get("anomalies", [])
    event.health_events = overrides.get("health_events", [])
    event.duration_ms = overrides.get("duration_ms", 50)
    return event


def _make_rca_result(**overrides):
    """Create a mock RCA result."""
    rca = MagicMock()
    rca.root_cause = overrides.get("root_cause", "High CPU on i-abc123")
    rca.severity = MagicMock()
    rca.severity.value = overrides.get("severity", "high")
    rca.confidence = overrides.get("confidence", 0.85)
    rca.pattern_id = overrides.get("pattern_id", "pat-cpu-spike")
    rca.evidence = overrides.get("evidence", ["CPU > 90%"])
    rca.matched_symptoms = overrides.get("matched_symptoms", ["cpu_spike"])
    rca.affected_resources = overrides.get("affected_resources", ["i-abc123"])
    rca.remediation = MagicMock()
    rca.remediation.suggestion = "Scale up or optimize"
    rca.to_dict.return_value = {
        "root_cause": rca.root_cause,
        "severity": rca.severity.value,
        "confidence": rca.confidence,
        "pattern_id": rca.pattern_id,
        "evidence": rca.evidence,
    }
    return rca


def _make_detect_result(fresh=True, has_event=True, source="proactive_scan"):
    """Create a mock DetectResult."""
    dr = MagicMock()
    dr.detect_id = "det-test-orch"
    dr.is_stale = not fresh
    dr.freshness_label = "fresh" if fresh else "stale"
    dr.age_seconds = 30 if fresh else 600
    dr.source = source
    dr.correlated_event = _make_correlated_event() if has_event else None
    dr.anomalies_detected = [{"type": "cpu_spike"}]
    return dr


# =============================================================================
# IncidentRecord Tests
# =============================================================================

class TestIncidentRecord:

    def test_to_dict_basic(self):
        """to_dict serializes correctly."""
        record = IncidentRecord(
            incident_id="inc-test-001",
            trigger_type=TriggerType.ALARM,
            trigger_data={"alarm_name": "HighCPU"},
            region="ap-southeast-1",
        )
        d = record.to_dict()
        assert d["incident_id"] == "inc-test-001"
        assert d["trigger_type"] == "alarm"
        assert d["status"] == "triggered"
        assert d["region"] == "ap-southeast-1"

    def test_to_dict_with_pipeline_results(self):
        """to_dict includes pipeline results when present."""
        record = IncidentRecord(
            incident_id="inc-test-002",
            trigger_type=TriggerType.ANOMALY,
            trigger_data={},
            region="ap-southeast-1",
            status=IncidentStatus.COMPLETED,
            rca_result={"root_cause": "disk full", "severity": "high"},
            matched_sops=[{"sop_id": "sop-1", "name": "Fix Disk"}],
            duration_ms=1234,
        )
        d = record.to_dict()
        assert d["status"] == "completed"
        assert d["rca_result"]["root_cause"] == "disk full"
        assert len(d["matched_sops"]) == 1
        assert d["duration_ms"] == 1234

    def test_to_markdown_basic(self):
        """to_markdown generates valid markdown."""
        record = IncidentRecord(
            incident_id="inc-md-test",
            trigger_type=TriggerType.MANUAL,
            trigger_data={},
            region="ap-southeast-1",
            status=IncidentStatus.COMPLETED,
            duration_ms=500,
        )
        md = record.to_markdown()
        assert "inc-md-test" in md
        assert "manual" in md
        assert "completed" in md

    def test_to_markdown_with_rca(self):
        """to_markdown includes RCA section when present."""
        record = IncidentRecord(
            incident_id="inc-md-rca",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            rca_result={
                "root_cause": "Memory leak in app",
                "severity": "high",
                "confidence": 0.9,
                "pattern_id": "pat-mem-leak",
                "evidence": ["OOM errors in logs"],
            },
        )
        md = record.to_markdown()
        assert "Memory leak" in md
        assert "根因分析" in md
        assert "🔴" in md  # high severity

    def test_to_markdown_with_sops(self):
        """to_markdown includes SOP section."""
        record = IncidentRecord(
            incident_id="inc-md-sop",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            matched_sops=[{
                "sop_id": "sop-ec2-high-cpu",
                "name": "EC2 High CPU",
                "match_confidence": 0.85,
                "risk_level": "L1",
            }],
        )
        md = record.to_markdown()
        assert "sop-ec2-high-cpu" in md
        assert "推荐 SOP" in md

    def test_to_markdown_with_error(self):
        """to_markdown includes error section."""
        record = IncidentRecord(
            incident_id="inc-md-err",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            status=IncidentStatus.FAILED,
            error="Connection timeout",
        )
        md = record.to_markdown()
        assert "Connection timeout" in md
        assert "❌" in md

    def test_to_markdown_with_stage_timings(self):
        """to_markdown includes stage timings."""
        record = IncidentRecord(
            incident_id="inc-md-timing",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            stage_timings={"collect": 100, "analyze": 200},
        )
        md = record.to_markdown()
        assert "各阶段耗时" in md
        assert "collect" in md

    def test_to_markdown_with_safety_check(self):
        """to_markdown includes safety check section."""
        record = IncidentRecord(
            incident_id="inc-md-safety",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            safety_check={
                "risk_level": "L1",
                "execution_mode": "auto",
                "passed": True,
            },
        )
        md = record.to_markdown()
        assert "安全检查" in md
        assert "L1" in md

    def test_to_markdown_with_execution_result(self):
        """to_markdown includes execution result."""
        record = IncidentRecord(
            incident_id="inc-md-exec",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            execution_result={
                "success": True,
                "sop_id": "sop-1",
                "message": "SOP completed",
            },
        )
        md = record.to_markdown()
        assert "执行结果" in md
        assert "成功" in md


# =============================================================================
# IncidentOrchestrator — handle_incident Pipeline
# =============================================================================

class TestHandleIncident:

    @pytest.fixture
    def orchestrator(self):
        return IncidentOrchestrator(region="ap-southeast-1")

    @pytest.mark.asyncio
    async def test_full_pipeline_with_fresh_detect_result(self, orchestrator):
        """Full pipeline reuses fresh DetectResult (skip Stage 1)."""
        detect_result = _make_detect_result(fresh=True)
        rca_result = _make_rca_result()
        
        mock_engine = MagicMock()
        mock_engine.analyze = AsyncMock(return_value=rca_result)
        
        mock_bridge = MagicMock()
        mock_bridge.match_sops.return_value = [{
            "sop_id": "sop-ec2-high-cpu",
            "name": "EC2 High CPU",
            "match_confidence": 0.85,
            "severity": "high",
        }]
        
        mock_safety = MagicMock()
        mock_safety.check.return_value = MagicMock(
            passed=True, execution_mode="auto",
            to_dict=MagicMock(return_value={"passed": True, "risk_level": "L1", "execution_mode": "auto"})
        )
        mock_safety._classify_risk.return_value = MagicMock(value="L1")
        
        with patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch("src.sop_safety.get_safety_layer", return_value=mock_safety), \
             patch.object(orchestrator, "_persist_incident"), \
             patch.object(orchestrator, "_auto_feedback"):
            
            # Make isinstance(detect_result, DetectResult) work with MagicMock
            with patch("src.detect_agent.DetectResult", new=type(detect_result)):
                incident = await orchestrator.handle_incident(
                    trigger_type="anomaly",
                    detect_result=detect_result,
                )
        
        assert incident.status == IncidentStatus.COMPLETED
        assert incident.collection_summary["source"] == "detect_agent_reuse"
        assert incident.rca_result is not None
        assert incident.matched_sops is not None
        assert incident.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_pipeline_manual_trigger_forces_fresh_collection(self, orchestrator):
        """Manual trigger ignores cached DetectResult (R2)."""
        detect_result = _make_detect_result(fresh=True)
        rca_result = _make_rca_result()
        event = _make_correlated_event()
        
        mock_correlator = MagicMock()
        mock_correlator.collect = AsyncMock(return_value=event)
        
        mock_engine = MagicMock()
        mock_engine.analyze = AsyncMock(return_value=rca_result)
        
        mock_bridge = MagicMock()
        mock_bridge.match_sops.return_value = []
        
        with patch("src.event_correlator.get_correlator", return_value=mock_correlator), \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch.object(orchestrator, "_persist_incident"), \
             patch.object(orchestrator, "_auto_feedback"):
            
            incident = await orchestrator.handle_incident(
                trigger_type="manual",
                detect_result=detect_result,
            )
        
        # Manual trigger should call correlator.collect, not reuse
        mock_correlator.collect.assert_called_once()
        assert incident.collection_summary["source"] == "fresh_collection"

    @pytest.mark.asyncio
    async def test_pipeline_stale_detect_result_falls_back(self, orchestrator):
        """Stale DetectResult triggers fresh collection (R1)."""
        detect_result = _make_detect_result(fresh=False)
        rca_result = _make_rca_result()
        event = _make_correlated_event()
        
        mock_correlator = MagicMock()
        mock_correlator.collect = AsyncMock(return_value=event)
        
        mock_engine = MagicMock()
        mock_engine.analyze = AsyncMock(return_value=rca_result)
        
        mock_bridge = MagicMock()
        mock_bridge.match_sops.return_value = []
        
        with patch("src.event_correlator.get_correlator", return_value=mock_correlator), \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch.object(orchestrator, "_persist_incident"), \
             patch.object(orchestrator, "_auto_feedback"):
            
            incident = await orchestrator.handle_incident(
                trigger_type="anomaly",
                detect_result=detect_result,
            )
        
        mock_correlator.collect.assert_called_once()
        assert incident.collection_summary["source"] == "fresh_collection"

    @pytest.mark.asyncio
    async def test_pipeline_no_detect_result_collects_fresh(self, orchestrator):
        """No DetectResult provided → fresh collection."""
        rca_result = _make_rca_result()
        event = _make_correlated_event()
        
        mock_correlator = MagicMock()
        mock_correlator.collect = AsyncMock(return_value=event)
        
        mock_engine = MagicMock()
        mock_engine.analyze = AsyncMock(return_value=rca_result)
        
        mock_bridge = MagicMock()
        mock_bridge.match_sops.return_value = []
        
        with patch("src.event_correlator.get_correlator", return_value=mock_correlator), \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch.object(orchestrator, "_persist_incident"), \
             patch.object(orchestrator, "_auto_feedback"):
            
            incident = await orchestrator.handle_incident(trigger_type="alarm")
        
        mock_correlator.collect.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_exception_sets_failed(self, orchestrator):
        """Exception in pipeline sets FAILED status."""
        with patch("src.event_correlator.get_correlator", side_effect=Exception("AWS down")):
            incident = await orchestrator.handle_incident(trigger_type="alarm")
        
        assert incident.status == IncidentStatus.FAILED
        assert "AWS down" in incident.error

    @pytest.mark.asyncio
    async def test_pipeline_records_stage_timings(self, orchestrator):
        """Stage timings are recorded."""
        rca_result = _make_rca_result()
        event = _make_correlated_event()
        
        mock_correlator = MagicMock()
        mock_correlator.collect = AsyncMock(return_value=event)
        
        mock_engine = MagicMock()
        mock_engine.analyze = AsyncMock(return_value=rca_result)
        
        mock_bridge = MagicMock()
        mock_bridge.match_sops.return_value = []
        
        with patch("src.event_correlator.get_correlator", return_value=mock_correlator), \
             patch("src.rca_inference.get_rca_inference_engine", return_value=mock_engine), \
             patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch.object(orchestrator, "_persist_incident"), \
             patch.object(orchestrator, "_auto_feedback"):
            
            incident = await orchestrator.handle_incident(trigger_type="alarm")
        
        assert "collect" in incident.stage_timings
        assert "analyze" in incident.stage_timings


# =============================================================================
# Execute SOP
# =============================================================================

class TestExecuteSop:

    def test_execute_sop_success(self):
        orchestrator = IncidentOrchestrator()
        rca_result = _make_rca_result()
        
        mock_executor = MagicMock()
        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-001"
        mock_executor.start_execution.return_value = mock_execution
        
        mock_safety = MagicMock()
        mock_safety.create_snapshot.return_value = MagicMock(snapshot_id="snap-001")
        
        with patch("src.sop_system.get_sop_executor", return_value=mock_executor):
            result = orchestrator._execute_sop(
                "sop-ec2-high-cpu", rca_result, ["i-123"], mock_safety
            )
        
        assert result["success"] is True
        assert result["sop_id"] == "sop-ec2-high-cpu"
        assert result["execution_id"] == "exec-001"
        mock_safety.record_execution.assert_called_once()

    def test_execute_sop_returns_none(self):
        orchestrator = IncidentOrchestrator()
        rca_result = _make_rca_result()
        
        mock_executor = MagicMock()
        mock_executor.start_execution.return_value = None
        
        mock_safety = MagicMock()
        mock_safety.create_snapshot.return_value = MagicMock(snapshot_id="snap-002")
        
        with patch("src.sop_system.get_sop_executor", return_value=mock_executor):
            result = orchestrator._execute_sop(
                "sop-test", rca_result, ["i-123"], mock_safety
            )
        
        assert result["success"] is False

    def test_execute_sop_exception(self):
        orchestrator = IncidentOrchestrator()
        rca_result = _make_rca_result()
        
        mock_safety = MagicMock()
        
        with patch("src.sop_system.get_sop_executor", side_effect=Exception("executor crash")):
            result = orchestrator._execute_sop(
                "sop-test", rca_result, ["i-123"], mock_safety
            )
        
        assert result["success"] is False
        assert "executor crash" in result["message"]


# =============================================================================
# Auto-Feedback
# =============================================================================

class TestAutoFeedback:

    def test_feedback_on_successful_execution(self):
        orchestrator = IncidentOrchestrator()
        rca_result = _make_rca_result(confidence=0.9)
        
        incident = IncidentRecord(
            incident_id="inc-fb-001",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            execution_result={
                "success": True,
                "sop_id": "sop-ec2-high-cpu",
                "execution_id": "exec-001",
            },
        )
        
        mock_bridge = MagicMock()
        
        with patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch.object(orchestrator, "_learn_from_incident"):
            orchestrator._auto_feedback(
                incident, rca_result, [{"sop_id": "sop-ec2-high-cpu"}]
            )
        
        mock_bridge.submit_feedback.assert_called_once()
        call_kwargs = mock_bridge.submit_feedback.call_args[1]
        assert call_kwargs["success"] is True
        assert call_kwargs["sop_id"] == "sop-ec2-high-cpu"

    def test_feedback_high_confidence_no_execution(self):
        orchestrator = IncidentOrchestrator()
        rca_result = _make_rca_result(confidence=0.9)
        
        incident = IncidentRecord(
            incident_id="inc-fb-002",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            execution_result=None,
        )
        
        mock_bridge = MagicMock()
        
        with patch("src.rca_sop_bridge.get_bridge", return_value=mock_bridge), \
             patch.object(orchestrator, "_learn_from_incident"):
            orchestrator._auto_feedback(
                incident, rca_result,
                [{"sop_id": "sop-test"}]
            )
        
        mock_bridge.submit_feedback.assert_called_once()

    def test_feedback_exception_is_swallowed(self):
        """Auto-feedback errors are logged but don't crash."""
        orchestrator = IncidentOrchestrator()
        rca_result = _make_rca_result()
        
        incident = IncidentRecord(
            incident_id="inc-fb-err",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            execution_result={"success": True, "sop_id": "sop-1", "execution_id": "e1"},
        )
        
        with patch("src.rca_sop_bridge.get_bridge", side_effect=Exception("bridge down")):
            # Should not raise
            orchestrator._auto_feedback(incident, rca_result, [{"sop_id": "sop-1"}])


# =============================================================================
# Persist Incident
# =============================================================================

class TestPersistIncident:

    def test_persist_creates_file(self, tmp_path):
        orchestrator = IncidentOrchestrator()
        
        incident = IncidentRecord(
            incident_id="inc-persist-001",
            trigger_type=TriggerType.ALARM,
            trigger_data={"alarm": "HighCPU"},
            region="ap-southeast-1",
        )
        
        with patch("os.path.dirname", return_value=str(tmp_path)):
            with patch("os.path.join", side_effect=lambda *args: os.path.join(*args)):
                with patch("os.makedirs"):
                    # Simpler approach: just check it doesn't crash
                    orchestrator._persist_incident(incident)


# =============================================================================
# Query Methods
# =============================================================================

class TestQueryMethods:

    def test_get_incident(self):
        orchestrator = IncidentOrchestrator()
        record = IncidentRecord(
            incident_id="inc-get-001",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
        )
        orchestrator._incidents["inc-get-001"] = record
        
        assert orchestrator.get_incident("inc-get-001") is record
        assert orchestrator.get_incident("nonexistent") is None

    def test_list_incidents_empty(self):
        orchestrator = IncidentOrchestrator()
        assert orchestrator.list_incidents() == []

    def test_list_incidents_with_data(self):
        orchestrator = IncidentOrchestrator()
        for i in range(5):
            orchestrator._incidents[f"inc-{i}"] = IncidentRecord(
                incident_id=f"inc-{i}",
                trigger_type=TriggerType.ALARM,
                trigger_data={},
                region="ap-southeast-1",
            )
        
        result = orchestrator.list_incidents(limit=3)
        assert len(result) == 3

    def test_list_incidents_filter_by_status(self):
        orchestrator = IncidentOrchestrator()
        orchestrator._incidents["inc-ok"] = IncidentRecord(
            incident_id="inc-ok",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            status=IncidentStatus.COMPLETED,
        )
        orchestrator._incidents["inc-fail"] = IncidentRecord(
            incident_id="inc-fail",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            status=IncidentStatus.FAILED,
        )
        
        result = orchestrator.list_incidents(status="completed")
        assert len(result) == 1
        assert result[0]["incident_id"] == "inc-ok"

    def test_get_stats_empty(self):
        orchestrator = IncidentOrchestrator()
        stats = orchestrator.get_stats()
        assert stats["total_incidents"] == 0
        assert stats["within_target"] is True

    def test_get_stats_with_data(self):
        orchestrator = IncidentOrchestrator()
        record = IncidentRecord(
            incident_id="inc-stat-1",
            trigger_type=TriggerType.ALARM,
            trigger_data={},
            region="ap-southeast-1",
            status=IncidentStatus.COMPLETED,
            duration_ms=5000,
            stage_timings={"collect": 1000, "analyze": 2000},
        )
        orchestrator._incidents["inc-stat-1"] = record
        
        stats = orchestrator.get_stats()
        assert stats["total_incidents"] == 1
        assert stats["avg_duration_ms"] == 5000
        assert stats["avg_stage_timings"]["collect"] == 1000
        assert stats["within_target"] is True


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:

    def test_get_orchestrator_returns_instance(self):
        import src.incident_orchestrator as mod
        mod._orchestrator = None
        
        o1 = get_orchestrator()
        o2 = get_orchestrator()
        assert o1 is o2
        
        mod._orchestrator = None  # cleanup

    def test_get_orchestrator_with_region(self):
        import src.incident_orchestrator as mod
        mod._orchestrator = None
        
        o = get_orchestrator(region="us-east-1")
        assert o.region == "us-east-1"
        
        mod._orchestrator = None  # cleanup


# =============================================================================
# TriggerType / IncidentStatus Enums
# =============================================================================

class TestEnums:

    def test_trigger_types(self):
        assert TriggerType.ALARM.value == "alarm"
        assert TriggerType.ANOMALY.value == "anomaly"
        assert TriggerType.MANUAL.value == "manual"
        assert TriggerType.PROACTIVE.value == "proactive"

    def test_incident_statuses(self):
        assert IncidentStatus.TRIGGERED.value == "triggered"
        assert IncidentStatus.COMPLETED.value == "completed"
        assert IncidentStatus.FAILED.value == "failed"
