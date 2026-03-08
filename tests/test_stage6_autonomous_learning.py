"""Tests for IncidentOrchestrator Stage 6 — Autonomous Learning Loops.

Validates ADR-009 §10: Stage 6 failures don't affect Stages 1-5.
"""

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.incident_orchestrator import IncidentOrchestrator, IncidentRecord, IncidentStatus


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestStage6AutonomousLearning(unittest.TestCase):
    """Test Stage 6: Post-RCA autonomous learning loops."""

    def _make_incident(self, incident_id="inc-test-001"):
        inc = IncidentRecord(
            incident_id=incident_id,
            trigger_type="alarm",
            trigger_data={},
            region="us-east-1",
        )
        inc.status = IncidentStatus.COMPLETED
        inc.resolution_log = ["kubectl delete pod/crashed-pod", "kubectl apply -f fix.yaml"]
        return inc

    def _make_rca_result(self):
        rca = MagicMock()
        rca.to_dict.return_value = {
            "root_cause": "OOM kill",
            "affected_service": "eks",
            "service": "eks",
            "alert_type": "pod_crash_loop",
            "confidence": 0.85,
            "symptoms": ["CrashLoopBackOff", "High memory"],
            "detection_source": "cloudwatch",
        }
        rca.confidence = 0.85
        return rca

    @patch("src.knowledge.flywheel.KnowledgeFlywheel")
    @patch("src.sop.auto_writer.SOPAutoWriter")
    @patch("src.skills.iteration.SkillGapDetector")
    @patch("src.skills.iteration.SkillIterationGuard")
    def test_stage6_happy_path(self, mock_guard_cls, mock_detector_cls, mock_writer_cls, mock_flywheel_cls):
        """All 3 sub-stages execute successfully."""
        orch = IncidentOrchestrator()
        inc = self._make_incident()
        rca = self._make_rca_result()

        # 6a: Flywheel
        mock_fw = AsyncMock()
        mock_flywheel_cls.return_value = mock_fw

        # 6b: SOPAutoWriter
        mock_writer = AsyncMock()
        mock_writer.evaluate_and_write = AsyncMock(return_value=MagicMock(sop_id="sop-test", status="draft"))
        mock_writer_cls.return_value = mock_writer

        # 6c: SkillGapDetector
        mock_detector = MagicMock()
        mock_detector.analyze_incident.return_value = MagicMock(
            gap_type="novel_tool_usage", suggested_skill_domain="kubectl_ext"
        )
        mock_detector_cls.return_value = mock_detector
        mock_guard = MagicMock()
        mock_guard.should_iterate.return_value = True
        mock_guard_cls.return_value = mock_guard

        _run(orch._autonomous_learning(inc, rca))

        mock_fw.capture.assert_called_once()
        mock_writer.evaluate_and_write.assert_called_once()
        mock_detector.analyze_incident.assert_called_once()
        mock_guard.record_iteration.assert_called_once()

    @patch("src.knowledge.flywheel.KnowledgeFlywheel")
    def test_stage6a_failure_does_not_block_6b_6c(self, mock_flywheel_cls):
        """Flywheel failure doesn't prevent SOP + Skill stages."""
        orch = IncidentOrchestrator()
        inc = self._make_incident()
        rca = self._make_rca_result()

        # 6a fails
        mock_fw = AsyncMock()
        mock_fw.capture = AsyncMock(side_effect=Exception("flywheel boom"))
        mock_flywheel_cls.return_value = mock_fw

        # Should not raise — defensive isolation
        _run(orch._autonomous_learning(inc, rca))

    @patch("src.sop.auto_writer.SOPAutoWriter")
    @patch("src.sop.auto_writer.SOPDeduplicator")
    @patch("src.knowledge.flywheel.KnowledgeFlywheel")
    def test_stage6b_failure_does_not_block_6c(self, mock_fw_cls, mock_dedup_cls, mock_writer_cls):
        """SOPAutoWriter failure doesn't prevent Skill gap detection."""
        orch = IncidentOrchestrator()
        inc = self._make_incident()
        rca = self._make_rca_result()

        mock_fw_cls.return_value = AsyncMock()
        mock_dedup_cls.return_value = MagicMock()
        mock_writer_cls.side_effect = Exception("writer init boom")

        # Should not raise
        _run(orch._autonomous_learning(inc, rca))

    @patch("src.skills.iteration.SkillGapDetector")
    @patch("src.skills.iteration.SkillIterationGuard")
    @patch("src.sop.auto_writer.SOPAutoWriter")
    @patch("src.sop.auto_writer.SOPDeduplicator")
    @patch("src.knowledge.flywheel.KnowledgeFlywheel")
    def test_stage6c_dedup_suppresses_iteration(
        self, mock_fw_cls, mock_dedup_cls, mock_writer_cls, mock_guard_cls, mock_detector_cls
    ):
        """SkillIterationGuard suppresses duplicate gap."""
        orch = IncidentOrchestrator()
        inc = self._make_incident()
        rca = self._make_rca_result()

        mock_fw_cls.return_value = AsyncMock()
        mock_dedup_cls.return_value = MagicMock()
        mock_writer = AsyncMock()
        mock_writer.evaluate_and_write = AsyncMock(return_value=None)
        mock_writer_cls.return_value = mock_writer

        mock_detector = MagicMock()
        mock_detector.analyze_incident.return_value = MagicMock(gap_type="novel_tool_usage")
        mock_detector_cls.return_value = mock_detector
        mock_guard = MagicMock()
        mock_guard.should_iterate.return_value = False  # Suppressed
        mock_guard_cls.return_value = mock_guard

        _run(orch._autonomous_learning(inc, rca))
        mock_guard.record_iteration.assert_not_called()

    def test_stage6_no_rca_dict(self):
        """Stage 6 handles rca_result without to_dict gracefully."""
        orch = IncidentOrchestrator()
        inc = self._make_incident()
        rca = "string_rca_result"  # No to_dict

        # Should not raise
        _run(orch._autonomous_learning(inc, rca))

    @patch("src.knowledge.flywheel.KnowledgeFlywheel")
    @patch("src.sop.auto_writer.SOPAutoWriter")
    @patch("src.sop.auto_writer.SOPDeduplicator")
    def test_stage6_no_resolution_log(self, mock_dedup_cls, mock_writer_cls, mock_fw_cls):
        """Stage 6 works when incident has no resolution_log attribute."""
        orch = IncidentOrchestrator()
        inc = self._make_incident()
        # Remove resolution_log
        if hasattr(inc, "resolution_log"):
            delattr(inc, "resolution_log")
        rca = self._make_rca_result()

        mock_fw_cls.return_value = AsyncMock()
        mock_dedup_cls.return_value = MagicMock()
        mock_writer = AsyncMock()
        mock_writer.evaluate_and_write = AsyncMock(return_value=None)
        mock_writer_cls.return_value = mock_writer

        _run(orch._autonomous_learning(inc, rca))


if __name__ == "__main__":
    unittest.main()
