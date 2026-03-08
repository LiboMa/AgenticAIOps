"""Router: /api/aws, /api/cloudwatch, /api/scanner - AWS resources and scanner."""

from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException

from routers.schemas import (
    SetRegionRequest, MonitorResourceRequest, CloudWatchLogsRequest,
)
from routers.deps import (
    get_scanner, get_current_region, set_current_region,
    get_monitored_resources, set_monitored_resources,
)

router = APIRouter(tags=["aws"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def get_aws_client(service_name: str):
    """Get AWS client, returns None if not configured."""
    try:
        import boto3
        return boto3.client(service_name)
    except Exception:
        return None


# =============================================================================
# AWS Resource APIs (with mock fallback)
# =============================================================================

@router.get("/api/aws/ec2")
async def list_ec2_instances():
    """List EC2 instances."""
    client = get_aws_client('ec2')

    if client:
        try:
            response = client.describe_instances()
            instances = []
            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    name = next((t['Value'] for t in instance.get('Tags', []) if t['Key'] == 'Name'), 'Unnamed')
                    instances.append({
                        'id': instance['InstanceId'],
                        'name': name,
                        'type': instance['InstanceType'],
                        'state': instance['State']['Name'],
                        'az': instance.get('Placement', {}).get('AvailabilityZone', 'N/A'),
                        'cpu': 0,
                    })
            running = sum(1 for i in instances if i['state'] == 'running')
            stopped = sum(1 for i in instances if i['state'] == 'stopped')
            return {
                'instances': instances,
                'stats': {'total': len(instances), 'running': running, 'stopped': stopped}
            }
        except Exception:
            pass

    return {
        'instances': [
            {'id': 'i-0abc123def456', 'name': 'web-server-1', 'type': 't3.medium', 'state': 'running', 'az': 'us-east-1a', 'cpu': 45},
            {'id': 'i-0def456abc789', 'name': 'api-server-1', 'type': 't3.large', 'state': 'running', 'az': 'us-east-1b', 'cpu': 62},
            {'id': 'i-0ghi789jkl012', 'name': 'db-server-1', 'type': 'r5.xlarge', 'state': 'running', 'az': 'us-east-1a', 'cpu': 78},
            {'id': 'i-0mno345pqr678', 'name': 'worker-1', 'type': 't3.small', 'state': 'stopped', 'az': 'us-east-1c', 'cpu': 0},
            {'id': 'i-0stu901vwx234', 'name': 'batch-processor', 'type': 'm5.large', 'state': 'running', 'az': 'us-east-1b', 'cpu': 33},
        ],
        'stats': {'total': 5, 'running': 4, 'stopped': 1}
    }


@router.get("/api/aws/lambda")
async def list_lambda_functions():
    """List Lambda functions."""
    client = get_aws_client('lambda')

    if client:
        try:
            response = client.list_functions()
            functions = []
            for fn in response.get('Functions', []):
                functions.append({
                    'name': fn['FunctionName'],
                    'runtime': fn.get('Runtime', 'N/A'),
                    'memory': fn.get('MemorySize', 0),
                    'timeout': fn.get('Timeout', 0),
                    'invocations': 0,
                })
            return {'functions': functions}
        except Exception:
            pass

    return {
        'functions': [
            {'name': 'api-handler', 'runtime': 'python3.11', 'memory': 256, 'timeout': 30, 'invocations': 1250},
            {'name': 'image-processor', 'runtime': 'nodejs18.x', 'memory': 512, 'timeout': 60, 'invocations': 340},
            {'name': 'notification-sender', 'runtime': 'python3.11', 'memory': 128, 'timeout': 15, 'invocations': 890},
            {'name': 'data-transformer', 'runtime': 'python3.12', 'memory': 1024, 'timeout': 120, 'invocations': 456},
            {'name': 'auth-validator', 'runtime': 'nodejs20.x', 'memory': 256, 'timeout': 10, 'invocations': 2100},
        ]
    }


@router.get("/api/aws/s3")
async def list_s3_buckets():
    """List S3 buckets."""
    client = get_aws_client('s3')

    if client:
        try:
            response = client.list_buckets()
            buckets = []
            for bucket in response.get('Buckets', []):
                buckets.append({
                    'name': bucket['Name'],
                    'region': 'us-east-1',
                    'objects': 0,
                    'size': 'N/A',
                    'public': False,
                })
            return {'buckets': buckets}
        except Exception:
            pass

    return {
        'buckets': [
            {'name': 'prod-assets-bucket', 'region': 'us-east-1', 'objects': 12450, 'size': '45.2 GB', 'public': False},
            {'name': 'logs-archive-bucket', 'region': 'us-east-1', 'objects': 89230, 'size': '128.5 GB', 'public': False},
            {'name': 'static-website-bucket', 'region': 'us-east-1', 'objects': 234, 'size': '1.2 GB', 'public': True},
            {'name': 'backup-daily-bucket', 'region': 'us-west-2', 'objects': 567, 'size': '89.7 GB', 'public': False},
        ]
    }


@router.get("/api/aws/rds")
async def list_rds_instances():
    """List RDS database instances."""
    client = get_aws_client('rds')

    if client:
        try:
            response = client.describe_db_instances()
            instances = []
            for db in response.get('DBInstances', []):
                instances.append({
                    'id': db['DBInstanceIdentifier'],
                    'engine': db['Engine'],
                    'status': db['DBInstanceStatus'],
                    'class': db['DBInstanceClass'],
                    'storage': db.get('AllocatedStorage', 0),
                })
            return {'instances': instances}
        except Exception:
            pass

    return {
        'instances': [
            {'id': 'prod-mysql-primary', 'engine': 'mysql', 'status': 'available', 'class': 'db.r5.large', 'storage': 500},
            {'id': 'prod-postgres-main', 'engine': 'postgres', 'status': 'available', 'class': 'db.r5.xlarge', 'storage': 1000},
            {'id': 'analytics-redshift', 'engine': 'redshift', 'status': 'available', 'class': 'dc2.large', 'storage': 2000},
        ]
    }


@router.get("/api/aws/scan")
async def scan_aws_resources():
    """Scan all AWS resources and return summary with potential issues."""
    ec2_data = await list_ec2_instances()
    lambda_data = await list_lambda_functions()
    s3_data = await list_s3_buckets()
    rds_data = await list_rds_instances()

    issues = []

    for instance in ec2_data.get('instances', []):
        if instance.get('cpu', 0) > 70:
            issues.append({
                'resource': f"EC2: {instance['name']}",
                'severity': 'high' if instance['cpu'] > 85 else 'medium',
                'issue': f"High CPU utilization: {instance['cpu']}%",
                'recommendation': 'Consider scaling up or investigating workload'
            })

    for bucket in s3_data.get('buckets', []):
        if bucket.get('public'):
            issues.append({
                'resource': f"S3: {bucket['name']}",
                'severity': 'high',
                'issue': 'Bucket has public access enabled',
                'recommendation': 'Review bucket policy and disable public access if not needed'
            })

    return {
        'summary': {
            'ec2': {'count': len(ec2_data.get('instances', [])), 'running': ec2_data.get('stats', {}).get('running', 0)},
            'lambda': {'count': len(lambda_data.get('functions', []))},
            's3': {'count': len(s3_data.get('buckets', []))},
            'rds': {'count': len(rds_data.get('instances', []))},
        },
        'issues': issues,
        'scanned_at': datetime.now().isoformat()
    }


# =============================================================================
# AWS Cloud Scanner (Full Resource Discovery)
# =============================================================================

@router.get("/api/scanner/account")
async def get_account_info():
    """Get current AWS account information."""
    scanner = get_scanner(get_current_region())
    return scanner.get_account_info()


@router.get("/api/scanner/regions")
async def list_regions():
    """List available AWS regions."""
    scanner = get_scanner(get_current_region())
    regions = scanner.list_regions()
    common = ["ap-southeast-1", "us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1"]
    return {
        "current": get_current_region(),
        "common": common,
        "all": regions,
    }


@router.post("/api/scanner/region")
async def set_region(request: SetRegionRequest):
    """Set the current region for scanning."""
    set_current_region(request.region)
    return {"status": "ok", "region": get_current_region()}


@router.get("/api/scanner/scan")
async def scan_all_resources_full(region: Optional[str] = None):
    """Perform full cloud scan of all AWS resources."""
    scan_region = region or get_current_region()
    scanner = get_scanner(scan_region)
    return scanner.scan_all_resources()


@router.get("/api/scanner/service/{service}")
async def scan_service(service: str, region: Optional[str] = None):
    """Scan a specific AWS service."""
    scan_region = region or get_current_region()
    scanner = get_scanner(scan_region)

    service_scanners = {
        "ec2": scanner._scan_ec2,
        "lambda": scanner._scan_lambda,
        "s3": scanner._scan_s3,
        "rds": scanner._scan_rds,
        "iam": scanner._scan_iam,
        "eks": scanner._scan_eks,
        "cloudwatch": scanner._scan_cloudwatch_alarms,
    }

    if service not in service_scanners:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")

    return {
        "service": service,
        "region": scan_region,
        "data": service_scanners[service](),
    }


# =============================================================================
# Monitoring
# =============================================================================

@router.post("/api/scanner/monitor")
async def add_to_monitoring(request: MonitorResourceRequest):
    """Add a resource to the monitoring list."""
    monitored = get_monitored_resources()

    for r in monitored:
        if r["resource_id"] == request.resource_id:
            return {"status": "already_monitored", "resource_id": request.resource_id}

    monitored.append({
        "resource_id": request.resource_id,
        "resource_type": request.resource_type,
        "name": request.name,
        "service": request.service,
        "added_at": datetime.now().isoformat(),
    })

    return {"status": "ok", "resource_id": request.resource_id, "total_monitored": len(monitored)}


@router.delete("/api/scanner/monitor/{resource_id}")
async def remove_from_monitoring(resource_id: str):
    """Remove a resource from monitoring."""
    monitored = get_monitored_resources()
    new_list = [r for r in monitored if r["resource_id"] != resource_id]
    set_monitored_resources(new_list)
    return {"status": "ok", "resource_id": resource_id, "total_monitored": len(new_list)}


@router.get("/api/scanner/monitored")
async def list_monitored_resources():
    """List all monitored resources."""
    monitored = get_monitored_resources()
    return {"resources": monitored, "count": len(monitored)}


# =============================================================================
# CloudWatch
# =============================================================================

@router.get("/api/cloudwatch/metrics/ec2/{instance_id}")
async def get_ec2_metrics(instance_id: str, metric: str = "CPUUtilization", hours: int = 1):
    """Get CloudWatch metrics for an EC2 instance."""
    scanner = get_scanner(get_current_region())
    return scanner.get_ec2_metrics(instance_id, metric, hours)


@router.get("/api/cloudwatch/metrics/rds/{db_id}")
async def get_rds_metrics(db_id: str, metric: str = "CPUUtilization", hours: int = 1):
    """Get CloudWatch metrics for an RDS instance."""
    scanner = get_scanner(get_current_region())
    return scanner.get_rds_metrics(db_id, metric, hours)


@router.get("/api/cloudwatch/metrics/lambda/{function_name}")
async def get_lambda_metrics(function_name: str, metric: str = "Duration", hours: int = 1):
    """Get CloudWatch metrics for a Lambda function."""
    scanner = get_scanner(get_current_region())
    return scanner.get_lambda_metrics(function_name, metric, hours)


@router.post("/api/cloudwatch/logs")
async def get_cloudwatch_logs(request: CloudWatchLogsRequest):
    """Get CloudWatch logs."""
    scanner = get_scanner(get_current_region())
    return scanner.get_cloudwatch_logs(
        request.log_group,
        request.filter_pattern,
        request.limit,
        request.hours,
    )
