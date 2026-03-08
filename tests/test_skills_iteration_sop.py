"""Tests for Module C (Skills self-bootstrap) and Module D (SOP auto-writer).

Covers: SkillGapDetector, SkillSpecBuilder, SkillValidator, SkillIterationGuard,
        SOPDocument, SOPAutoWriter, SOPDeduplicator
"""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.skills.iteration.gap_detector import SkillGapDetector, SkillGap
from src.skills.iteration.spec_builder import SkillSpecBuilder, HarnessTask
from src.skills.iteration.validator import SkillValidator, SkillDraft, ValidationResult
from src.skills.iteration.guard import SkillIterationGuard
from src.sop import SOPDocument, SOPStep, RemediationPlan
from src.sop.auto_writer import SOPAutoWriter, SOPDeduplicator


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =====================================================================
# Module C: SkillGapDetector
# =====================================================================

class TestSkillGapDetector(unittest.TestCase):

    def setUp(self):
        self.detector = SkillGapDetector()

    def test_detect_novel_tool_usage(self):
        """Unknown commands in resolution log trigger novel_tool_usage."""
        rca = {"service": "eks", "alert_type": "pod_crash"}
        gap = self.detector.analyze_incident(
            "inc-001", rca, resolution_log=["helmfile", "kustomize build"]
        )
        self.assertIsNotNone(gap)
        self.assertEqual(gap.gap_type, "novel_tool_usage")
        self.assertIn("helmfile", gap.uncovered_commands)

    def test_no_gap_when_all_known(self):
        """Known commands don't trigger a gap."""
        rca = {"service": "linux", "confidence": 0.9, "detection_source": "cloudwatch"}
        gap = self.detector.analyze_incident(
            "inc-002", rca, resolution_log=["kubectl get pods", "grep error"]
        )
        self.assertIsNone(gap)

    def test_detect_repeated_manual(self):
        """≥3 similar incidents trigger repeated_manual."""
        rca = {"service": "eks", "similar_incident_count": 5, "detection_source": "cloudwatch", "confidence": 0.9}
        gap = self.detector.analyze_incident("inc-003", rca, resolution_log=["kubectl get pods"])
        self.assertIsNotNone(gap)
        self.assertEqual(gap.gap_type, "repeated_manual")
        self.assertEqual(gap.repeat_count, 5)

    def test_detect_detection_miss(self):
        """Manual detection source triggers detection_miss."""
        rca = {"service": "rds", "detection_source": "manual", "confidence": 0.9}
        gap = self.detector.analyze_incident("inc-004", rca, resolution_log=["psql -c 'SELECT 1'"])
        self.assertIsNotNone(gap)
        self.assertEqual(gap.gap_type, "detection_miss")

    def test_detect_low_confidence(self):
        """Low RCA confidence triggers low_confidence."""
        rca = {"service": "ec2", "confidence": 0.1, "detection_source": "cloudwatch"}
        gap = self.detector.analyze_incident("inc-005", rca, resolution_log=["top"])
        self.assertIsNotNone(gap)
        self.assertEqual(gap.gap_type, "low_confidence")

    def test_no_gap_high_confidence(self):
        """High confidence + known commands + automated detection → no gap."""
        rca = {
            "service": "eks", "confidence": 0.95,
            "detection_source": "cloudwatch", "similar_incident_count": 1,
        }
        gap = self.detector.analyze_incident("inc-006", rca, resolution_log=["kubectl get pods"])
        self.assertIsNone(gap)

    def test_priority_novel_over_repeated(self):
        """Novel tool usage has priority over repeated manual."""
        rca = {"service": "eks", "similar_incident_count": 5, "detection_source": "cloudwatch", "confidence": 0.9}
        gap = self.detector.analyze_incident(
            "inc-007", rca, resolution_log=["helmfile sync"]
        )
        self.assertEqual(gap.gap_type, "novel_tool_usage")


class TestSkillGap(unittest.TestCase):

    def test_commands_hash_deterministic(self):
        gap = SkillGap(gap_type="novel_tool_usage", uncovered_commands=["foo", "bar"])
        h1 = gap.commands_hash
        gap2 = SkillGap(gap_type="novel_tool_usage", uncovered_commands=["bar", "foo"])
        self.assertEqual(h1, gap2.commands_hash)  # sorted

    def test_to_dict(self):
        gap = SkillGap(gap_type="detection_miss", incident_id="inc-1")
        d = gap.to_dict()
        self.assertEqual(d["gap_type"], "detection_miss")
        self.assertEqual(d["incident_id"], "inc-1")


# =====================================================================
# Module C: SkillSpecBuilder
# =====================================================================

class TestSkillSpecBuilder(unittest.TestCase):

    def test_build_task(self):
        builder = SkillSpecBuilder()
        gap = SkillGap(
            gap_type="novel_tool_usage",
            suggested_skill_domain="helm",
            uncovered_commands=["helmfile"],
        )
        task = builder.build_task(gap)
        self.assertIsInstance(task, HarnessTask)
        self.assertIn("helm", task.output_dir)
        self.assertIn("SKILL.md", task.expected_files)
        self.assertIn("helmfile", task.task)

    def test_build_task_with_incident(self):
        builder = SkillSpecBuilder()
        gap = SkillGap(gap_type="repeated_manual", suggested_skill_domain="rds")
        incident = MagicMock()
        incident.to_dict.return_value = {"incident_id": "inc-1", "service": "rds"}
        task = builder.build_task(gap, incident)
        self.assertIn("rds", task.task)


# =====================================================================
# Module C: SkillValidator
# =====================================================================

class TestSkillValidator(unittest.TestCase):

    def setUp(self):
        self.validator = SkillValidator()

    def _make_draft(self, tools_py="", skill_md="", test_py=""):
        return SkillDraft(
            domain="test",
            skill_md_content=skill_md,
            tools_py_content=tools_py,
            test_content=test_py,
        )

    def test_pass_valid_skill(self):
        skill_md = """---
name: test_skill
version: "1.0"
tools:
  - check_status
---
# Test Skill
"""
        tools_py = """
from some_module import secure_tool

@secure_tool
def check_status():
    return "ok"
"""
        draft = self._make_draft(tools_py=tools_py, skill_md=skill_md)
        result = self.validator.validate(draft)
        self.assertTrue(result.passed, f"Errors: {result.errors}")

    def test_l1_blocked_call_os_system(self):
        tools_py = """
import os
def run():
    os.system("rm -rf /")
"""
        draft = self._make_draft(tools_py=tools_py, skill_md="---\nname: x\nversion: '1'\n---\n")
        result = self.validator.validate(draft)
        self.assertFalse(result.passed)
        self.assertTrue(any("os.system" in e for e in result.errors))

    def test_l1_blocked_eval(self):
        tools_py = "def run():\n    return eval('1+1')\n"
        draft = self._make_draft(tools_py=tools_py, skill_md="---\nname: x\nversion: '1'\n---\n")
        result = self.validator.validate(draft)
        self.assertFalse(result.passed)
        self.assertTrue(any("eval" in e for e in result.errors))

    def test_l1_syntax_error(self):
        tools_py = "def run(\n"
        draft = self._make_draft(tools_py=tools_py, skill_md="---\nname: x\nversion: '1'\n---\n")
        result = self.validator.validate(draft)
        self.assertFalse(result.passed)
        self.assertTrue(any("Syntax" in e for e in result.errors))

    def test_l2_missing_frontmatter(self):
        draft = self._make_draft(tools_py="pass", skill_md="# No frontmatter")
        result = self.validator.validate(draft)
        self.assertFalse(result.passed)
        self.assertTrue(any("frontmatter" in e.lower() for e in result.errors))

    def test_l2_missing_name(self):
        skill_md = "---\nversion: '1'\n---\n"
        draft = self._make_draft(tools_py="pass", skill_md=skill_md)
        result = self.validator.validate(draft)
        self.assertFalse(result.passed)
        self.assertTrue(any("name" in e for e in result.errors))

    def test_l3_missing_secure_tool(self):
        tools_py = "def public_function():\n    pass\n"
        skill_md = "---\nname: x\nversion: '1'\n---\n"
        draft = self._make_draft(tools_py=tools_py, skill_md=skill_md)
        result = self.validator.validate(draft)
        self.assertFalse(result.passed)
        self.assertTrue(any("secure_tool" in e for e in result.errors))

    def test_l3_private_function_ok(self):
        tools_py = """
from mod import secure_tool

@secure_tool
def check():
    pass

def _helper():
    pass
"""
        skill_md = "---\nname: x\nversion: '1'\n---\n"
        draft = self._make_draft(tools_py=tools_py, skill_md=skill_md)
        result = self.validator.validate(draft)
        self.assertTrue(result.passed, f"Errors: {result.errors}")

    def test_l4_write_ops_with_readonly_tier(self):
        tools_py = """
from mod import secure_tool

@secure_tool
def cleanup_resources():
    # This function will delete and remove stale pods
    delete_stale()
    remove_old_configs()
"""
        skill_md = "---\nname: x\nversion: '1'\ntier: T0_READONLY\n---\n"
        draft = self._make_draft(tools_py=tools_py, skill_md=skill_md)
        result = self.validator.validate(draft)
        self.assertFalse(result.passed)
        self.assertTrue(any("L4" in e for e in result.errors))

    def test_l5_empty_tools(self):
        draft = self._make_draft(tools_py="", skill_md="---\nname: x\nversion: '1'\n---\n")
        result = self.validator.validate(draft)
        self.assertFalse(result.passed)
        self.assertTrue(any("empty" in e.lower() for e in result.errors))

    def test_validation_result_summary(self):
        r = ValidationResult(passed=True, errors=[], warnings=["w1"])
        self.assertIn("PASS", r.summary)
        r2 = ValidationResult(passed=False, errors=["e1"], warnings=[])
        self.assertIn("FAIL", r2.summary)


# =====================================================================
# Module C: SkillIterationGuard
# =====================================================================

class TestSkillIterationGuard(unittest.TestCase):

    def setUp(self):
        self.guard = SkillIterationGuard()

    def test_first_iteration_allowed(self):
        gap = SkillGap(gap_type="novel_tool_usage", incident_id="inc-1",
                       suggested_skill_domain="helm", uncovered_commands=["helmfile"])
        self.assertTrue(self.guard.should_iterate(gap))

    def test_duplicate_blocked(self):
        gap = SkillGap(gap_type="novel_tool_usage", incident_id="inc-1",
                       suggested_skill_domain="helm", uncovered_commands=["helmfile"])
        self.guard.record_iteration(gap)
        self.assertFalse(self.guard.should_iterate(gap))

    def test_different_gap_allowed(self):
        gap1 = SkillGap(gap_type="novel_tool_usage", incident_id="inc-1",
                        suggested_skill_domain="helm", uncovered_commands=["helmfile"])
        gap2 = SkillGap(gap_type="detection_miss", incident_id="inc-2",
                        suggested_skill_domain="rds")
        self.guard.record_iteration(gap1)
        self.assertTrue(self.guard.should_iterate(gap2))

    def test_per_incident_limit(self):
        gap1 = SkillGap(gap_type="novel_tool_usage", incident_id="inc-1",
                        suggested_skill_domain="helm", uncovered_commands=["helmfile"])
        self.guard.record_iteration(gap1)
        gap2 = SkillGap(gap_type="detection_miss", incident_id="inc-1",
                        suggested_skill_domain="rds")
        self.assertFalse(self.guard.should_iterate(gap2))

    def test_reset(self):
        gap = SkillGap(gap_type="novel_tool_usage", incident_id="inc-1",
                       suggested_skill_domain="helm", uncovered_commands=["helmfile"])
        self.guard.record_iteration(gap)
        self.guard.reset()
        self.assertTrue(self.guard.should_iterate(gap))

    def test_expired_window_allowed(self):
        gap = SkillGap(gap_type="novel_tool_usage", incident_id="inc-1",
                       suggested_skill_domain="helm", uncovered_commands=["helmfile"])
        self.guard.record_iteration(gap)
        # Manually expire
        key = self.guard._make_key(gap)
        self.guard._recent_iterations[key] = datetime.now(timezone.utc) - timedelta(days=8)
        self.guard._incident_counts.clear()
        self.assertTrue(self.guard.should_iterate(gap))


# =====================================================================
# Module D: SOPDocument
# =====================================================================

class TestSOPDocument(unittest.TestCase):

    def test_minimal_creation(self):
        sop = SOPDocument(title="Test SOP", service="eks", alert_type="pod_crash")
        self.assertTrue(sop.sop_id.startswith("sop-"))
        self.assertEqual(sop.status, "draft")
        self.assertEqual(sop.confidence, 0.0)

    def test_s3_key(self):
        sop = SOPDocument(title="t", service="eks", alert_type="pod_crash", sop_id="sop-abc123")
        self.assertEqual(sop.s3_key, "sop/eks/pod_crash/sop-abc123.md")

    def test_lifecycle_draft_to_active(self):
        sop = SOPDocument(title="t", service="eks", alert_type="crash")
        self.assertEqual(sop.status, "draft")
        sop.record_success()
        self.assertEqual(sop.status, "active")
        self.assertEqual(sop.success_count, 1)

    def test_lifecycle_active_to_stable(self):
        sop = SOPDocument(title="t", service="eks", alert_type="crash")
        for _ in range(3):
            sop.record_success()
        self.assertEqual(sop.status, "stable")

    def test_lifecycle_high_confidence(self):
        sop = SOPDocument(title="t", service="eks", alert_type="crash")
        for _ in range(5):
            sop.record_success()
        self.assertEqual(sop.status, "stable")
        self.assertGreater(sop.confidence, 0.9)

    def test_lifecycle_downgrade_on_failures(self):
        sop = SOPDocument(title="t", service="eks", alert_type="crash")
        for _ in range(3):
            sop.record_success()
        self.assertEqual(sop.status, "stable")
        sop.record_failure()
        sop.record_failure()
        self.assertEqual(sop.status, "review_needed")

    def test_success_resets_consecutive_failures(self):
        sop = SOPDocument(title="t", service="eks", alert_type="crash")
        sop.record_success()
        sop.record_failure()
        sop.record_success()
        self.assertEqual(sop.consecutive_failures, 0)

    def test_to_markdown(self):
        sop = SOPDocument(
            title="EKS Pod Crash",
            service="eks",
            alert_type="pod_crash",
            trigger_conditions=["CrashLoopBackOff detected"],
            diagnostic_steps=[SOPStep(order=1, description="Check pod logs", command="kubectl logs pod/x")],
            remediation_plans=[
                RemediationPlan(
                    name="Quick Fix",
                    steps=[SOPStep(order=1, description="Restart pod")],
                    risk_level="low",
                )
            ],
        )
        md = sop.to_markdown()
        self.assertIn("# SOP: EKS Pod Crash", md)
        self.assertIn("CrashLoopBackOff", md)
        self.assertIn("kubectl logs", md)
        self.assertIn("Quick Fix", md)


# =====================================================================
# Module D: SOPDeduplicator
# =====================================================================

class TestSOPDeduplicator(unittest.TestCase):

    def test_no_kb_returns_none(self):
        dedup = SOPDeduplicator(kb_search=None)
        result = _run(dedup.find_similar("root cause", "eks"))
        self.assertIsNone(result)

    def test_low_similarity_returns_none(self):
        mock_result = MagicMock()
        mock_result.score = 0.5
        kb = AsyncMock()
        kb.hybrid_search = AsyncMock(return_value=[mock_result])
        dedup = SOPDeduplicator(kb_search=kb)
        result = _run(dedup.find_similar("root cause", "eks"))
        self.assertIsNone(result)

    def test_high_similarity_returns_match(self):
        mock_result = MagicMock()
        mock_result.score = 0.9
        mock_result.metadata = {"sop_id": "sop-123"}
        mock_result.content = "existing SOP content"
        kb = AsyncMock()
        kb.hybrid_search = AsyncMock(return_value=[mock_result])
        dedup = SOPDeduplicator(kb_search=kb)
        result = _run(dedup.find_similar("root cause", "eks"))
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "update")
        self.assertEqual(result["sop_id"], "sop-123")

    def test_kb_error_returns_none(self):
        kb = AsyncMock()
        kb.hybrid_search = AsyncMock(side_effect=Exception("network error"))
        dedup = SOPDeduplicator(kb_search=kb)
        result = _run(dedup.find_similar("root cause", "eks"))
        self.assertIsNone(result)


# =====================================================================
# Module D: SOPAutoWriter
# =====================================================================

class TestSOPAutoWriter(unittest.TestCase):

    def test_evaluate_trigger_new_pattern(self):
        writer = SOPAutoWriter()
        trigger = writer.evaluate_trigger(None, {"root_cause": "OOM"}, ["restart pod"])
        self.assertEqual(trigger, "new_pattern")

    def test_evaluate_trigger_no_trigger(self):
        writer = SOPAutoWriter()
        existing = {"content": "x\n" * 100}  # many lines
        trigger = writer.evaluate_trigger(existing, {}, ["step1"])
        self.assertIsNone(trigger)

    def test_evaluate_trigger_better_fix(self):
        writer = SOPAutoWriter()
        existing = {"content": "short"}
        trigger = writer.evaluate_trigger(
            existing, {}, ["step1", "step2", "step3", "step4", "step5"]
        )
        self.assertEqual(trigger, "better_fix")

    def test_evaluate_trigger_escalation(self):
        writer = SOPAutoWriter()
        existing = {"content": "x\n" * 10}
        trigger = writer.evaluate_trigger(
            existing, {}, ["escalated to on-call engineer"]
        )
        self.assertEqual(trigger, "escalation_path")

    def test_build_sop_from_rca(self):
        writer = SOPAutoWriter()
        rca = {
            "affected_service": "eks",
            "alert_type": "pod_crash",
            "root_cause": "OOM kill",
            "symptoms": ["High memory usage", "Pod restart"],
        }
        sop = writer.build_sop_from_rca(
            rca, ["kubectl delete pod/x", "kubectl apply -f fix.yaml"], "inc-001"
        )
        self.assertIsInstance(sop, SOPDocument)
        self.assertEqual(sop.service, "eks")
        self.assertEqual(sop.created_from_incident, "inc-001")
        self.assertTrue(len(sop.diagnostic_steps) >= 2)
        self.assertTrue(len(sop.remediation_plans) >= 2)

    def test_evaluate_and_write_no_trigger(self):
        dedup = SOPDeduplicator(kb_search=None)
        writer = SOPAutoWriter(deduplicator=dedup)
        rca = {"root_cause": "test", "confidence": 0.9}
        # No trigger because dedup returns None → new_pattern triggers
        result = _run(writer.evaluate_and_write("inc-1", rca, []))
        self.assertIsNotNone(result)  # new_pattern always triggers when no existing SOP

    def test_evaluate_and_write_produces_sop(self):
        dedup = SOPDeduplicator(kb_search=None)
        writer = SOPAutoWriter(deduplicator=dedup)
        rca = {
            "affected_service": "rds",
            "alert_type": "high_connections",
            "root_cause": "Connection leak",
            "symptoms": ["Too many connections"],
        }
        sop = _run(writer.evaluate_and_write("inc-2", rca, ["kill idle connections"]))
        self.assertIsNotNone(sop)
        self.assertEqual(sop.service, "rds")


if __name__ == "__main__":
    unittest.main()
