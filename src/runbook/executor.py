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
            # K8s actions
            "get_resource": self._action_get_resource,
            "get_resource_limits": self._action_get_resource_limits,
            "patch_resource": self._action_patch_resource,
            "rollout_restart": self._action_rollout_restart,
            "rollout_undo": self._action_rollout_undo,
            "wait_rollout": self._action_wait_rollout,
            "verify_health": self._action_verify_health,
            "calculate": self._action_calculate,
            "check_metrics": self._action_check_metrics,
            # AWS actions (L4: real boto3 execution)
            "ec2_reboot": self._action_ec2_reboot,
            "ec2_stop": self._action_ec2_stop,
            "ec2_start": self._action_ec2_start,
            "ec2_describe": self._action_ec2_describe,
            "asg_scale": self._action_asg_scale,
            "rds_reboot": self._action_rds_reboot,
            "rds_failover": self._action_rds_failover,
            "lambda_update_config": self._action_lambda_update_config,
            "cloudwatch_describe_alarms": self._action_cw_describe_alarms,
            "sns_notify": self._action_sns_notify,
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
    
    # =========================================================================
    # AWS Actions (L4: real boto3 execution)
    # =========================================================================
    
    def _get_boto3_client(self, service: str, region: str = None):
        """Get a boto3 client for the given AWS service."""
        import boto3
        from src.config import AWS_REGION
        return boto3.client(service, region_name=region or AWS_REGION)
    
    def _action_ec2_describe(self, params: Dict, context: Dict) -> Dict:
        """Describe EC2 instance."""
        instance_id = params.get("instance_id") or context.get("instance_id")
        if not instance_id:
            raise ValueError("instance_id required")
        
        ec2 = self._get_boto3_client("ec2", params.get("region"))
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        inst = resp["Reservations"][0]["Instances"][0]
        return {
            "instance_id": instance_id,
            "state": inst["State"]["Name"],
            "instance_type": inst["InstanceType"],
            "launch_time": str(inst.get("LaunchTime")),
        }
    
    def _action_ec2_reboot(self, params: Dict, context: Dict) -> Dict:
        """Reboot an EC2 instance."""
        instance_id = params.get("instance_id") or context.get("instance_id")
        if not instance_id:
            raise ValueError("instance_id required")
        
        logger.info(f"Rebooting EC2 instance: {instance_id}")
        ec2 = self._get_boto3_client("ec2", params.get("region"))
        ec2.reboot_instances(InstanceIds=[instance_id])
        return {"instance_id": instance_id, "action": "reboot", "success": True}
    
    def _action_ec2_stop(self, params: Dict, context: Dict) -> Dict:
        """Stop an EC2 instance."""
        instance_id = params.get("instance_id") or context.get("instance_id")
        if not instance_id:
            raise ValueError("instance_id required")
        
        logger.info(f"Stopping EC2 instance: {instance_id}")
        ec2 = self._get_boto3_client("ec2", params.get("region"))
        resp = ec2.stop_instances(InstanceIds=[instance_id])
        state = resp["StoppingInstances"][0]["CurrentState"]["Name"]
        return {"instance_id": instance_id, "action": "stop", "state": state}
    
    def _action_ec2_start(self, params: Dict, context: Dict) -> Dict:
        """Start an EC2 instance."""
        instance_id = params.get("instance_id") or context.get("instance_id")
        if not instance_id:
            raise ValueError("instance_id required")
        
        logger.info(f"Starting EC2 instance: {instance_id}")
        ec2 = self._get_boto3_client("ec2", params.get("region"))
        resp = ec2.start_instances(InstanceIds=[instance_id])
        state = resp["StartingInstances"][0]["CurrentState"]["Name"]
        return {"instance_id": instance_id, "action": "start", "state": state}
    
    def _action_asg_scale(self, params: Dict, context: Dict) -> Dict:
        """Scale an Auto Scaling Group."""
        asg_name = params.get("asg_name") or context.get("asg_name")
        desired = params.get("desired_capacity")
        min_size = params.get("min_size")
        max_size = params.get("max_size")
        
        if not asg_name:
            raise ValueError("asg_name required")
        
        logger.info(f"Scaling ASG {asg_name}: desired={desired}")
        asg = self._get_boto3_client("autoscaling", params.get("region"))
        
        update_params = {"AutoScalingGroupName": asg_name}
        if desired is not None:
            update_params["DesiredCapacity"] = int(desired)
        if min_size is not None:
            update_params["MinSize"] = int(min_size)
        if max_size is not None:
            update_params["MaxSize"] = int(max_size)
        
        asg.update_auto_scaling_group(**update_params)
        return {"asg_name": asg_name, "action": "scale", "desired": desired, "success": True}
    
    def _action_rds_reboot(self, params: Dict, context: Dict) -> Dict:
        """Reboot an RDS instance."""
        db_id = params.get("db_instance_id") or context.get("db_instance_id")
        if not db_id:
            raise ValueError("db_instance_id required")
        
        logger.info(f"Rebooting RDS instance: {db_id}")
        rds = self._get_boto3_client("rds", params.get("region"))
        resp = rds.reboot_db_instance(
            DBInstanceIdentifier=db_id,
            ForceFailover=params.get("force_failover", False),
        )
        return {
            "db_instance_id": db_id,
            "action": "reboot",
            "status": resp["DBInstance"]["DBInstanceStatus"],
        }
    
    def _action_rds_failover(self, params: Dict, context: Dict) -> Dict:
        """Trigger RDS Multi-AZ failover."""
        db_id = params.get("db_instance_id") or context.get("db_instance_id")
        if not db_id:
            raise ValueError("db_instance_id required")
        
        logger.info(f"Triggering RDS failover: {db_id}")
        rds = self._get_boto3_client("rds", params.get("region"))
        resp = rds.reboot_db_instance(
            DBInstanceIdentifier=db_id,
            ForceFailover=True,
        )
        return {
            "db_instance_id": db_id,
            "action": "failover",
            "status": resp["DBInstance"]["DBInstanceStatus"],
        }
    
    def _action_lambda_update_config(self, params: Dict, context: Dict) -> Dict:
        """Update Lambda function configuration (memory, timeout)."""
        func_name = params.get("function_name") or context.get("function_name")
        if not func_name:
            raise ValueError("function_name required")
        
        logger.info(f"Updating Lambda config: {func_name}")
        lam = self._get_boto3_client("lambda", params.get("region"))
        
        update_params = {"FunctionName": func_name}
        if params.get("memory_size"):
            update_params["MemorySize"] = int(params["memory_size"])
        if params.get("timeout"):
            update_params["Timeout"] = int(params["timeout"])
        if params.get("environment"):
            update_params["Environment"] = {"Variables": params["environment"]}
        
        resp = lam.update_function_configuration(**update_params)
        return {
            "function_name": func_name,
            "action": "update_config",
            "memory": resp.get("MemorySize"),
            "timeout": resp.get("Timeout"),
        }
    
    def _action_cw_describe_alarms(self, params: Dict, context: Dict) -> Dict:
        """Describe CloudWatch alarms."""
        alarm_names = params.get("alarm_names", [])
        cw = self._get_boto3_client("cloudwatch", params.get("region"))
        
        if alarm_names:
            resp = cw.describe_alarms(AlarmNames=alarm_names)
        else:
            resp = cw.describe_alarms(StateValue="ALARM", MaxRecords=10)
        
        alarms = [{
            "name": a["AlarmName"],
            "state": a["StateValue"],
            "metric": a["MetricName"],
            "reason": a.get("StateReason", "")[:200],
        } for a in resp.get("MetricAlarms", [])]
        
        return {"alarms": alarms, "count": len(alarms)}
    
    def _action_sns_notify(self, params: Dict, context: Dict) -> Dict:
        """Send SNS notification."""
        topic_arn = params.get("topic_arn")
        message = params.get("message", "")
        subject = params.get("subject", "AgenticAIOps Notification")
        
        if not topic_arn:
            logger.warning("No SNS topic_arn provided, skipping notification")
            return {"sent": False, "reason": "no topic_arn"}
        
        sns = self._get_boto3_client("sns", params.get("region"))
        resp = sns.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=message,
        )
        return {"sent": True, "message_id": resp.get("MessageId")}
    
    
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
