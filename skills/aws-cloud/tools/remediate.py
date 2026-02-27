"""AWS Cloud remediation tools for Strands Agent.

Write-tier and dangerous-tier tools for AWS resource management.
Dangerous operations require approval_token.

Each function is decorated with @tool for automatic registration
via SkillLoader.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Optional

from strands import tool

logger = logging.getLogger(__name__)


def _aws(service: str, command: str, args: list[str],
         region: Optional[str] = None, timeout: int = 30) -> str:
    """Execute an AWS CLI command and return stdout or error string."""
    cmd = ["aws", service, command] + args
    if region:
        cmd.extend(["--region", region])
    cmd.extend(["--output", "json"])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# EC2 Write-tier
# ---------------------------------------------------------------------------

@tool
def start_instances(instance_ids: str, region: Optional[str] = None) -> str:
    """Start stopped EC2 instances.

    Args:
        instance_ids: Comma-separated instance IDs
        region: AWS region

    Returns:
        Start operation result.
    """
    args = ["--instance-ids"] + instance_ids.split(",")
    logger.info(f"Starting instances: {instance_ids}")
    return _aws("ec2", "start-instances", args, region)


@tool
def stop_instances(instance_ids: str, region: Optional[str] = None) -> str:
    """Stop running EC2 instances.

    Args:
        instance_ids: Comma-separated instance IDs
        region: AWS region

    Returns:
        Stop operation result.
    """
    args = ["--instance-ids"] + instance_ids.split(",")
    logger.info(f"Stopping instances: {instance_ids}")
    return _aws("ec2", "stop-instances", args, region)


@tool
def reboot_instances(instance_ids: str, region: Optional[str] = None) -> str:
    """Reboot EC2 instances.

    Args:
        instance_ids: Comma-separated instance IDs
        region: AWS region

    Returns:
        Reboot operation result (empty on success).
    """
    args = ["--instance-ids"] + instance_ids.split(",")
    logger.info(f"Rebooting instances: {instance_ids}")
    result = _aws("ec2", "reboot-instances", args, region)
    return result or "OK: Reboot initiated"


# ---------------------------------------------------------------------------
# ASG Write-tier
# ---------------------------------------------------------------------------

@tool
def update_asg_capacity(asg_name: str, desired: int,
                        min_size: Optional[int] = None,
                        max_size: Optional[int] = None,
                        region: Optional[str] = None) -> str:
    """Update Auto Scaling Group desired capacity.

    Args:
        asg_name: ASG name
        desired: Desired capacity
        min_size: Optional new minimum size
        max_size: Optional new maximum size
        region: AWS region

    Returns:
        Update result.
    """
    args = ["--auto-scaling-group-name", asg_name,
            "--desired-capacity", str(desired)]
    if min_size is not None:
        args.extend(["--min-size", str(min_size)])
    if max_size is not None:
        args.extend(["--max-size", str(max_size)])
    logger.info(f"Updating ASG {asg_name}: desired={desired}")
    result = _aws("autoscaling", "update-auto-scaling-group", args, region)
    return result or f"OK: ASG {asg_name} updated to desired={desired}"


# ---------------------------------------------------------------------------
# ECS Write-tier
# ---------------------------------------------------------------------------

@tool
def update_ecs_service(cluster: str, service: str,
                       desired_count: Optional[int] = None,
                       force_new_deployment: bool = False,
                       region: Optional[str] = None) -> str:
    """Update ECS service desired count or force new deployment.

    Args:
        cluster: ECS cluster name
        service: ECS service name
        desired_count: New desired task count
        force_new_deployment: Force a new deployment (rolling restart)
        region: AWS region

    Returns:
        Updated service info.
    """
    args = ["--cluster", cluster, "--service", service]
    if desired_count is not None:
        args.extend(["--desired-count", str(desired_count)])
    if force_new_deployment:
        args.append("--force-new-deployment")
    logger.info(f"Updating ECS service {service} in {cluster}")
    return _aws("ecs", "update-service", args, region)


# ---------------------------------------------------------------------------
# Lambda Write-tier
# ---------------------------------------------------------------------------

@tool
def invoke_function(function_name: str,
                    payload: Optional[str] = None,
                    region: Optional[str] = None) -> str:
    """Invoke a Lambda function.

    Args:
        function_name: Lambda function name or ARN
        payload: JSON payload string (optional)
        region: AWS region

    Returns:
        Function response.
    """
    args = ["--function-name", function_name, "/dev/stdout"]
    if payload:
        args = ["--function-name", function_name, "--payload", payload, "/dev/stdout"]
    logger.info(f"Invoking Lambda: {function_name}")
    return _aws("lambda", "invoke", args, region)


# ---------------------------------------------------------------------------
# CloudWatch Write-tier
# ---------------------------------------------------------------------------

@tool
def put_metric_alarm(alarm_name: str, namespace: str,
                     metric_name: str, threshold: float,
                     comparison: str, period: int = 300,
                     evaluation_periods: int = 2,
                     statistic: str = "Average",
                     dimension_name: Optional[str] = None,
                     dimension_value: Optional[str] = None,
                     region: Optional[str] = None) -> str:
    """Create or update a CloudWatch alarm.

    Args:
        alarm_name: Alarm name
        namespace: CloudWatch namespace (e.g. AWS/EC2)
        metric_name: Metric name (e.g. CPUUtilization)
        threshold: Alarm threshold value
        comparison: GreaterThanThreshold, LessThanThreshold, etc.
        period: Period in seconds
        evaluation_periods: Number of periods to evaluate
        statistic: Average, Sum, Maximum, Minimum
        dimension_name: Dimension name (optional)
        dimension_value: Dimension value (optional)
        region: AWS region

    Returns:
        Alarm creation result.
    """
    args = [
        "--alarm-name", alarm_name,
        "--namespace", namespace,
        "--metric-name", metric_name,
        "--threshold", str(threshold),
        "--comparison-operator", comparison,
        "--period", str(period),
        "--evaluation-periods", str(evaluation_periods),
        "--statistic", statistic,
    ]
    if dimension_name and dimension_value:
        args.extend(["--dimensions",
                      f"Name={dimension_name},Value={dimension_value}"])
    logger.info(f"Creating alarm: {alarm_name}")
    result = _aws("cloudwatch", "put-metric-alarm", args, region)
    return result or f"OK: Alarm {alarm_name} created/updated"


# ---------------------------------------------------------------------------
# EBS Write-tier
# ---------------------------------------------------------------------------

@tool
def create_snapshot(volume_id: str, description: Optional[str] = None,
                    region: Optional[str] = None) -> str:
    """Create an EBS volume snapshot (backup before changes).

    Args:
        volume_id: EBS volume ID
        description: Snapshot description
        region: AWS region

    Returns:
        Snapshot ID and details.
    """
    args = ["--volume-id", volume_id]
    if description:
        args.extend(["--description", description])
    else:
        import datetime
        args.extend(["--description",
                      f"Auto-snapshot {datetime.datetime.utcnow().strftime('%Y%m%d-%H%M')}"])
    logger.info(f"Creating snapshot for volume: {volume_id}")
    return _aws("ec2", "create-snapshot", args, region)


# ---------------------------------------------------------------------------
# Tagging Write-tier
# ---------------------------------------------------------------------------

@tool
def tag_resource(resource_id: str, tags: str,
                 region: Optional[str] = None) -> str:
    """Add tags to an AWS resource.

    Args:
        resource_id: Resource ID (instance, volume, etc.)
        tags: Tags as Key=Value pairs, comma-separated (e.g. 'Env=prod,Team=ops')
        region: AWS region

    Returns:
        Tagging result.
    """
    tag_specs = []
    for pair in tags.split(","):
        k, v = pair.strip().split("=", 1)
        tag_specs.append(f"Key={k.strip()},Value={v.strip()}")
    args = ["--resources", resource_id, "--tags"] + tag_specs
    logger.info(f"Tagging {resource_id}: {tags}")
    result = _aws("ec2", "create-tags", args, region)
    return result or f"OK: Tagged {resource_id}"


# ---------------------------------------------------------------------------
# Dangerous-tier (require approval_token)
# ---------------------------------------------------------------------------

@tool
def terminate_instances(instance_ids: str,
                        approval_token: str,
                        region: Optional[str] = None) -> str:
    """DANGEROUS: Terminate EC2 instances permanently.

    Args:
        instance_ids: Comma-separated instance IDs
        approval_token: Required approval token for dangerous operations
        region: AWS region

    Returns:
        Termination result.
    """
    if not approval_token:
        return "ERROR: approval_token required for dangerous operation"
    args = ["--instance-ids"] + instance_ids.split(",")
    logger.warning(f"DANGEROUS: Terminating instances: {instance_ids} "
                   f"(token={approval_token[:8]}...)")
    return _aws("ec2", "terminate-instances", args, region)


@tool
def delete_stack(stack_name: str,
                 approval_token: str,
                 region: Optional[str] = None) -> str:
    """DANGEROUS: Delete a CloudFormation stack and all its resources.

    Args:
        stack_name: Stack name
        approval_token: Required approval token
        region: AWS region

    Returns:
        Deletion result.
    """
    if not approval_token:
        return "ERROR: approval_token required for dangerous operation"
    args = ["--stack-name", stack_name]
    logger.warning(f"DANGEROUS: Deleting stack: {stack_name} "
                   f"(token={approval_token[:8]}...)")
    result = _aws("cloudformation", "delete-stack", args, region)
    return result or f"OK: Stack {stack_name} deletion initiated"


@tool
def delete_snapshot(snapshot_id: str,
                    approval_token: str,
                    region: Optional[str] = None) -> str:
    """DANGEROUS: Delete an EBS snapshot permanently.

    Args:
        snapshot_id: Snapshot ID
        approval_token: Required approval token
        region: AWS region

    Returns:
        Deletion result.
    """
    if not approval_token:
        return "ERROR: approval_token required for dangerous operation"
    args = ["--snapshot-id", snapshot_id]
    logger.warning(f"DANGEROUS: Deleting snapshot: {snapshot_id}")
    result = _aws("ec2", "delete-snapshot", args, region)
    return result or f"OK: Snapshot {snapshot_id} deleted"


@tool
def force_delete_asg(asg_name: str,
                     approval_token: str,
                     region: Optional[str] = None) -> str:
    """DANGEROUS: Force delete ASG and terminate all instances.

    Args:
        asg_name: Auto Scaling Group name
        approval_token: Required approval token
        region: AWS region

    Returns:
        Deletion result.
    """
    if not approval_token:
        return "ERROR: approval_token required for dangerous operation"
    args = ["--auto-scaling-group-name", asg_name, "--force-delete"]
    logger.warning(f"DANGEROUS: Force deleting ASG: {asg_name}")
    result = _aws("autoscaling", "delete-auto-scaling-group", args, region)
    return result or f"OK: ASG {asg_name} force deleted"
