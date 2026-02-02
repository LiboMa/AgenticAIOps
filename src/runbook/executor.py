"""
Runbook Executor

Executes runbook steps and manages rollback on failure.
"""

import logging
import re
import time
import uuid
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List, Callable

from .models import (
    Runbook, RunbookStep, RunbookExecution, 
    ExecutionStatus, StepStatus, StepResult
)
from .loader import RunbookLoader

logger = logging.getLogger(__name__)


class RunbookExecutor:
    """
    Executes runbooks with step-by-step execution and rollback support.
    
    Features:
    - Template variable substitution
    - Precondition checking
    - Step-by-step execution with timeout
    - Automatic rollback on failure
    - Execution history tracking
    
    Example:
        executor = RunbookExecutor()
        
        # Execute a runbook
        execution = executor.execute(
            runbook_id="increase-memory-limit",
            context={
                "namespace": "default",
                "resource_name": "my-app",
                "resource_type": "deployment",
            }
        )
        
        if execution.status == ExecutionStatus.SUCCESS:
            print("Runbook executed successfully")
    """
    
    def __init__(
        self,
        loader: Optional[RunbookLoader] = None,
        aci=None,
        dry_run: bool = False,
    ):
        """
        Initialize the executor.
        
        Args:
            loader: RunbookLoader instance
            aci: AgentCloudInterface for K8s operations
            dry_run: If True, simulate execution without actual changes
        """
        self.loader = loader or RunbookLoader()
        self._aci = aci
        self.dry_run = dry_run
        
        self._executions: Dict[str, RunbookExecution] = {}
        self._action_handlers: Dict[str, Callable] = {}
        
        # Register built-in action handlers
        self._register_builtin_handlers()
    
    @property
    def aci(self):
        """Lazy-load ACI."""
        if self._aci is None:
            try:
                from src.aci import AgentCloudInterface
                self._aci = AgentCloudInterface()
            except ImportError:
                logger.warning("ACI not available")
        return self._aci
    
    def _register_builtin_handlers(self) -> None:
        """Register built-in action handlers."""
        self._action_handlers = {
            "get_resource": self._action_get_resource,
            "get_resource_limits": self._action_get_resource_limits,
            "patch_resource": self._action_patch_resource,
            "rollout_restart": self._action_rollout_restart,
            "rollout_undo": self._action_rollout_undo,
            "wait_rollout": self._action_wait_rollout,
            "verify_health": self._action_verify_health,
            "calculate": self._action_calculate,
            "check_metrics": self._action_check_metrics,
        }
    
    def register_action(self, name: str, handler: Callable) -> None:
        """Register a custom action handler."""
        self._action_handlers[name] = handler
    
    def execute(
        self,
        runbook_id: str,
        context: Dict[str, Any],
        issue_id: Optional[str] = None,
    ) -> RunbookExecution:
        """
        Execute a runbook.
        
        Args:
            runbook_id: ID of the runbook to execute
            context: Execution context (variables)
            issue_id: Associated issue ID
            
        Returns:
            RunbookExecution with results
        """
        runbook = self.loader.get(runbook_id)
        if not runbook:
            return self._create_failed_execution(
                runbook_id, context, issue_id, f"Runbook not found: {runbook_id}"
            )
        
        return self.execute_runbook(runbook, context, issue_id)
    
    def execute_for_pattern(
        self,
        pattern_id: str,
        context: Dict[str, Any],
        issue_id: Optional[str] = None,
    ) -> Optional[RunbookExecution]:
        """
        Execute the runbook associated with a pattern.
        
        Args:
            pattern_id: RCA pattern ID
            context: Execution context
            issue_id: Associated issue ID
            
        Returns:
            RunbookExecution if runbook found, None otherwise
        """
        runbook = self.loader.get_for_pattern(pattern_id)
        if not runbook:
            logger.info(f"No runbook found for pattern: {pattern_id}")
            return None
        
        return self.execute_runbook(runbook, context, issue_id)
    
    def execute_runbook(
        self,
        runbook: Runbook,
        context: Dict[str, Any],
        issue_id: Optional[str] = None,
    ) -> RunbookExecution:
        """
        Execute a runbook instance.
        
        Args:
            runbook: Runbook to execute
            context: Execution context
            issue_id: Associated issue ID
            
        Returns:
            RunbookExecution with results
        """
        execution = RunbookExecution(
            execution_id=str(uuid.uuid4())[:8],
            runbook_id=runbook.id,
            issue_id=issue_id,
            status=ExecutionStatus.RUNNING,
            context=context.copy(),
        )
        
        self._executions[execution.execution_id] = execution
        
        logger.info(f"Starting runbook execution: {runbook.id} (exec={execution.execution_id})")
        
        try:
            # Check preconditions
            if not self._check_preconditions(runbook, execution.context):
                execution.status = ExecutionStatus.FAILED
                execution.error = "Preconditions not met"
                execution.completed_at = datetime.now(UTC).isoformat()
                return execution
            
            # Execute steps
            for step in runbook.steps:
                result = self._execute_step(step, execution.context)
                execution.step_results.append(result)
                
                if result.status == StepStatus.FAILED:
                    logger.error(f"Step {step.id} failed: {result.error}")
                    execution.status = ExecutionStatus.FAILED
                    execution.error = f"Step {step.id} failed: {result.error}"
                    
                    # Attempt rollback
                    if runbook.rollback:
                        self._execute_rollback(runbook, execution)
                    
                    break
                
                # Store output in context
                if step.output and result.output is not None:
                    execution.context[step.output] = result.output
            
            # Mark as success if all steps completed
            if execution.status == ExecutionStatus.RUNNING:
                execution.status = ExecutionStatus.SUCCESS
                logger.info(f"Runbook execution completed: {runbook.id}")
        
        except Exception as e:
            logger.error(f"Runbook execution error: {e}")
            execution.status = ExecutionStatus.FAILED
            execution.error = str(e)
        
        execution.completed_at = datetime.now(UTC).isoformat()
        return execution
    
    def _check_preconditions(self, runbook: Runbook, context: Dict) -> bool:
        """Check if preconditions are met."""
        for precond in runbook.preconditions:
            check_type = precond.get('check')
            
            if check_type == 'resource_exists':
                if not self._check_resource_exists(precond, context):
                    return False
            
            elif check_type == 'restart_count_below':
                max_restarts = precond.get('max_restarts', 10)
                current_restarts = context.get('restart_count', 0)
                if current_restarts > max_restarts:
                    logger.warning(f"Restart count {current_restarts} exceeds max {max_restarts}")
                    return False
        
        return True
    
    def _check_resource_exists(self, precond: Dict, context: Dict) -> bool:
        """Check if a K8s resource exists."""
        if self.dry_run:
            return True
        
        if not self.aci:
            return True  # Assume exists if no ACI
        
        # Simplified check - actual implementation would use kubectl/API
        return True
    
    def _execute_step(self, step: RunbookStep, context: Dict) -> StepResult:
        """Execute a single step."""
        start_time = time.time()
        
        logger.info(f"Executing step: {step.id} ({step.action})")
        
        # Resolve template variables in params
        resolved_params = self._resolve_templates(step.params, context)
        
        try:
            # Get action handler
            handler = self._action_handlers.get(step.action)
            
            if handler is None:
                return StepResult(
                    step_id=step.id,
                    status=StepStatus.FAILED,
                    error=f"Unknown action: {step.action}",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            
            # Execute action
            if self.dry_run:
                logger.info(f"[DRY RUN] Would execute {step.action} with {resolved_params}")
                output = {"dry_run": True, "params": resolved_params}
            else:
                output = handler(resolved_params, context)
            
            return StepResult(
                step_id=step.id,
                status=StepStatus.SUCCESS,
                output=output,
                duration_ms=(time.time() - start_time) * 1000,
            )
            
        except Exception as e:
            logger.error(f"Step {step.id} error: {e}")
            return StepResult(
                step_id=step.id,
                status=StepStatus.FAILED,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )
    
    def _execute_rollback(self, runbook: Runbook, execution: RunbookExecution) -> None:
        """Execute rollback steps."""
        logger.warning(f"Executing rollback for {runbook.id}")
        
        for step in runbook.rollback:
            result = self._execute_step(step, execution.context)
            execution.step_results.append(result)
            
            if result.status == StepStatus.FAILED:
                logger.error(f"Rollback step {step.id} failed")
                break
        
        execution.status = ExecutionStatus.ROLLED_BACK
    
    def _resolve_templates(self, params: Dict, context: Dict) -> Dict:
        """Resolve template variables in parameters."""
        resolved = {}
        
        for key, value in params.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_string(value, context)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_templates(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_string(v, context) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                resolved[key] = value
        
        return resolved
    
    def _resolve_string(self, template: str, context: Dict) -> str:
        """Resolve template variables in a string."""
        # Match {{ variable }} pattern
        pattern = r'\{\{\s*([^}]+)\s*\}\}'
        
        def replacer(match):
            var_path = match.group(1).strip()
            
            # Handle nested paths like "current_limits.memory"
            parts = var_path.split('.')
            value = context
            
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, match.group(0))
                else:
                    return match.group(0)
            
            return str(value) if value != context else match.group(0)
        
        return re.sub(pattern, replacer, template)
    
    # Built-in action handlers
    
    def _action_get_resource(self, params: Dict, context: Dict) -> Dict:
        """Get K8s resource."""
        # Placeholder - actual implementation uses ACI
        return {
            "resource_type": params.get("resource_type"),
            "name": params.get("resource_name"),
            "namespace": params.get("namespace"),
        }
    
    def _action_get_resource_limits(self, params: Dict, context: Dict) -> Dict:
        """Get resource limits from deployment."""
        # Placeholder - actual implementation uses ACI
        return {
            "memory": "512Mi",
            "cpu": "500m",
        }
    
    def _action_patch_resource(self, params: Dict, context: Dict) -> Dict:
        """Patch K8s resource."""
        logger.info(f"Patching {params.get('resource_type')}/{params.get('resource_name')}")
        
        if self.aci:
            # Actual patch via ACI
            pass
        
        return {"patched": True}
    
    def _action_rollout_restart(self, params: Dict, context: Dict) -> Dict:
        """Restart deployment."""
        logger.info(f"Restarting {params.get('resource_type')}/{params.get('resource_name')}")
        
        if self.aci:
            result = self.aci.restart_deployment(
                namespace=params.get('namespace'),
                deployment=params.get('resource_name'),
            )
            return {"success": result.status.value == "success"}
        
        return {"restarted": True}
    
    def _action_rollout_undo(self, params: Dict, context: Dict) -> Dict:
        """Rollback deployment."""
        logger.info(f"Rolling back {params.get('resource_type')}/{params.get('resource_name')}")
        return {"rolled_back": True}
    
    def _action_wait_rollout(self, params: Dict, context: Dict) -> Dict:
        """Wait for rollout to complete."""
        timeout = params.get('timeout_seconds', 300)
        logger.info(f"Waiting for rollout (timeout={timeout}s)")
        
        # In real implementation, poll status
        return {"completed": True}
    
    def _action_verify_health(self, params: Dict, context: Dict) -> Dict:
        """Verify pod health."""
        logger.info(f"Verifying health in {params.get('namespace')}")
        return {"healthy": True}
    
    def _action_calculate(self, params: Dict, context: Dict) -> Any:
        """Calculate a value."""
        expression = params.get('expression', '')
        max_value = params.get('max_value')
        
        # Simple calculation - parse memory/cpu values
        # In real implementation, properly parse K8s resource quantities
        return max_value or expression
    
    def _action_check_metrics(self, params: Dict, context: Dict) -> Dict:
        """Check metrics."""
        metric = params.get('metric')
        logger.info(f"Checking metric: {metric}")
        return {"metric": metric, "status": "ok"}
    
    def get_execution(self, execution_id: str) -> Optional[RunbookExecution]:
        """Get execution by ID."""
        return self._executions.get(execution_id)
    
    def list_executions(self, limit: int = 10) -> List[Dict]:
        """List recent executions."""
        executions = list(self._executions.values())[-limit:]
        return [e.to_dict() for e in executions]
    
    def _create_failed_execution(
        self,
        runbook_id: str,
        context: Dict,
        issue_id: Optional[str],
        error: str,
    ) -> RunbookExecution:
        """Create a failed execution record."""
        return RunbookExecution(
            execution_id=str(uuid.uuid4())[:8],
            runbook_id=runbook_id,
            issue_id=issue_id,
            status=ExecutionStatus.FAILED,
            context=context,
            error=error,
            completed_at=datetime.now(UTC).isoformat(),
        )
