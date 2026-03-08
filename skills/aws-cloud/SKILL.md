---
name: aws-cloud
description: >
  Manage and diagnose AWS cloud infrastructure including EC2, ASG, ECS,
  Lambda, CloudFormation, IAM, S3, and CloudWatch. Use when investigating
  instance health, scaling events, deployment failures, permission errors,
  resource limits, or general AWS operations.
license: Apache-2.0
compatibility: Requires AWS CLI with appropriate IAM permissions
metadata:
  author: agenticaiops
  version: "1.0"
  routing:
    domains: [aws, ec2, ecs, lambda, asg, cloudformation, cfn, iam, s3, cloudwatch, cloudtrail, config, ssm, autoscaling, ami, ebs, snapshot]
    keywords: [InsufficientInstanceCapacity, InstanceLimitExceeded, UnauthorizedAccess, AccessDenied, ThrottlingException, ServiceQuotaExceeded, StackRollback, DeploymentFailed, HealthCheckFailed, ScalingActivity, SpotInterruption]
    confidence_boost: 0.15
safety:
  tiers:
    read: [describe_instances, describe_asgs, describe_ecs_services, list_functions, describe_stacks, get_metric_data, describe_alarms, lookup_events, get_instance_profile, describe_volumes, list_buckets, get_stack_events]
    write: [start_instances, reboot_instances, update_asg_capacity, update_ecs_service, invoke_function, update_stack, put_metric_alarm, tag_resource, create_snapshot]
    dangerous: [terminate_instances, delete_stack, delete_snapshot, detach_volume, remove_role_from_instance_profile, delete_function, force_delete_asg]
  security_filter: aws
allowed-tools: Bash(aws:ec2,ecs,lambda,autoscaling,cloudformation,iam,sts,cloudwatch,cloudtrail,config,ssm,s3)
---

# AWS Cloud Operations Skill

You are an AWS Solutions Architect and operations expert. When this skill
is active, follow these guidelines for diagnosing and managing AWS resources.

## Principles

1. **Read before act** — always describe before modify/delete
2. **Least privilege** — verify IAM permissions match the minimum needed
3. **Region awareness** — confirm the target region; resources are regional
4. **Tag everything** — ensure Owner, Environment, Cost-Center tags
5. **Snapshot before mutate** — create EBS snapshots before volume modifications
6. **CloudTrail is the audit log** — check recent API calls when investigating changes

<!-- tier: read -->
## Diagnostics

### EC2 Instance Health
```bash
aws ec2 describe-instance-status --instance-ids <id> --include-all-instances
aws ssm describe-instance-information --filters Key=InstanceIds,Values=<id>
aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization --dimensions Name=InstanceId,Value=<id> --start-time <T> --end-time <T> --period 300 --statistics Average
```

### Auto Scaling
```bash
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names <name>
aws autoscaling describe-scaling-activities --auto-scaling-group-name <name> --max-items 10
```

### ECS Services
```bash
aws ecs describe-services --cluster <cluster> --services <service>
aws ecs list-tasks --cluster <cluster> --service-name <service> --desired-status RUNNING
aws logs get-log-events --log-group-name <group> --log-stream-name <stream> --limit 50
```

### CloudTrail (Who changed what?)
```bash
aws cloudtrail lookup-events --lookup-attributes AttributeKey=ResourceName,AttributeValue=<resource> --max-items 20
```

<!-- tier: write -->
## Remediation

```bash
aws ec2 start-instances --instance-ids <id>
aws ec2 reboot-instances --instance-ids <id>
aws autoscaling update-auto-scaling-group --auto-scaling-group-name <name> --desired-capacity <n>
aws ecs update-service --cluster <cluster> --service <service> --desired-count <n>
aws rds create-db-snapshot --db-instance-identifier <id> --db-snapshot-identifier pre-change-$(date +%Y%m%d)
```

<!-- tier: dangerous -->
## Destructive Operations (requires approval)

- `terminate-instances` — permanent instance destruction
- `delete-stack` — removes all stack resources
- `delete-snapshot` — irreversible backup deletion
- `force-delete-auto-scaling-group` — kills all instances immediately

## Common Patterns

| Symptom | Likely Cause | First Check |
|---------|-------------|-------------|
| Instance unreachable | Status check failed | describe-instance-status |
| ASG not scaling | Cooldown or template error | describe-scaling-activities |
| ECS task crashing | OOM or bad image | Task stopped reason + CW Logs |
| Lambda timeout | Cold start or downstream | Function config + X-Ray |
| Stack rollback | Resource creation failed | describe-stack-events |
| AccessDenied | Missing IAM permission | CloudTrail + policy simulator |
