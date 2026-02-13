"""
SOP (Standard Operating Procedure) System

This module provides:
- SOP definition and loading (YAML format)
- SOP execution engine with step tracking
- SOP suggestion based on anomaly/incident
- Execution history and reporting
"""

import json
import logging
import yaml
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib

logger = logging.getLogger(__name__)


class StepType(str, Enum):
    """Types of SOP steps"""
    MANUAL = "manual"           # Human action required
    AUTO = "auto"               # Automated action
    APPROVAL = "approval"       # Requires approval to proceed
    CONDITIONAL = "conditional" # Branch based on condition
    NOTIFICATION = "notification"  # Send notification


class StepStatus(str, Enum):
    """Status of SOP step execution"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class SOPStep:
    """A single step in an SOP"""
    step_id: str
    name: str
    description: str
    step_type: StepType
    
    # For automated steps
    action: str = ""            # Action to execute
    action_params: Dict[str, Any] = field(default_factory=dict)
    
    # For conditional steps
    condition: str = ""
    on_true: str = ""           # Next step if true
    on_false: str = ""          # Next step if false
    
    # Execution settings
    timeout_seconds: int = 300
    retry_count: int = 0
    
    # Metadata
    estimated_minutes: int = 5
    requires_approval: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['step_type'] = self.step_type.value
        return result


@dataclass
class SOP:
    """Standard Operating Procedure definition"""
    sop_id: str
    name: str
    description: str
    category: str               # incident, change, maintenance, deployment
    service: str                # ec2, rds, lambda, etc.
    severity: str               # critical, high, medium, low
    
    # Trigger conditions
    trigger_type: str = "manual"  # manual, metric, anomaly, schedule
    trigger_conditions: Dict[str, Any] = field(default_factory=dict)
    
    # Steps
    steps: List[SOPStep] = field(default_factory=list)
    
    # Metadata
    version: str = "1.0"
    author: str = "system"
    created_at: str = ""
    updated_at: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Related resources
    related_runbooks: List[str] = field(default_factory=list)
    related_patterns: List[str] = field(default_factory=list)
    
    # Statistics
    execution_count: int = 0
    success_rate: float = 0.0
    avg_duration_minutes: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['steps'] = [s.to_dict() if isinstance(s, SOPStep) else s for s in self.steps]
        return result
    
    @classmethod
    def from_yaml(cls, yaml_content: str) -> 'SOP':
        """Parse SOP from YAML content."""
        data = yaml.safe_load(yaml_content)
        
        # Parse steps
        steps = []
        for step_data in data.get('steps', []):
            step = SOPStep(
                step_id=step_data.get('id', ''),
                name=step_data.get('name', ''),
                description=step_data.get('description', ''),
                step_type=StepType(step_data.get('type', 'manual')),
                action=step_data.get('action', ''),
                action_params=step_data.get('params', {}),
                condition=step_data.get('condition', ''),
                on_true=step_data.get('on_true', ''),
                on_false=step_data.get('on_false', ''),
                timeout_seconds=step_data.get('timeout', 300),
                retry_count=step_data.get('retry', 0),
                estimated_minutes=step_data.get('estimated_minutes', 5),
                requires_approval=step_data.get('requires_approval', False)
            )
            steps.append(step)
        
        return cls(
            sop_id=data.get('id', ''),
            name=data.get('name', ''),
            description=data.get('description', ''),
            category=data.get('category', 'incident'),
            service=data.get('service', 'general'),
            severity=data.get('severity', 'medium'),
            trigger_type=data.get('trigger', {}).get('type', 'manual'),
            trigger_conditions=data.get('trigger', {}).get('conditions', {}),
            steps=steps,
            version=data.get('version', '1.0'),
            author=data.get('author', 'system'),
            tags=data.get('tags', []),
            related_runbooks=data.get('related_runbooks', []),
            related_patterns=data.get('related_patterns', [])
        )


@dataclass
class SOPExecution:
    """Record of an SOP execution"""
    execution_id: str
    sop_id: str
    sop_name: str
    
    # Execution context
    triggered_by: str = "manual"  # manual, alert, schedule
    trigger_context: Dict[str, Any] = field(default_factory=dict)
    
    # Status tracking
    status: str = "pending"  # pending, in_progress, completed, failed, cancelled
    current_step: int = 0
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    
    # Timestamps
    started_at: str = ""
    completed_at: str = ""
    
    # Results
    success: bool = False
    error_message: str = ""
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SOPStore:
    """Store and manage SOPs."""
    
    def __init__(self, s3_bucket: str = "agentic-aiops-knowledge-base"):
        self.s3_bucket = s3_bucket
        self.sops: Dict[str, SOP] = {}
        self.executions: Dict[str, SOPExecution] = {}
        self._loaded = False
        
        # Load built-in SOPs
        self._load_builtin_sops()
        
        # Try to load from S3
        self._load_from_s3()
    
    def _load_builtin_sops(self):
        """Load built-in SOP templates."""
        builtin_sops = [
            self._create_ec2_high_cpu_sop(),
            self._create_rds_failover_sop(),
            self._create_lambda_error_sop(),
            self._create_ec2_disk_full_sop(),
            self._create_rds_storage_low_sop(),
            self._create_elb_5xx_spike_sop(),
            self._create_ec2_unreachable_sop(),
            self._create_dynamodb_throttle_sop(),
        ]
        for sop in builtin_sops:
            self.sops[sop.sop_id] = sop
    
    def _create_ec2_high_cpu_sop(self) -> SOP:
        """Built-in SOP for EC2 high CPU."""
        return SOP(
            sop_id="sop-ec2-high-cpu",
            name="EC2 High CPU Response",
            description="Standard procedure for handling EC2 instances with high CPU utilization",
            category="incident",
            service="ec2",
            severity="high",
            trigger_type="metric",
            trigger_conditions={"metric": "CPUUtilization", "threshold": 90, "operator": ">="},
            steps=[
                SOPStep(
                    step_id="1",
                    name="Identify Top Processes",
                    description="SSH into instance and identify processes consuming CPU",
                    step_type=StepType.MANUAL,
                    action="ssh_command",
                    action_params={"command": "top -bn1 | head -20"},
                    estimated_minutes=5
                ),
                SOPStep(
                    step_id="2",
                    name="Check Recent Changes",
                    description="Review CloudTrail for recent configuration changes",
                    step_type=StepType.AUTO,
                    action="cloudtrail_query",
                    action_params={"hours": 24, "resource_type": "ec2"},
                    estimated_minutes=3
                ),
                SOPStep(
                    step_id="3",
                    name="Scale Decision",
                    description="Decide whether to scale up or optimize",
                    step_type=StepType.APPROVAL,
                    requires_approval=True,
                    estimated_minutes=10
                ),
                SOPStep(
                    step_id="4",
                    name="Execute Remediation",
                    description="Scale instance or restart problematic process",
                    step_type=StepType.MANUAL,
                    estimated_minutes=15
                ),
                SOPStep(
                    step_id="5",
                    name="Verify Resolution",
                    description="Confirm CPU utilization has normalized",
                    step_type=StepType.AUTO,
                    action="check_metric",
                    action_params={"metric": "CPUUtilization", "threshold": 80},
                    estimated_minutes=5
                )
            ],
            tags=["ec2", "cpu", "performance"],
            created_at=datetime.utcnow().isoformat()
        )
    
    def _create_rds_failover_sop(self) -> SOP:
        """Built-in SOP for RDS failover."""
        return SOP(
            sop_id="sop-rds-failover",
            name="RDS Planned Failover",
            description="Standard procedure for RDS Multi-AZ failover",
            category="maintenance",
            service="rds",
            severity="medium",
            trigger_type="manual",
            steps=[
                SOPStep(
                    step_id="1",
                    name="Pre-flight Checks",
                    description="Verify Multi-AZ is enabled and standby is healthy",
                    step_type=StepType.AUTO,
                    action="rds_describe",
                    estimated_minutes=2
                ),
                SOPStep(
                    step_id="2",
                    name="Notify Stakeholders",
                    description="Send notification about planned failover",
                    step_type=StepType.NOTIFICATION,
                    action="notify",
                    action_params={"channel": "slack", "message": "RDS failover starting"},
                    estimated_minutes=1
                ),
                SOPStep(
                    step_id="3",
                    name="Approval",
                    description="Get approval to proceed with failover",
                    step_type=StepType.APPROVAL,
                    requires_approval=True,
                    estimated_minutes=5
                ),
                SOPStep(
                    step_id="4",
                    name="Execute Failover",
                    description="Initiate RDS failover",
                    step_type=StepType.AUTO,
                    action="rds_failover",
                    estimated_minutes=5
                ),
                SOPStep(
                    step_id="5",
                    name="Verify Connectivity",
                    description="Test database connectivity after failover",
                    step_type=StepType.MANUAL,
                    estimated_minutes=5
                ),
                SOPStep(
                    step_id="6",
                    name="Complete Notification",
                    description="Notify stakeholders of completion",
                    step_type=StepType.NOTIFICATION,
                    action="notify",
                    action_params={"channel": "slack", "message": "RDS failover completed"},
                    estimated_minutes=1
                )
            ],
            tags=["rds", "failover", "maintenance"],
            created_at=datetime.utcnow().isoformat()
        )
    
    def _create_lambda_error_sop(self) -> SOP:
        """Built-in SOP for Lambda errors."""
        return SOP(
            sop_id="sop-lambda-errors",
            name="Lambda Error Investigation",
            description="Standard procedure for investigating Lambda function errors",
            category="incident",
            service="lambda",
            severity="high",
            trigger_type="metric",
            trigger_conditions={"metric": "Errors", "threshold": 10, "period": 300},
            steps=[
                SOPStep(
                    step_id="1",
                    name="Check Error Logs",
                    description="Review CloudWatch Logs for error details",
                    step_type=StepType.AUTO,
                    action="cloudwatch_logs",
                    action_params={"log_group": "/aws/lambda/*", "hours": 1},
                    estimated_minutes=5
                ),
                SOPStep(
                    step_id="2",
                    name="Identify Error Pattern",
                    description="Categorize the error type",
                    step_type=StepType.MANUAL,
                    estimated_minutes=10
                ),
                SOPStep(
                    step_id="3",
                    name="Check Recent Deployments",
                    description="Review recent function updates",
                    step_type=StepType.AUTO,
                    action="lambda_versions",
                    estimated_minutes=3
                ),
                SOPStep(
                    step_id="4",
                    name="Rollback Decision",
                    description="Decide whether to rollback to previous version",
                    step_type=StepType.CONDITIONAL,
                    condition="error_rate > 50%",
                    on_true="5",
                    on_false="6",
                    estimated_minutes=5
                ),
                SOPStep(
                    step_id="5",
                    name="Execute Rollback",
                    description="Rollback to previous stable version",
                    step_type=StepType.AUTO,
                    action="lambda_rollback",
                    requires_approval=True,
                    estimated_minutes=5
                ),
                SOPStep(
                    step_id="6",
                    name="Monitor",
                    description="Monitor error rate for 15 minutes",
                    step_type=StepType.MANUAL,
                    estimated_minutes=15
                )
            ],
            tags=["lambda", "errors", "investigation"],
            created_at=datetime.utcnow().isoformat()
        )
    
    def _create_ec2_disk_full_sop(self) -> SOP:
        """Built-in SOP for EC2 disk full."""
        return SOP(
            sop_id="sop-ec2-disk-full",
            name="EC2 Disk Full Response",
            description="Handle EC2 instances with disk usage > 90%",
            category="incident", service="ec2", severity="high",
            trigger_type="metric",
            trigger_conditions={"metric": "DiskSpaceUtilization", "threshold": 90},
            steps=[
                SOPStep(step_id="1", name="Identify Large Files",
                    description="Find files consuming disk space",
                    step_type=StepType.AUTO, action="ssh_command",
                    action_params={"command": "du -sh /var/log/* | sort -rh | head -10"},
                    estimated_minutes=3),
                SOPStep(step_id="2", name="Clean Old Logs",
                    description="Rotate and clean old log files",
                    step_type=StepType.AUTO, action="ssh_command",
                    action_params={"command": "journalctl --vacuum-size=100M && find /var/log -name '*.gz' -mtime +7 -delete"},
                    estimated_minutes=5),
                SOPStep(step_id="3", name="Expand EBS Volume",
                    description="If cleanup insufficient, expand EBS volume",
                    step_type=StepType.APPROVAL, requires_approval=True,
                    estimated_minutes=10),
                SOPStep(step_id="4", name="Verify Disk Space",
                    description="Confirm disk usage is below threshold",
                    step_type=StepType.AUTO, action="check_metric",
                    action_params={"metric": "DiskSpaceUtilization", "threshold": 80},
                    estimated_minutes=3),
            ],
            tags=["ec2", "disk", "storage", "cleanup"],
            created_at=datetime.utcnow().isoformat()
        )
    
    def _create_rds_storage_low_sop(self) -> SOP:
        """Built-in SOP for RDS low storage."""
        return SOP(
            sop_id="sop-rds-storage-low",
            name="RDS Storage Low Response",
            description="Handle RDS instances with storage < 10GB remaining",
            category="incident", service="rds", severity="medium",
            trigger_type="metric",
            trigger_conditions={"metric": "FreeStorageSpace", "threshold": 10737418240, "operator": "<="},
            steps=[
                SOPStep(step_id="1", name="Check Current Usage",
                    description="Describe RDS instance storage details",
                    step_type=StepType.AUTO, action="rds_describe",
                    estimated_minutes=2),
                SOPStep(step_id="2", name="Create Snapshot",
                    description="Create DB snapshot before changes",
                    step_type=StepType.AUTO, action="rds_snapshot",
                    estimated_minutes=5),
                SOPStep(step_id="3", name="Expand Storage",
                    description="Modify RDS instance to increase allocated storage",
                    step_type=StepType.APPROVAL, requires_approval=True,
                    action="rds_modify", action_params={"increase_gb": 50},
                    estimated_minutes=15),
                SOPStep(step_id="4", name="Verify Storage",
                    description="Confirm storage expansion completed",
                    step_type=StepType.AUTO, action="check_metric",
                    estimated_minutes=5),
            ],
            tags=["rds", "storage", "expansion"],
            created_at=datetime.utcnow().isoformat()
        )
    
    def _create_elb_5xx_spike_sop(self) -> SOP:
        """Built-in SOP for ELB 5xx spike."""
        return SOP(
            sop_id="sop-elb-5xx-spike",
            name="ELB 5xx Error Spike Response",
            description="Handle ALB/ELB with elevated 5xx error rate",
            category="incident", service="elb", severity="high",
            trigger_type="metric",
            trigger_conditions={"metric": "HTTPCode_ELB_5XX_Count", "threshold": 10},
            steps=[
                SOPStep(step_id="1", name="Check Target Health",
                    description="Verify target group health status",
                    step_type=StepType.AUTO, action="describe_target_health",
                    estimated_minutes=2),
                SOPStep(step_id="2", name="Check Backend Logs",
                    description="Review backend application logs for errors",
                    step_type=StepType.MANUAL, estimated_minutes=5),
                SOPStep(step_id="3", name="Deregister Unhealthy",
                    description="Deregister unhealthy targets from target group",
                    step_type=StepType.AUTO, action="deregister_targets",
                    estimated_minutes=3),
                SOPStep(step_id="4", name="Restart Unhealthy Instances",
                    description="Reboot unhealthy backend instances",
                    step_type=StepType.AUTO, action="reboot_instances",
                    estimated_minutes=5),
                SOPStep(step_id="5", name="Monitor Recovery",
                    description="Monitor 5xx rate for 10 minutes",
                    step_type=StepType.MANUAL, estimated_minutes=10),
            ],
            tags=["elb", "alb", "5xx", "errors", "backend"],
            created_at=datetime.utcnow().isoformat()
        )
    
    def _create_ec2_unreachable_sop(self) -> SOP:
        """Built-in SOP for EC2 unreachable."""
        return SOP(
            sop_id="sop-ec2-unreachable",
            name="EC2 Instance Unreachable Response",
            description="Handle EC2 instances failing status checks",
            category="incident", service="ec2", severity="high",
            trigger_type="metric",
            trigger_conditions={"metric": "StatusCheckFailed", "threshold": 1},
            steps=[
                SOPStep(step_id="1", name="Check Instance Status",
                    description="Describe instance and system status checks",
                    step_type=StepType.AUTO, action="describe_instance_status",
                    estimated_minutes=2),
                SOPStep(step_id="2", name="Reboot Instance",
                    description="Attempt soft reboot",
                    step_type=StepType.APPROVAL, action="reboot_instances",
                    requires_approval=True, estimated_minutes=5),
                SOPStep(step_id="3", name="Check Security Groups",
                    description="Verify security group rules allow required traffic",
                    step_type=StepType.AUTO, action="describe_security_groups",
                    estimated_minutes=3),
                SOPStep(step_id="4", name="Check VPC/Subnet",
                    description="Verify VPC routing and subnet configuration",
                    step_type=StepType.MANUAL, estimated_minutes=5),
                SOPStep(step_id="5", name="Verify Recovery",
                    description="Confirm instance is reachable",
                    step_type=StepType.AUTO, action="check_metric",
                    action_params={"metric": "StatusCheckFailed", "threshold": 0},
                    estimated_minutes=3),
            ],
            tags=["ec2", "unreachable", "status", "network"],
            created_at=datetime.utcnow().isoformat()
        )
    
    def _create_dynamodb_throttle_sop(self) -> SOP:
        """Built-in SOP for DynamoDB throttling."""
        return SOP(
            sop_id="sop-dynamodb-throttle",
            name="DynamoDB Throttling Response",
            description="Handle DynamoDB tables experiencing throttling events",
            category="incident", service="dynamodb", severity="medium",
            trigger_type="metric",
            trigger_conditions={"metric": "ThrottledRequests", "threshold": 1},
            steps=[
                SOPStep(step_id="1", name="Check Table Capacity",
                    description="Describe table provisioned/on-demand capacity",
                    step_type=StepType.AUTO, action="describe_table",
                    estimated_minutes=2),
                SOPStep(step_id="2", name="Check Consumed Capacity",
                    description="Review consumed RCU/WCU metrics",
                    step_type=StepType.AUTO, action="check_metric",
                    action_params={"metrics": ["ConsumedReadCapacityUnits", "ConsumedWriteCapacityUnits"]},
                    estimated_minutes=3),
                SOPStep(step_id="3", name="Increase Capacity",
                    description="Increase RCU/WCU or switch to on-demand",
                    step_type=StepType.AUTO, action="update_table",
                    action_params={"billing_mode": "PAY_PER_REQUEST"},
                    estimated_minutes=5),
                SOPStep(step_id="4", name="Verify Throttling Stopped",
                    description="Confirm no more throttling events",
                    step_type=StepType.AUTO, action="check_metric",
                    action_params={"metric": "ThrottledRequests", "threshold": 0},
                    estimated_minutes=5),
            ],
            tags=["dynamodb", "throttle", "capacity", "rcu", "wcu"],
            created_at=datetime.utcnow().isoformat()
        )
    
    def _load_from_s3(self):
        """Load SOPs from S3."""
        try:
            import boto3
            s3 = boto3.client('s3')
            
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix='sops/'):
                for obj in page.get('Contents', []):
                    if obj['Key'].endswith('.yaml') or obj['Key'].endswith('.yml'):
                        try:
                            response = s3.get_object(Bucket=self.s3_bucket, Key=obj['Key'])
                            yaml_content = response['Body'].read().decode()
                            sop = SOP.from_yaml(yaml_content)
                            self.sops[sop.sop_id] = sop
                            logger.info(f"Loaded SOP from S3: {sop.sop_id}")
                        except Exception as e:
                            logger.warning(f"Failed to load SOP {obj['Key']}: {e}")
            
            self._loaded = True
        except Exception as e:
            logger.warning(f"S3 SOP load failed: {e}")
            self._loaded = True
    
    def get_sop(self, sop_id: str) -> Optional[SOP]:
        """Get SOP by ID."""
        return self.sops.get(sop_id)
    
    def list_sops(
        self,
        service: Optional[str] = None,
        category: Optional[str] = None,
        severity: Optional[str] = None
    ) -> List[SOP]:
        """List SOPs with optional filters."""
        results = []
        for sop in self.sops.values():
            if service and sop.service != service:
                continue
            if category and sop.category != category:
                continue
            if severity and sop.severity != severity:
                continue
            results.append(sop)
        return results
    
    def suggest_sops(
        self,
        service: str,
        issue_keywords: List[str],
        severity: Optional[str] = None
    ) -> List[SOP]:
        """Suggest relevant SOPs for an issue."""
        results = []
        
        for sop in self.sops.values():
            score = 0
            
            # Service match
            if sop.service == service:
                score += 5
            
            # Keyword match in name/description/tags
            sop_text = f"{sop.name} {sop.description} {' '.join(sop.tags)}".lower()
            for keyword in issue_keywords:
                if keyword.lower() in sop_text:
                    score += 2
            
            # Severity match
            if severity and sop.severity == severity:
                score += 1
            
            if score > 0:
                results.append((score, sop))
        
        # Sort by score
        results.sort(key=lambda x: x[0], reverse=True)
        return [sop for _, sop in results[:5]]
    
    def save_sop(self, sop: SOP) -> bool:
        """Save SOP to store and S3."""
        self.sops[sop.sop_id] = sop
        
        try:
            import boto3
            s3 = boto3.client('s3')
            
            key = f"sops/{sop.service}/{sop.sop_id}.json"
            s3.put_object(
                Bucket=self.s3_bucket,
                Key=key,
                Body=json.dumps(sop.to_dict(), indent=2),
                ContentType='application/json'
            )
            return True
        except Exception as e:
            logger.warning(f"S3 SOP save failed: {e}")
            return False


class SOPExecutor:
    """Execute SOPs with step tracking."""
    
    def __init__(self, sop_store: SOPStore):
        self.sop_store = sop_store
    
    def start_execution(
        self,
        sop_id: str,
        triggered_by: str = "manual",
        context: Dict[str, Any] = None
    ) -> Optional[SOPExecution]:
        """Start executing an SOP."""
        sop = self.sop_store.get_sop(sop_id)
        if not sop:
            return None
        
        execution_id = hashlib.sha256(
            f"{sop_id}:{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:12]
        
        execution = SOPExecution(
            execution_id=execution_id,
            sop_id=sop_id,
            sop_name=sop.name,
            triggered_by=triggered_by,
            trigger_context=context or {},
            status="in_progress",
            current_step=0,
            started_at=datetime.utcnow().isoformat()
        )
        
        self.sop_store.executions[execution_id] = execution
        logger.info(f"Started SOP execution: {execution_id} for {sop_id}")
        
        return execution
    
    def get_execution(self, execution_id: str) -> Optional[SOPExecution]:
        """Get execution status."""
        return self.sop_store.executions.get(execution_id)
    
    def complete_step(
        self,
        execution_id: str,
        step_result: Dict[str, Any]
    ) -> bool:
        """Mark a step as complete and advance."""
        execution = self.sop_store.executions.get(execution_id)
        if not execution:
            return False
        
        execution.step_results.append(step_result)
        execution.current_step += 1
        
        # Check if all steps complete
        sop = self.sop_store.get_sop(execution.sop_id)
        if sop and execution.current_step >= len(sop.steps):
            execution.status = "completed"
            execution.success = True
            execution.completed_at = datetime.utcnow().isoformat()
            
            # Update SOP statistics
            sop.execution_count += 1
        
        return True


# Singleton instances
_sop_store: Optional[SOPStore] = None
_sop_executor: Optional[SOPExecutor] = None


def get_sop_store() -> SOPStore:
    """Get or create SOP store instance."""
    global _sop_store
    if _sop_store is None:
        _sop_store = SOPStore()
    return _sop_store


def get_sop_executor() -> SOPExecutor:
    """Get or create SOP executor instance."""
    global _sop_executor
    if _sop_executor is None:
        _sop_executor = SOPExecutor(get_sop_store())
    return _sop_executor
