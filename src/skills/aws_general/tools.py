"""AWS General Skill — 16 tools (boto3-based AWS operations)."""
from __future__ import annotations
import json
from .._security import secure_tool
from .._models import SecurityTier, ToolResult

def _boto_call(service: str, method: str, **kwargs):
    """Wrapper for boto3 calls with error handling."""
    try:
        import boto3
        client = boto3.client(service)
        result = getattr(client, method)(**kwargs)
        # Remove ResponseMetadata for cleaner output
        result.pop("ResponseMetadata", None)
        return result
    except Exception as e:
        return {"error": str(e)}

# ─── T0: Read-Only ─────────────────────────────────────────────

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def ec2_describe_instances(filters: str = "") -> str:
    """Describe EC2 instances, optionally filtered."""
    kwargs = {}
    if filters:
        kwargs["Filters"] = [{"Name": "tag:Name", "Values": [f"*{filters}*"]}]
    r = _boto_call("ec2", "describe_instances", **kwargs)
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def ec2_instance_status(instance_ids: str = "") -> str:
    """Get EC2 instance status checks."""
    kwargs = {}
    if instance_ids:
        kwargs["InstanceIds"] = [i.strip() for i in instance_ids.split(",")]
    r = _boto_call("ec2", "describe_instance_status", **kwargs)
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def rds_describe_instances() -> str:
    """Describe all RDS instances."""
    r = _boto_call("rds", "describe_db_instances")
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def lambda_list_functions() -> str:
    """List Lambda functions."""
    r = _boto_call("lambda", "list_functions")
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def s3_list_buckets() -> str:
    """List S3 buckets."""
    r = _boto_call("s3", "list_buckets")
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def cloudwatch_get_alarms(state: str = "ALARM") -> str:
    """Get CloudWatch alarms by state."""
    r = _boto_call("cloudwatch", "describe_alarms", StateValue=state)
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def ecs_list_clusters() -> str:
    """List ECS clusters."""
    r = _boto_call("ecs", "list_clusters")
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def eks_list_clusters() -> str:
    """List EKS clusters."""
    r = _boto_call("eks", "list_clusters")
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def asg_describe_groups(name: str = "") -> str:
    """Describe Auto Scaling groups."""
    kwargs = {}
    if name:
        kwargs["AutoScalingGroupNames"] = [name]
    r = _boto_call("autoscaling", "describe_auto_scaling_groups", **kwargs)
    return ToolResult.success(r).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="aws_general", command_param=None)
def iam_get_account_summary() -> str:
    """Get IAM account summary."""
    r = _boto_call("iam", "get_account_summary")
    return ToolResult.success(r).to_json()

# ─── T1: Low-Risk Write ────────────────────────────────────────

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="aws_general", command_param=None)
def asg_set_desired_capacity(group_name: str, desired: int) -> str:
    """Set ASG desired capacity."""
    desired = max(0, min(desired, 50))
    r = _boto_call("autoscaling", "set_desired_capacity",
                    AutoScalingGroupName=group_name, DesiredCapacity=desired)
    return ToolResult.success({"group": group_name, "desired": desired}).to_json()

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="aws_general", command_param=None)
def lambda_update_concurrency(function_name: str, concurrency: int) -> str:
    """Update Lambda reserved concurrency."""
    concurrency = max(0, min(concurrency, 1000))
    r = _boto_call("lambda", "put_function_concurrency",
                    FunctionName=function_name, ReservedConcurrentExecutions=concurrency)
    return ToolResult.success(r).to_json()

# ─── T2: High-Risk ─────────────────────────────────────────────

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="aws_general", command_param=None, dry_run_support=True)
def ec2_reboot_instance(instance_id: str, dry_run: bool = False) -> str:
    """Reboot an EC2 instance. Requires approval_token."""
    r = _boto_call("ec2", "reboot_instances", InstanceIds=[instance_id], DryRun=dry_run)
    return ToolResult.success({"instance_id": instance_id, "action": "reboot"}).to_json()

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="aws_general", command_param=None, dry_run_support=True)
def rds_failover(db_cluster_id: str, dry_run: bool = False) -> str:
    """Failover an RDS cluster. Requires approval_token."""
    r = _boto_call("rds", "failover_db_cluster", DBClusterIdentifier=db_cluster_id)
    return ToolResult.success({"cluster": db_cluster_id, "action": "failover"}).to_json()

# ─── T3: Destructive ───────────────────────────────────────────

@secure_tool(tier=SecurityTier.T3_DESTRUCTIVE, skill="aws_general", command_param=None, dry_run_support=True)
def ec2_terminate_instance(instance_id: str, dry_run: bool = False) -> str:
    """Terminate an EC2 instance. Requires dual approval. 🔴"""
    r = _boto_call("ec2", "terminate_instances", InstanceIds=[instance_id], DryRun=dry_run)
    return ToolResult.success({"instance_id": instance_id, "action": "terminate"}).to_json()

@secure_tool(tier=SecurityTier.T3_DESTRUCTIVE, skill="aws_general", command_param=None, dry_run_support=True)
def rds_delete_instance(db_instance_id: str, skip_snapshot: bool = False, dry_run: bool = False) -> str:
    """Delete an RDS instance. Requires dual approval. 🔴"""
    kwargs = {"DBInstanceIdentifier": db_instance_id, "SkipFinalSnapshot": skip_snapshot}
    r = _boto_call("rds", "delete_db_instance", **kwargs)
    return ToolResult.success({"db_instance": db_instance_id, "action": "delete"}).to_json()
