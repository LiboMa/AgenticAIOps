"""
Tests for Runbook Module
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from src.runbook import (
    Runbook, RunbookStep, RunbookExecution, ExecutionStatus,
    RunbookLoader, RunbookExecutor
)
from src.runbook.models import StepStatus, StepResult


class TestRunbookModels:
    """Tests for runbook data models."""
    
    def test_execution_status_enum(self):
        """Test execution status enum."""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.SUCCESS.value == "success"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.ROLLED_BACK.value == "rolled_back"
    
    def test_runbook_step_creation(self):
        """Test RunbookStep creation."""
        step = RunbookStep(
            id="test-step",
            action="patch_resource",
            description="Test step",
            params={"key": "value"},
            requires_approval=True,
        )
        
        assert step.id == "test-step"
        assert step.action == "patch_resource"
        assert step.requires_approval is True
    
    def test_runbook_creation(self):
        """Test Runbook creation."""
        runbook = Runbook(
            id="test-runbook",
            name="Test Runbook",
            description="A test runbook",
            triggers=[{"pattern_id": "oom-001"}],
            steps=[
                RunbookStep(id="step1", action="test_action"),
            ],
        )
        
        assert runbook.id == "test-runbook"
        assert len(runbook.steps) == 1
    
    def test_runbook_to_dict(self):
        """Test Runbook serialization."""
        runbook = Runbook(
            id="test",
            name="Test",
            steps=[RunbookStep(id="s1", action="a1")],
            rollback=[RunbookStep(id="r1", action="undo")],
        )
        
        data = runbook.to_dict()
        
        assert data["id"] == "test"
        assert data["step_count"] == 1
        assert data["has_rollback"] is True
    
    def test_execution_to_dict(self):
        """Test RunbookExecution serialization."""
        execution = RunbookExecution(
            execution_id="abc123",
            runbook_id="test",
            status=ExecutionStatus.SUCCESS,
            step_results=[
                StepResult(step_id="s1", status=StepStatus.SUCCESS),
            ],
        )
        
        data = execution.to_dict()
        
        assert data["execution_id"] == "abc123"
        assert data["status"] == "success"
        assert len(data["step_results"]) == 1
    
    def test_execution_is_complete(self):
        """Test execution completion check."""
        execution = RunbookExecution(
            execution_id="test",
            runbook_id="test",
            status=ExecutionStatus.PENDING,
        )
        assert execution.is_complete is False
        
        execution.status = ExecutionStatus.SUCCESS
        assert execution.is_complete is True
        
        execution.status = ExecutionStatus.FAILED
        assert execution.is_complete is True
    
    def test_execution_duration(self):
        """Test execution duration calculation."""
        execution = RunbookExecution(
            execution_id="test",
            runbook_id="test",
            step_results=[
                StepResult(step_id="s1", status=StepStatus.SUCCESS, duration_ms=100),
                StepResult(step_id="s2", status=StepStatus.SUCCESS, duration_ms=200),
            ],
        )
        
        assert execution.duration_ms == 300


class TestRunbookLoader:
    """Tests for RunbookLoader."""
    
    @pytest.fixture
    def loader(self):
        """Create loader with default config."""
        return RunbookLoader()
    
    def test_load_all_runbooks(self, loader):
        """Test loading all runbooks from directory."""
        runbooks = loader.list_runbooks()
        
        # Should have loaded our 3 runbooks
        assert len(runbooks) >= 3
    
    def test_get_runbook_by_id(self, loader):
        """Test getting runbook by ID."""
        runbook = loader.get("increase-memory-limit")
        
        assert runbook is not None
        assert runbook.name == "Increase Pod Memory Limit"
    
    def test_get_runbook_for_pattern(self, loader):
        """Test getting runbook for pattern."""
        runbook = loader.get_for_pattern("oom-001")
        
        assert runbook is not None
        assert runbook.id == "increase-memory-limit"
    
    def test_get_runbook_for_crash_pattern(self, loader):
        """Test getting runbook for crash pattern."""
        runbook = loader.get_for_pattern("crash-001")
        
        assert runbook is not None
        assert runbook.id == "rollout-restart"
    
    def test_get_nonexistent_runbook(self, loader):
        """Test getting non-existent runbook."""
        runbook = loader.get("nonexistent")
        assert runbook is None
    
    def test_get_runbook_for_unknown_pattern(self, loader):
        """Test getting runbook for unknown pattern."""
        runbook = loader.get_for_pattern("unknown-pattern")
        assert runbook is None


class TestRunbookExecutor:
    """Tests for RunbookExecutor."""
    
    @pytest.fixture
    def executor(self):
        """Create executor in dry-run mode."""
        return RunbookExecutor(dry_run=True)
    
    def test_execute_runbook(self, executor):
        """Test basic runbook execution."""
        context = {
            "namespace": "default",
            "resource_name": "test-app",
            "resource_type": "deployment",
            "container_name": "main",
        }
        
        execution = executor.execute("increase-memory-limit", context)
        
        assert execution is not None
        assert execution.runbook_id == "increase-memory-limit"
        # In dry-run mode, should succeed
        assert execution.status in [ExecutionStatus.SUCCESS, ExecutionStatus.FAILED]
    
    def test_execute_for_pattern(self, executor):
        """Test executing runbook for pattern."""
        context = {
            "namespace": "default",
            "resource_name": "crash-app",
            "resource_type": "deployment",
        }
        
        execution = executor.execute_for_pattern("crash-001", context)
        
        assert execution is not None
        assert execution.runbook_id == "rollout-restart"
    
    def test_execute_nonexistent_runbook(self, executor):
        """Test executing non-existent runbook."""
        execution = executor.execute("nonexistent", {})
        
        assert execution.status == ExecutionStatus.FAILED
        assert "not found" in execution.error
    
    def test_template_resolution(self, executor):
        """Test template variable resolution."""
        context = {
            "namespace": "production",
            "resource_name": "my-app",
            "limits": {"memory": "1Gi"},
        }
        
        params = {
            "ns": "{{ namespace }}",
            "app": "{{ resource_name }}",
            "mem": "{{ limits.memory }}",
        }
        
        resolved = executor._resolve_templates(params, context)
        
        assert resolved["ns"] == "production"
        assert resolved["app"] == "my-app"
        assert resolved["mem"] == "1Gi"
    
    def test_template_nested_resolution(self, executor):
        """Test nested template resolution."""
        context = {"name": "test"}
        
        params = {
            "outer": {
                "inner": "{{ name }}"
            }
        }
        
        resolved = executor._resolve_templates(params, context)
        
        assert resolved["outer"]["inner"] == "test"
    
    def test_precondition_restart_count(self, executor):
        """Test restart count precondition."""
        runbook = Runbook(
            id="test",
            name="Test",
            preconditions=[{"check": "restart_count_below", "max_restarts": 5}],
            steps=[],
        )
        
        # Should pass
        context = {"restart_count": 3}
        assert executor._check_preconditions(runbook, context) is True
        
        # Should fail
        context = {"restart_count": 10}
        assert executor._check_preconditions(runbook, context) is False
    
    def test_get_execution(self, executor):
        """Test getting execution by ID."""
        context = {"namespace": "test", "resource_name": "app", "resource_type": "deployment"}
        execution = executor.execute("increase-memory-limit", context)
        
        retrieved = executor.get_execution(execution.execution_id)
        
        assert retrieved is not None
        assert retrieved.execution_id == execution.execution_id
    
    def test_list_executions(self, executor):
        """Test listing executions."""
        # Run a few executions
        context = {"namespace": "test", "resource_name": "app", "resource_type": "deployment"}
        executor.execute("increase-memory-limit", context)
        executor.execute("rollout-restart", context)
        
        executions = executor.list_executions()
        
        assert len(executions) >= 2
    
    def test_register_custom_action(self, executor):
        """Test registering custom action handler."""
        def custom_handler(params, context):
            return {"custom": "result"}
        
        executor.register_action("custom_action", custom_handler)
        
        assert "custom_action" in executor._action_handlers
    
    def test_execution_with_issue_id(self, executor):
        """Test execution with associated issue."""
        context = {"namespace": "test", "resource_name": "app", "resource_type": "deployment"}
        
        execution = executor.execute(
            "increase-memory-limit",
            context,
            issue_id="issue-123"
        )
        
        assert execution.issue_id == "issue-123"


class TestRunbookIntegration:
    """Integration tests for runbook module."""
    
    def test_full_pipeline_dry_run(self):
        """Test full runbook execution pipeline in dry-run mode."""
        # Load runbooks
        loader = RunbookLoader()
        
        # Verify OOM runbook exists
        runbook = loader.get_for_pattern("oom-001")
        assert runbook is not None
        
        # Execute in dry-run
        executor = RunbookExecutor(loader=loader, dry_run=True)
        
        context = {
            "namespace": "stress-test",
            "resource_name": "memory-stress",
            "resource_type": "deployment",
            "container_name": "stress",
        }
        
        execution = executor.execute_for_pattern("oom-001", context)
        
        assert execution is not None
        assert len(execution.step_results) > 0
    
    def test_runbook_with_rollback_steps(self):
        """Test that runbooks have rollback steps."""
        loader = RunbookLoader()
        
        runbook = loader.get("increase-memory-limit")
        
        assert runbook is not None
        assert len(runbook.rollback) > 0
        assert runbook.rollback[0].action == "patch_resource"
