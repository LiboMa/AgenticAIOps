"""Coverage tests for sop_system.py — targeting 66% → 85%+."""
import json
import pytest
from unittest.mock import patch, MagicMock
from src.sop_system import (
    SOPStep, SOP, SOPExecution, SOPStore, SOPExecutor,
    StepType, StepStatus, get_sop_store, get_sop_executor,
)


# --------------- Fixtures ---------------
@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singletons before each test."""
    import src.sop_system as mod
    mod._sop_store = None
    mod._sop_executor = None
    yield
    mod._sop_store = None
    mod._sop_executor = None


def _mock_boto3():
    """Patch boto3.client so SOPStore.__init__ doesn't hit real AWS."""
    m = MagicMock()
    m.get_paginator.return_value.paginate.return_value = []
    return patch("boto3.client", return_value=m)


def _make_store():
    with _mock_boto3():
        return SOPStore()


def _sample_yaml():
    return """
id: sop-test-001
name: Test SOP
description: A test SOP for coverage
category: incident
service: ec2
severity: high
trigger:
  type: anomaly
  conditions:
    metric: CPUUtilization
tags: [ec2, restart]
related_runbooks: [rb-001]
related_patterns: [pattern-cpu]
steps:
  - id: step-1
    name: Check status
    description: Check EC2 instance status
    type: auto
    action: describe_instances
    params:
      instance_id: i-12345
    timeout: 60
    retry: 1
    estimated_minutes: 2
    requires_approval: false
  - id: step-2
    name: Restart instance
    description: Restart if needed
    type: approval
    requires_approval: true
"""


# --------------- StepType / StepStatus ---------------
class TestEnums:
    def test_step_types(self):
        assert StepType.MANUAL == "manual"
        assert StepType.AUTO == "auto"
        assert StepType.APPROVAL == "approval"
        assert StepType.CONDITIONAL == "conditional"
        assert StepType.NOTIFICATION == "notification"

    def test_step_statuses(self):
        assert StepStatus.PENDING == "pending"
        assert StepStatus.WAITING_APPROVAL == "waiting_approval"


# --------------- SOPStep ---------------
class TestSOPStep:
    def test_to_dict(self):
        step = SOPStep(
            step_id="s1", name="Test", description="desc",
            step_type=StepType.AUTO, action="run", action_params={"k": "v"},
            timeout_seconds=60, retry_count=2
        )
        d = step.to_dict()
        assert d["step_id"] == "s1"
        assert d["step_type"] == "auto"
        assert d["action_params"] == {"k": "v"}

    def test_conditional_fields(self):
        step = SOPStep(
            step_id="s2", name="Branch", description="cond",
            step_type=StepType.CONDITIONAL, condition="status==ok",
            on_true="step-3", on_false="step-4"
        )
        d = step.to_dict()
        assert d["condition"] == "status==ok"
        assert d["on_true"] == "step-3"


# --------------- SOP ---------------
class TestSOP:
    def test_to_dict(self):
        sop = SOP(
            sop_id="sop-1", name="Test", description="d",
            category="incident", service="ec2", severity="high",
            steps=[SOPStep("s1", "S", "D", StepType.MANUAL)]
        )
        d = sop.to_dict()
        assert d["sop_id"] == "sop-1"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["step_type"] == "manual"

    def test_from_yaml(self):
        sop = SOP.from_yaml(_sample_yaml())
        assert sop.sop_id == "sop-test-001"
        assert sop.service == "ec2"
        assert sop.severity == "high"
        assert sop.trigger_type == "anomaly"
        assert len(sop.steps) == 2
        assert sop.steps[0].step_type == StepType.AUTO
        assert sop.steps[0].action == "describe_instances"
        assert sop.steps[1].step_type == StepType.APPROVAL
        assert sop.tags == ["ec2", "restart"]
        assert sop.related_runbooks == ["rb-001"]

    def test_from_yaml_minimal(self):
        sop = SOP.from_yaml("id: min\nname: Minimal\ndescription: d\n")
        assert sop.sop_id == "min"
        assert sop.category == "incident"
        assert sop.steps == []


# --------------- SOPExecution ---------------
class TestSOPExecution:
    def test_to_dict(self):
        ex = SOPExecution(execution_id="ex-1", sop_id="sop-1", sop_name="Test")
        d = ex.to_dict()
        assert d["execution_id"] == "ex-1"
        assert d["status"] == "pending"
        assert d["success"] is False


# --------------- SOPStore ---------------
class TestSOPStore:
    def test_init_loads_builtins(self):
        store = _make_store()
        assert len(store.sops) > 0  # built-in SOPs loaded

    def test_get_sop_exists(self):
        store = _make_store()
        ids = list(store.sops.keys())
        assert store.get_sop(ids[0]) is not None

    def test_get_sop_missing(self):
        store = _make_store()
        assert store.get_sop("nonexistent") is None

    def test_list_sops_no_filter(self):
        store = _make_store()
        results = store.list_sops()
        assert len(results) == len(store.sops)

    def test_list_sops_by_service(self):
        store = _make_store()
        results = store.list_sops(service="ec2")
        for sop in results:
            assert sop.service == "ec2"

    def test_list_sops_by_category(self):
        store = _make_store()
        results = store.list_sops(category="incident")
        for sop in results:
            assert sop.category == "incident"

    def test_list_sops_by_severity(self):
        store = _make_store()
        results = store.list_sops(severity="critical")
        for sop in results:
            assert sop.severity == "critical"

    def test_list_sops_combined_filter(self):
        store = _make_store()
        results = store.list_sops(service="ec2", category="incident", severity="critical")
        for sop in results:
            assert sop.service == "ec2"

    def test_suggest_sops_by_service(self):
        store = _make_store()
        results = store.suggest_sops(service="ec2", issue_keywords=["cpu"])
        assert isinstance(results, list)
        # Should prefer ec2 SOPs
        if results:
            assert results[0].service == "ec2"

    def test_suggest_sops_keyword_match(self):
        store = _make_store()
        results = store.suggest_sops(service="ec2", issue_keywords=["high", "cpu"])
        assert isinstance(results, list)

    def test_suggest_sops_with_severity(self):
        store = _make_store()
        results = store.suggest_sops(service="ec2", issue_keywords=["cpu"], severity="critical")
        assert isinstance(results, list)

    def test_suggest_sops_no_match(self):
        store = _make_store()
        results = store.suggest_sops(service="nonexistent_svc", issue_keywords=["zzz"])
        assert results == []

    def test_suggest_sops_max_5(self):
        store = _make_store()
        # Add many SOPs
        for i in range(10):
            store.sops[f"sop-extra-{i}"] = SOP(
                sop_id=f"sop-extra-{i}", name=f"Extra cpu SOP {i}",
                description="cpu usage alert", category="incident",
                service="ec2", severity="high", tags=["cpu"]
            )
        results = store.suggest_sops(service="ec2", issue_keywords=["cpu"])
        assert len(results) <= 5

    def test_save_sop_success(self):
        store = _make_store()
        sop = SOP(sop_id="sop-new", name="New", description="d",
                   category="incident", service="ec2", severity="low")
        with _mock_boto3() as m:
            ok = store.save_sop(sop)
            assert ok is True
            assert "sop-new" in store.sops

    def test_save_sop_s3_failure(self):
        store = _make_store()
        sop = SOP(sop_id="sop-fail", name="Fail", description="d",
                   category="incident", service="ec2", severity="low")
        with patch("boto3.client", side_effect=Exception("boom")):
            ok = store.save_sop(sop)
            assert ok is False
            # SOP still in local store even if S3 fails
            assert "sop-fail" in store.sops

    def test_load_from_s3_with_yaml(self):
        """Test S3 loading actually parses YAML files."""
        mock_s3 = MagicMock()
        pages = [{"Contents": [{"Key": "sops/ec2/test.yaml"}]}]
        mock_s3.get_paginator.return_value.paginate.return_value = pages
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: _sample_yaml().encode())
        }
        with patch("boto3.client", return_value=mock_s3):
            store = SOPStore()
        assert "sop-test-001" in store.sops

    def test_load_from_s3_yaml_parse_error(self):
        """S3 file that fails to parse doesn't crash init."""
        mock_s3 = MagicMock()
        pages = [{"Contents": [{"Key": "sops/bad.yaml"}]}]
        mock_s3.get_paginator.return_value.paginate.return_value = pages
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: b"{{bad yaml")
        }
        with patch("boto3.client", return_value=mock_s3):
            store = SOPStore()
        # Should not crash, just log warning

    def test_load_from_s3_connection_error(self):
        """S3 connection failure doesn't crash init."""
        with patch("boto3.client", side_effect=Exception("no S3")):
            store = SOPStore()
        assert store._loaded is True


# --------------- SOPExecutor ---------------
class TestSOPExecutor:
    def test_start_execution(self):
        store = _make_store()
        executor = SOPExecutor(store)
        sop_ids = list(store.sops.keys())
        assert len(sop_ids) > 0

        ex = executor.start_execution(sop_ids[0], triggered_by="alert", context={"alarm": "cpu"})
        assert ex is not None
        assert ex.status == "in_progress"
        assert ex.sop_id == sop_ids[0]
        assert ex.triggered_by == "alert"

    def test_start_execution_unknown_sop(self):
        store = _make_store()
        executor = SOPExecutor(store)
        ex = executor.start_execution("nonexistent")
        assert ex is None

    def test_get_execution(self):
        store = _make_store()
        executor = SOPExecutor(store)
        sop_id = list(store.sops.keys())[0]
        ex = executor.start_execution(sop_id)
        found = executor.get_execution(ex.execution_id)
        assert found is not None
        assert found.execution_id == ex.execution_id

    def test_get_execution_missing(self):
        store = _make_store()
        executor = SOPExecutor(store)
        assert executor.get_execution("nope") is None

    def test_complete_step(self):
        store = _make_store()
        executor = SOPExecutor(store)
        sop_id = list(store.sops.keys())[0]
        ex = executor.start_execution(sop_id)
        ok = executor.complete_step(ex.execution_id, {"result": "ok"})
        assert ok is True
        assert len(ex.step_results) == 1
        assert ex.current_step == 1

    def test_complete_step_missing_execution(self):
        store = _make_store()
        executor = SOPExecutor(store)
        ok = executor.complete_step("nope", {"result": "ok"})
        assert ok is False

    def test_complete_all_steps(self):
        """Complete all steps → execution marked completed."""
        store = _make_store()
        executor = SOPExecutor(store)
        # Find a SOP with steps
        sop = None
        for s in store.sops.values():
            if s.steps:
                sop = s
                break
        if not sop:
            pytest.skip("No SOP with steps found in builtins")

        ex = executor.start_execution(sop.sop_id)
        for i in range(len(sop.steps)):
            executor.complete_step(ex.execution_id, {"step": i, "ok": True})

        assert ex.status == "completed"
        assert ex.success is True
        assert ex.completed_at != ""
        assert sop.execution_count >= 1

    def test_start_execution_default_context(self):
        store = _make_store()
        executor = SOPExecutor(store)
        sop_id = list(store.sops.keys())[0]
        ex = executor.start_execution(sop_id)
        assert ex.trigger_context == {}


# --------------- Singletons ---------------
class TestSingletons:
    def test_get_sop_store(self):
        with _mock_boto3():
            store = get_sop_store()
            store2 = get_sop_store()
            assert store is store2

    def test_get_sop_executor(self):
        with _mock_boto3():
            executor = get_sop_executor()
            executor2 = get_sop_executor()
            assert executor is executor2
