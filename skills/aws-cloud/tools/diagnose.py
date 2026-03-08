"""AWS Cloud diagnostic tools for Strands Agent.

Read-tier tools for observing and diagnosing AWS resources:
EC2, ASG, ECS, Lambda, CloudFormation, CloudWatch, CloudTrail.

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

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _parse_json(raw: str) -> dict | list | str:
    """Try to parse JSON, return raw string on failure."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


# ---------------------------------------------------------------------------
# EC2 Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def describe_instances(instance_ids: Optional[str] = None,
                       filters: Optional[str] = None,
                       region: Optional[str] = None) -> str:
    """Describe EC2 instances. Provide comma-separated instance IDs or
    filter expression like 'Name=tag:Name,Values=web*'.

    Args:
        instance_ids: Comma-separated EC2 instance IDs (e.g. i-0abc,i-0def)
        filters: AWS CLI filter expression
        region: AWS region (defaults to configured region)

    Returns:
        JSON description of instances including state, type, IPs, tags.
    """
    args = []
    if instance_ids:
        args.extend(["--instance-ids"] + instance_ids.split(","))
    if filters:
        args.extend(["--filters", filters])
    raw = _aws("ec2", "describe-instances", args, region)
    data = _parse_json(raw)
    if isinstance(data, dict):
        instances = []
        for res in data.get("Reservations", []):
            for inst in res.get("Instances", []):
                name = ""
                for tag in inst.get("Tags", []):
                    if tag["Key"] == "Name":
                        name = tag["Value"]
                instances.append({
                    "InstanceId": inst["InstanceId"],
                    "Name": name,
                    "State": inst["State"]["Name"],
                    "Type": inst["InstanceType"],
                    "PrivateIp": inst.get("PrivateIpAddress", ""),
                    "PublicIp": inst.get("PublicIpAddress", ""),
                    "AZ": inst.get("Placement", {}).get("AvailabilityZone", ""),
                    "LaunchTime": inst.get("LaunchTime", ""),
                })
        return json.dumps(instances, indent=2, default=str)
    return str(data)


@tool
def describe_instance_status(instance_ids: str,
                             region: Optional[str] = None) -> str:
    """Check EC2 instance health status checks (system + instance).

    Args:
        instance_ids: Comma-separated EC2 instance IDs
        region: AWS region

    Returns:
        Instance status check results.
    """
    args = ["--instance-ids"] + instance_ids.split(",") + ["--include-all-instances"]
    return _aws("ec2", "describe-instance-status", args, region)


@tool
def get_ec2_cpu_utilization(instance_id: str, hours: int = 1,
                            region: Optional[str] = None) -> str:
    """Get EC2 CPU utilization metrics from CloudWatch.

    Args:
        instance_id: EC2 instance ID
        hours: Number of hours to look back (default 1)
        region: AWS region

    Returns:
        CPU utilization data points.
    """
    import datetime
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(hours=hours)
    args = [
        "--namespace", "AWS/EC2",
        "--metric-name", "CPUUtilization",
        "--dimensions", f"Name=InstanceId,Value={instance_id}",
        "--start-time", start.strftime("%Y-%m-%dT%H:%M:%S"),
        "--end-time", end.strftime("%Y-%m-%dT%H:%M:%S"),
        "--period", "300",
        "--statistics", "Average", "Maximum",
    ]
    return _aws("cloudwatch", "get-metric-statistics", args, region)


# ---------------------------------------------------------------------------
# ASG Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def describe_asgs(asg_names: Optional[str] = None,
                  region: Optional[str] = None) -> str:
    """Describe Auto Scaling Groups.

    Args:
        asg_names: Comma-separated ASG names (optional, lists all if omitted)
        region: AWS region

    Returns:
        ASG details including desired/min/max capacity, instances.
    """
    args = []
    if asg_names:
        args.extend(["--auto-scaling-group-names"] + asg_names.split(","))
    raw = _aws("autoscaling", "describe-auto-scaling-groups", args, region)
    data = _parse_json(raw)
    if isinstance(data, dict):
        asgs = []
        for asg in data.get("AutoScalingGroups", []):
            asgs.append({
                "Name": asg["AutoScalingGroupName"],
                "Desired": asg["DesiredCapacity"],
                "Min": asg["MinSize"],
                "Max": asg["MaxSize"],
                "Instances": len(asg.get("Instances", [])),
                "HealthyInstances": sum(1 for i in asg.get("Instances", [])
                                        if i.get("HealthStatus") == "Healthy"),
                "AZs": asg.get("AvailabilityZones", []),
            })
        return json.dumps(asgs, indent=2)
    return str(data)


@tool
def describe_scaling_activities(asg_name: str, max_items: int = 10,
                                region: Optional[str] = None) -> str:
    """Get recent Auto Scaling activities for an ASG.

    Args:
        asg_name: Auto Scaling Group name
        max_items: Max number of activities to return
        region: AWS region

    Returns:
        Recent scaling activities with causes.
    """
    args = ["--auto-scaling-group-name", asg_name, "--max-items", str(max_items)]
    return _aws("autoscaling", "describe-scaling-activities", args, region)


# ---------------------------------------------------------------------------
# ECS Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def describe_ecs_services(cluster: str, services: str,
                          region: Optional[str] = None) -> str:
    """Describe ECS services in a cluster.

    Args:
        cluster: ECS cluster name or ARN
        services: Comma-separated service names
        region: AWS region

    Returns:
        Service details including running count, desired count, events.
    """
    args = ["--cluster", cluster, "--services"] + services.split(",")
    raw = _aws("ecs", "describe-services", args, region)
    data = _parse_json(raw)
    if isinstance(data, dict):
        svcs = []
        for s in data.get("services", []):
            svcs.append({
                "Name": s["serviceName"],
                "Status": s["status"],
                "Running": s["runningCount"],
                "Desired": s["desiredCount"],
                "Pending": s["pendingCount"],
                "TaskDef": s.get("taskDefinition", "").split("/")[-1],
                "Events": [e["message"] for e in s.get("events", [])[:5]],
            })
        return json.dumps(svcs, indent=2)
    return str(data)


@tool
def list_ecs_tasks(cluster: str, service_name: Optional[str] = None,
                   status: str = "RUNNING",
                   region: Optional[str] = None) -> str:
    """List ECS tasks in a cluster.

    Args:
        cluster: ECS cluster name or ARN
        service_name: Filter by service name (optional)
        status: RUNNING or STOPPED
        region: AWS region

    Returns:
        List of task ARNs.
    """
    args = ["--cluster", cluster, "--desired-status", status]
    if service_name:
        args.extend(["--service-name", service_name])
    return _aws("ecs", "list-tasks", args, region)


# ---------------------------------------------------------------------------
# Lambda Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def list_functions(region: Optional[str] = None) -> str:
    """List all Lambda functions with runtime and memory info.

    Args:
        region: AWS region

    Returns:
        Lambda functions with name, runtime, memory, timeout, last modified.
    """
    raw = _aws("lambda", "list-functions", [], region)
    data = _parse_json(raw)
    if isinstance(data, dict):
        funcs = []
        for f in data.get("Functions", []):
            funcs.append({
                "Name": f["FunctionName"],
                "Runtime": f.get("Runtime", ""),
                "Memory": f.get("MemorySize", 0),
                "Timeout": f.get("Timeout", 0),
                "LastModified": f.get("LastModified", ""),
                "CodeSize": f.get("CodeSize", 0),
            })
        return json.dumps(funcs, indent=2)
    return str(data)


@tool
def get_function_config(function_name: str,
                        region: Optional[str] = None) -> str:
    """Get Lambda function configuration details.

    Args:
        function_name: Lambda function name or ARN
        region: AWS region

    Returns:
        Function configuration including env vars, VPC, layers.
    """
    args = ["--function-name", function_name]
    return _aws("lambda", "get-function-configuration", args, region)


# ---------------------------------------------------------------------------
# CloudFormation Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def describe_stacks(stack_name: Optional[str] = None,
                    region: Optional[str] = None) -> str:
    """Describe CloudFormation stacks.

    Args:
        stack_name: Stack name (optional, lists all if omitted)
        region: AWS region

    Returns:
        Stack details including status, outputs, parameters.
    """
    args = []
    if stack_name:
        args.extend(["--stack-name", stack_name])
    return _aws("cloudformation", "describe-stacks", args, region)


@tool
def get_stack_events(stack_name: str, max_items: int = 20,
                     region: Optional[str] = None) -> str:
    """Get recent CloudFormation stack events (useful for debugging rollbacks).

    Args:
        stack_name: Stack name
        max_items: Max events to return
        region: AWS region

    Returns:
        Stack events with status and reason.
    """
    args = ["--stack-name", stack_name, "--max-items", str(max_items)]
    raw = _aws("cloudformation", "describe-stack-events", args, region)
    data = _parse_json(raw)
    if isinstance(data, dict):
        events = []
        for e in data.get("StackEvents", [])[:max_items]:
            events.append({
                "Timestamp": e.get("Timestamp", ""),
                "Resource": e.get("LogicalResourceId", ""),
                "Type": e.get("ResourceType", ""),
                "Status": e.get("ResourceStatus", ""),
                "Reason": e.get("ResourceStatusReason", ""),
            })
        return json.dumps(events, indent=2, default=str)
    return str(data)


# ---------------------------------------------------------------------------
# CloudWatch Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def describe_alarms(state: Optional[str] = None,
                    alarm_prefix: Optional[str] = None,
                    region: Optional[str] = None) -> str:
    """Describe CloudWatch alarms, optionally filtered by state.

    Args:
        state: Filter by state: OK, ALARM, INSUFFICIENT_DATA
        alarm_prefix: Filter by alarm name prefix
        region: AWS region

    Returns:
        Alarm details including state, metric, threshold.
    """
    args = []
    if state:
        args.extend(["--state-value", state])
    if alarm_prefix:
        args.extend(["--alarm-name-prefix", alarm_prefix])
    return _aws("cloudwatch", "describe-alarms", args, region)


@tool
def get_metric_data(namespace: str, metric_name: str,
                    dimension_name: str, dimension_value: str,
                    hours: int = 1, period: int = 300,
                    stat: str = "Average",
                    region: Optional[str] = None) -> str:
    """Get CloudWatch metric data for any AWS service.

    Args:
        namespace: CloudWatch namespace (e.g. AWS/EC2, AWS/RDS, AWS/Lambda)
        metric_name: Metric name (e.g. CPUUtilization, Duration, Errors)
        dimension_name: Dimension name (e.g. InstanceId, FunctionName)
        dimension_value: Dimension value
        hours: Hours to look back (default 1)
        period: Period in seconds (default 300)
        stat: Statistic: Average, Sum, Maximum, Minimum
        region: AWS region

    Returns:
        Metric data points.
    """
    import datetime
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(hours=hours)
    args = [
        "--namespace", namespace,
        "--metric-name", metric_name,
        "--dimensions", f"Name={dimension_name},Value={dimension_value}",
        "--start-time", start.strftime("%Y-%m-%dT%H:%M:%S"),
        "--end-time", end.strftime("%Y-%m-%dT%H:%M:%S"),
        "--period", str(period),
        "--statistics", stat,
    ]
    return _aws("cloudwatch", "get-metric-statistics", args, region)


# ---------------------------------------------------------------------------
# CloudTrail Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def lookup_events(resource_name: Optional[str] = None,
                  event_name: Optional[str] = None,
                  username: Optional[str] = None,
                  max_items: int = 20,
                  region: Optional[str] = None) -> str:
    """Look up CloudTrail events to find who changed what.

    Args:
        resource_name: Filter by resource name
        event_name: Filter by API event name (e.g. TerminateInstances)
        username: Filter by IAM username
        max_items: Max events to return
        region: AWS region

    Returns:
        CloudTrail events with user, action, resource, time.
    """
    args = ["--max-items", str(max_items)]
    if resource_name:
        args.extend(["--lookup-attributes",
                      f"AttributeKey=ResourceName,AttributeValue={resource_name}"])
    elif event_name:
        args.extend(["--lookup-attributes",
                      f"AttributeKey=EventName,AttributeValue={event_name}"])
    elif username:
        args.extend(["--lookup-attributes",
                      f"AttributeKey=Username,AttributeValue={username}"])
    return _aws("cloudtrail", "lookup-events", args, region)


# ---------------------------------------------------------------------------
# EBS / Volumes Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def describe_volumes(volume_ids: Optional[str] = None,
                     instance_id: Optional[str] = None,
                     region: Optional[str] = None) -> str:
    """Describe EBS volumes.

    Args:
        volume_ids: Comma-separated volume IDs
        instance_id: Filter by attached instance ID
        region: AWS region

    Returns:
        Volume details including size, type, state, attachments.
    """
    args = []
    if volume_ids:
        args.extend(["--volume-ids"] + volume_ids.split(","))
    if instance_id:
        args.extend(["--filters", f"Name=attachment.instance-id,Values={instance_id}"])
    return _aws("ec2", "describe-volumes", args, region)


# ---------------------------------------------------------------------------
# S3 Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def list_buckets(region: Optional[str] = None) -> str:
    """List all S3 buckets.

    Args:
        region: AWS region

    Returns:
        List of S3 buckets with creation dates.
    """
    return _aws("s3api", "list-buckets", [], region)


# ---------------------------------------------------------------------------
# IAM Tools (read-tier)
# ---------------------------------------------------------------------------

@tool
def get_instance_profile(instance_id: str,
                         region: Optional[str] = None) -> str:
    """Get the IAM instance profile attached to an EC2 instance.

    Args:
        instance_id: EC2 instance ID
        region: AWS region

    Returns:
        Instance profile ARN and role info.
    """
    raw = _aws("ec2", "describe-instances",
               ["--instance-ids", instance_id,
                "--query", "Reservations[0].Instances[0].IamInstanceProfile"],
               region)
    return raw
