"""Tests for Runbook Executor - improve coverage from 44%."""

import pytest
from unittest.mock import patch, MagicMock
from src.runbook.executor import RunbookExecutor
from src.runbook.models import (
    Runbook, RunbookStep, RunbookExecution,
    ExecutionStatus, StepStatus, StepResult
)


@pytest.fixture
def executor():
    return RunbookExecutor(dry_run=True)


class TestResolveString:
    def test_resolve_simple(self, executor):
        result = executor._resolve_string("restart {{ service }}", {"service": "nginx"})
        assert result == "restart nginx"

    def test_resolve_nested(self, executor):
        result = executor._resolve_string("mem={{ limits.memory }}", {"limits": {"memory": "512Mi"}})
        assert result == "mem=512Mi"

    def test_resolve_missing(self, executor):
        result = executor._resolve_string("{{ missing }}", {})
        assert "missing" in result

    def test_resolve_no_template(self, executor):
        result = executor._resolve_string("plain text", {})
        assert result == "plain text"


class TestResolveTemplates:
    def test_resolve_dict(self, executor):
        params = {"name": "{{ svc }}", "count": 3}
        result = executor._resolve_templates(params, {"svc": "web"})
        assert result["name"] == "web"
        assert result["count"] == 3


class TestExecuteStep:
    def test_execute_step_dry_run(self, executor):
        step = RunbookStep(id="s1", action="get_resource", params={"kind": "pod"})
        result = executor._execute_step(step, {})
        assert result.status == StepStatus.SUCCESS
        assert result.output["dry_run"] is True

    def test_execute_step_unknown_action(self, executor):
        step = RunbookStep(id="s1", action="nonexistent_action", params={})
        result = executor._execute_step(step, {})
        assert result.status == StepStatus.FAILED
        assert "Unknown action" in result.error

    def test_execute_step_handler_error(self):
        executor = RunbookExecutor(dry_run=False)
        executor._action_handlers["boom"] = MagicMock(side_effect=RuntimeError("fail"))
        step = RunbookStep(id="s1", action="boom", params={})
        result = executor._execute_step(step, {})
        assert result.status == StepStatus.FAILED


class TestExecuteRunbook:
    def test_execute_not_found(self, executor):
        executor.loader = MagicMock()
        executor.loader.get.return_value = None
        result = executor.execute("rb-missing", {})
        assert result.status == ExecutionStatus.FAILED

    def test_execute_for_pattern_not_found(self, executor):
        executor.loader = MagicMock()
        executor.loader.get_for_pattern.return_value = None
        result = executor.execute_for_pattern("pat-missing", {})
        assert result is None

    def test_execute_runbook_dry_run(self, executor):
        runbook = Runbook(
            id="rb-1", name="test", description="t",
            steps=[RunbookStep(id="s1", action="get_resource", params={"kind": "pod"})],
        )
        result = executor.execute_runbook(runbook, {})
        assert result.status == ExecutionStatus.SUCCESS


class TestExecuteRollback:
    def test_rollback_executes(self, executor):
        runbook = Runbook(
            id="rb-1", name="test", description="t",
            steps=[], rollback=[RunbookStep(id="r1", action="get_resource", params={})]
        )
        execution = RunbookExecution(
            execution_id="ex-1", runbook_id="rb-1", status=ExecutionStatus.FAILED, context={}
        )
        executor._execute_rollback(runbook, execution)
        assert execution.status == ExecutionStatus.ROLLED_BACK
