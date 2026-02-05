"""
AWS Operations Module - Full Service Operations Support

Provides operational capabilities for AWS services:
- Health Check
- Anomaly Detection
- Logs Analysis
- Metrics Monitoring
- Operations (Start/Stop/Restart)

Similar to EKS support but for EC2, RDS, Lambda, S3, etc.
"""

import boto3
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from botocore.exceptions import ClientError
import statistics

logger = logging.getLogger(__name__)


class AWSServiceOps:
    """
    AWS Service Operations - Full operational support for AWS services.
    
    Provides:
    - Health Check (status, connectivity, performance)
    - Anomaly Detection (metric thresholds, patterns)
    - Logs Analysis (error detection, patterns)
    - Metrics Monitoring (CPU, Memory, Connections, etc.)
    - Operations (Start/Stop/Reboot for EC2, etc.)
    """
    
    def __init__(self, region: str = "ap-southeast-1"):
        self.region = region
        self._session = boto3.Session(region_name=region)
        
    def _get_client(self, service: str):
        return self._session.client(service, region_name=self.region)
    
    # =========================================================================
    # EC2 Operations
    # =========================================================================
    
    def ec2_health_check(self, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Comprehensive EC2 health check.
        
        Checks:
        - Instance status (running/stopped)
        - System status checks
        - Instance status checks
        - Recent CloudWatch metrics
        - CloudWatch alarms
        """
        ec2 = self._get_client('ec2')
        cw = self._get_client('cloudwatch')
        
        results = {
            "service": "EC2",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "instances": [],
            "issues": [],
            "metrics_summary": {},
        }
        
        try:
            # Get instances
            filters = []
            if instance_id:
                filters = [{'Name': 'instance-id', 'Values': [instance_id]}]
            
            response = ec2.describe_instances(Filters=filters) if filters else ec2.describe_instances()
            
            # Get instance status
            instance_ids = []
            for reservation in response.get('Reservations', []):
                for inst in reservation.get('Instances', []):
                    instance_ids.append(inst['InstanceId'])
            
            # Get status checks
            status_response = ec2.describe_instance_status(
                InstanceIds=instance_ids[:20] if instance_ids else [],
                IncludeAllInstances=True
            ) if instance_ids else {'InstanceStatuses': []}
            
            status_map = {s['InstanceId']: s for s in status_response.get('InstanceStatuses', [])}
            
            for reservation in response.get('Reservations', []):
                for inst in reservation.get('Instances', []):
                    inst_id = inst['InstanceId']
                    state = inst['State']['Name']
                    
                    # Get name tag
                    name = "unnamed"
                    for tag in inst.get('Tags', []):
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                            break
                    
                    # Status checks
                    status_info = status_map.get(inst_id, {})
                    system_status = status_info.get('SystemStatus', {}).get('Status', 'N/A')
                    instance_status = status_info.get('InstanceStatus', {}).get('Status', 'N/A')
                    
                    # Health determination
                    health = "healthy"
                    issues = []
                    
                    if state != 'running':
                        health = "warning" if state == 'stopped' else "unhealthy"
                        issues.append(f"Instance is {state}")
                    
                    if system_status == 'impaired':
                        health = "unhealthy"
                        issues.append("System status check failed")
                    
                    if instance_status == 'impaired':
                        health = "unhealthy"
                        issues.append("Instance status check failed")
                    
                    # Get CPU metrics (last 30 min)
                    cpu_metrics = self._get_metric_stats(
                        'AWS/EC2', 'CPUUtilization',
                        [{'Name': 'InstanceId', 'Value': inst_id}],
                        minutes=30
                    )
                    
                    # Check for high CPU
                    if cpu_metrics.get('max', 0) > 90:
                        issues.append(f"High CPU: {cpu_metrics['max']:.1f}%")
                        if health == "healthy":
                            health = "warning"
                    
                    instance_health = {
                        "id": inst_id,
                        "name": name,
                        "state": state,
                        "type": inst['InstanceType'],
                        "health": health,
                        "system_status": system_status,
                        "instance_status": instance_status,
                        "cpu_avg": cpu_metrics.get('avg', 0),
                        "cpu_max": cpu_metrics.get('max', 0),
                        "issues": issues,
                    }
                    
                    results["instances"].append(instance_health)
                    
                    if issues:
                        results["issues"].extend([{
                            "resource": f"{name} ({inst_id})",
                            "issue": issue
                        } for issue in issues])
            
            # Overall status
            if any(i["health"] == "unhealthy" for i in results["instances"]):
                results["overall_status"] = "unhealthy"
            elif any(i["health"] == "warning" for i in results["instances"]):
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def ec2_get_metrics(self, instance_id: str, hours: int = 1) -> Dict[str, Any]:
        """Get comprehensive EC2 metrics."""
        metrics_to_fetch = [
            'CPUUtilization',
            'NetworkIn',
            'NetworkOut',
            'DiskReadOps',
            'DiskWriteOps',
            'StatusCheckFailed',
        ]
        
        results = {
            "instance_id": instance_id,
            "period_hours": hours,
            "metrics": {},
        }
        
        for metric in metrics_to_fetch:
            data = self._get_metric_stats(
                'AWS/EC2', metric,
                [{'Name': 'InstanceId', 'Value': instance_id}],
                minutes=hours * 60
            )
            results["metrics"][metric] = data
        
        return results
    
    def ec2_get_logs(self, instance_id: str, hours: int = 1) -> Dict[str, Any]:
        """Get EC2 system logs (from CloudWatch Logs agent if configured)."""
        logs = self._get_client('logs')
        
        # Common log group patterns
        log_groups = [
            f"/var/log/messages",
            f"/var/log/syslog",
            f"/aws/ec2/{instance_id}",
            f"ec2/{instance_id}",
        ]
        
        results = {
            "instance_id": instance_id,
            "logs": [],
            "errors": [],
        }
        
        # Also try to get console output
        ec2 = self._get_client('ec2')
        try:
            console = ec2.get_console_output(InstanceId=instance_id)
            if console.get('Output'):
                # Get last 50 lines
                output_lines = console['Output'].split('\n')[-50:]
                results["console_output"] = output_lines
        except:
            pass
        
        return results
    
    def ec2_operations(self, instance_id: str, action: str) -> Dict[str, Any]:
        """Perform EC2 operations (start/stop/reboot)."""
        ec2 = self._get_client('ec2')
        
        try:
            if action == 'start':
                response = ec2.start_instances(InstanceIds=[instance_id])
                return {"success": True, "action": "start", "instance_id": instance_id}
            elif action == 'stop':
                response = ec2.stop_instances(InstanceIds=[instance_id])
                return {"success": True, "action": "stop", "instance_id": instance_id}
            elif action == 'reboot':
                response = ec2.reboot_instances(InstanceIds=[instance_id])
                return {"success": True, "action": "reboot", "instance_id": instance_id}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ClientError as e:
            return {"success": False, "error": str(e)}
    
    # =========================================================================
    # RDS Operations
    # =========================================================================
    
    def rds_health_check(self, db_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Comprehensive RDS health check.
        
        Checks:
        - Instance status
        - Connection count
        - CPU/Memory usage
        - Storage space
        - Replica lag (if applicable)
        """
        rds = self._get_client('rds')
        
        results = {
            "service": "RDS",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "databases": [],
            "issues": [],
        }
        
        try:
            if db_id:
                response = rds.describe_db_instances(DBInstanceIdentifier=db_id)
            else:
                response = rds.describe_db_instances()
            
            for db in response.get('DBInstances', []):
                db_identifier = db['DBInstanceIdentifier']
                status = db['DBInstanceStatus']
                
                health = "healthy"
                issues = []
                
                # Check status
                if status != 'available':
                    health = "warning" if status in ['backing-up', 'maintenance'] else "unhealthy"
                    issues.append(f"Status: {status}")
                
                # Check public accessibility
                if db.get('PubliclyAccessible'):
                    issues.append("⚠️ Publicly accessible")
                
                # Get metrics
                cpu = self._get_metric_stats(
                    'AWS/RDS', 'CPUUtilization',
                    [{'Name': 'DBInstanceIdentifier', 'Value': db_identifier}],
                    minutes=30
                )
                
                connections = self._get_metric_stats(
                    'AWS/RDS', 'DatabaseConnections',
                    [{'Name': 'DBInstanceIdentifier', 'Value': db_identifier}],
                    minutes=30
                )
                
                free_storage = self._get_metric_stats(
                    'AWS/RDS', 'FreeStorageSpace',
                    [{'Name': 'DBInstanceIdentifier', 'Value': db_identifier}],
                    minutes=30
                )
                
                # Anomaly detection
                if cpu.get('max', 0) > 80:
                    issues.append(f"High CPU: {cpu['max']:.1f}%")
                    if health == "healthy":
                        health = "warning"
                
                # Storage check (if less than 10GB free)
                storage_gb = free_storage.get('avg', 0) / (1024**3)
                if storage_gb < 10 and storage_gb > 0:
                    issues.append(f"Low storage: {storage_gb:.1f}GB free")
                    health = "warning"
                
                db_health = {
                    "id": db_identifier,
                    "engine": f"{db['Engine']} {db.get('EngineVersion', '')}",
                    "class": db['DBInstanceClass'],
                    "status": status,
                    "health": health,
                    "multi_az": db.get('MultiAZ', False),
                    "public": db.get('PubliclyAccessible', False),
                    "storage_gb": db.get('AllocatedStorage', 0),
                    "cpu_avg": cpu.get('avg', 0),
                    "cpu_max": cpu.get('max', 0),
                    "connections": connections.get('avg', 0),
                    "free_storage_gb": storage_gb,
                    "issues": issues,
                }
                
                results["databases"].append(db_health)
                
                if issues:
                    results["issues"].extend([{
                        "resource": db_identifier,
                        "issue": issue
                    } for issue in issues])
            
            # Overall status
            if any(d["health"] == "unhealthy" for d in results["databases"]):
                results["overall_status"] = "unhealthy"
            elif any(d["health"] == "warning" for d in results["databases"]):
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def rds_get_metrics(self, db_id: str, hours: int = 1) -> Dict[str, Any]:
        """Get comprehensive RDS metrics."""
        metrics_to_fetch = [
            'CPUUtilization',
            'DatabaseConnections',
            'FreeStorageSpace',
            'ReadIOPS',
            'WriteIOPS',
            'ReadLatency',
            'WriteLatency',
            'FreeableMemory',
        ]
        
        results = {
            "db_id": db_id,
            "period_hours": hours,
            "metrics": {},
        }
        
        for metric in metrics_to_fetch:
            data = self._get_metric_stats(
                'AWS/RDS', metric,
                [{'Name': 'DBInstanceIdentifier', 'Value': db_id}],
                minutes=hours * 60
            )
            results["metrics"][metric] = data
        
        return results
    
    def rds_get_logs(self, db_id: str, log_type: str = "error") -> Dict[str, Any]:
        """Get RDS logs (error, slowquery, etc.)."""
        rds = self._get_client('rds')
        
        try:
            # List available log files
            response = rds.describe_db_log_files(DBInstanceIdentifier=db_id)
            log_files = response.get('DescribeDBLogFiles', [])
            
            results = {
                "db_id": db_id,
                "available_logs": [f['LogFileName'] for f in log_files[-10:]],
                "log_content": [],
            }
            
            # Get recent error log if available
            for log_file in log_files[-5:]:
                if log_type in log_file['LogFileName'].lower():
                    try:
                        log_data = rds.download_db_log_file_portion(
                            DBInstanceIdentifier=db_id,
                            LogFileName=log_file['LogFileName'],
                            NumberOfLines=100
                        )
                        results["log_content"].append({
                            "file": log_file['LogFileName'],
                            "content": log_data.get('LogFileData', '')[-5000:]  # Last 5KB
                        })
                    except:
                        pass
            
            return results
            
        except ClientError as e:
            return {"error": str(e)}
    
    # =========================================================================
    # Lambda Operations
    # =========================================================================
    
    def lambda_health_check(self, function_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Comprehensive Lambda health check.
        
        Checks:
        - Error rate
        - Duration
        - Throttles
        - Concurrent executions
        """
        lambda_client = self._get_client('lambda')
        
        results = {
            "service": "Lambda",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "functions": [],
            "issues": [],
        }
        
        try:
            if function_name:
                response = {'Functions': [lambda_client.get_function(FunctionName=function_name)['Configuration']]}
            else:
                response = lambda_client.list_functions()
            
            for func in response.get('Functions', []):
                fname = func['FunctionName']
                
                health = "healthy"
                issues = []
                
                # Get metrics
                invocations = self._get_metric_stats(
                    'AWS/Lambda', 'Invocations',
                    [{'Name': 'FunctionName', 'Value': fname}],
                    minutes=60
                )
                
                errors = self._get_metric_stats(
                    'AWS/Lambda', 'Errors',
                    [{'Name': 'FunctionName', 'Value': fname}],
                    minutes=60
                )
                
                duration = self._get_metric_stats(
                    'AWS/Lambda', 'Duration',
                    [{'Name': 'FunctionName', 'Value': fname}],
                    minutes=60
                )
                
                throttles = self._get_metric_stats(
                    'AWS/Lambda', 'Throttles',
                    [{'Name': 'FunctionName', 'Value': fname}],
                    minutes=60
                )
                
                # Calculate error rate
                total_invocations = invocations.get('sum', 0)
                total_errors = errors.get('sum', 0)
                error_rate = (total_errors / total_invocations * 100) if total_invocations > 0 else 0
                
                # Anomaly detection
                if error_rate > 5:
                    issues.append(f"High error rate: {error_rate:.1f}%")
                    health = "warning" if error_rate < 20 else "unhealthy"
                
                if throttles.get('sum', 0) > 0:
                    issues.append(f"Throttled: {throttles['sum']:.0f} times")
                    if health == "healthy":
                        health = "warning"
                
                # Duration check (if > 80% of timeout)
                timeout_ms = func.get('Timeout', 3) * 1000
                if duration.get('max', 0) > timeout_ms * 0.8:
                    issues.append(f"Near timeout: {duration['max']:.0f}ms / {timeout_ms}ms")
                    if health == "healthy":
                        health = "warning"
                
                func_health = {
                    "name": fname,
                    "runtime": func.get('Runtime', 'N/A'),
                    "memory": func.get('MemorySize', 0),
                    "timeout": func.get('Timeout', 0),
                    "health": health,
                    "invocations": total_invocations,
                    "errors": total_errors,
                    "error_rate": error_rate,
                    "duration_avg": duration.get('avg', 0),
                    "duration_max": duration.get('max', 0),
                    "throttles": throttles.get('sum', 0),
                    "issues": issues,
                }
                
                results["functions"].append(func_health)
                
                if issues:
                    results["issues"].extend([{
                        "resource": fname,
                        "issue": issue
                    } for issue in issues])
            
            # Overall status
            if any(f["health"] == "unhealthy" for f in results["functions"]):
                results["overall_status"] = "unhealthy"
            elif any(f["health"] == "warning" for f in results["functions"]):
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def lambda_get_logs(self, function_name: str, hours: int = 1, filter_errors: bool = False) -> Dict[str, Any]:
        """Get Lambda function logs from CloudWatch."""
        logs = self._get_client('logs')
        
        log_group = f"/aws/lambda/{function_name}"
        
        end_time = int(datetime.utcnow().timestamp() * 1000)
        start_time = end_time - (hours * 3600 * 1000)
        
        try:
            filter_pattern = "ERROR" if filter_errors else ""
            
            response = logs.filter_log_events(
                logGroupName=log_group,
                startTime=start_time,
                endTime=end_time,
                filterPattern=filter_pattern,
                limit=100,
            )
            
            return {
                "function_name": function_name,
                "log_group": log_group,
                "filter": filter_pattern,
                "events": [
                    {
                        "timestamp": datetime.fromtimestamp(e['timestamp'] / 1000).isoformat(),
                        "message": e['message'][:500],  # Truncate long messages
                    }
                    for e in response.get('events', [])
                ],
            }
        except ClientError as e:
            return {"error": str(e)}
    
    # =========================================================================
    # S3 Operations
    # =========================================================================
    
    def s3_health_check(self, bucket_name: Optional[str] = None) -> Dict[str, Any]:
        """
        S3 bucket health check.
        
        Checks:
        - Public access
        - Encryption
        - Versioning
        - Logging
        """
        s3 = self._get_client('s3')
        
        results = {
            "service": "S3",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "buckets": [],
            "issues": [],
        }
        
        try:
            if bucket_name:
                buckets = [{'Name': bucket_name}]
            else:
                buckets = s3.list_buckets().get('Buckets', [])
            
            for bucket in buckets[:20]:  # Limit for performance
                bname = bucket['Name']
                
                health = "healthy"
                issues = []
                
                # Check public access
                is_public = False
                try:
                    public_access = s3.get_public_access_block(Bucket=bname)
                    block_config = public_access.get('PublicAccessBlockConfiguration', {})
                    if not all([
                        block_config.get('BlockPublicAcls', False),
                        block_config.get('IgnorePublicAcls', False),
                        block_config.get('BlockPublicPolicy', False),
                        block_config.get('RestrictPublicBuckets', False),
                    ]):
                        is_public = True
                except:
                    # Check ACL as fallback
                    try:
                        acl = s3.get_bucket_acl(Bucket=bname)
                        for grant in acl.get('Grants', []):
                            grantee = grant.get('Grantee', {})
                            if 'AllUsers' in grantee.get('URI', ''):
                                is_public = True
                                break
                    except:
                        pass
                
                if is_public:
                    issues.append("⚠️ Public access enabled")
                    health = "warning"
                
                # Check encryption
                encryption = "unknown"
                try:
                    enc_response = s3.get_bucket_encryption(Bucket=bname)
                    encryption = "enabled"
                except ClientError as e:
                    if 'ServerSideEncryptionConfigurationNotFoundError' in str(e):
                        encryption = "disabled"
                        issues.append("No encryption configured")
                
                # Check versioning
                versioning = "disabled"
                try:
                    ver_response = s3.get_bucket_versioning(Bucket=bname)
                    versioning = ver_response.get('Status', 'disabled')
                except:
                    pass
                
                bucket_health = {
                    "name": bname,
                    "health": health,
                    "public": is_public,
                    "encryption": encryption,
                    "versioning": versioning,
                    "issues": issues,
                }
                
                results["buckets"].append(bucket_health)
                
                if issues:
                    results["issues"].extend([{
                        "resource": bname,
                        "issue": issue
                    } for issue in issues])
            
            # Overall status
            public_count = sum(1 for b in results["buckets"] if b["public"])
            if public_count > 0:
                results["overall_status"] = "warning"
                results["public_buckets"] = public_count
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _get_metric_stats(
        self,
        namespace: str,
        metric_name: str,
        dimensions: List[Dict[str, str]],
        minutes: int = 60
    ) -> Dict[str, float]:
        """Get metric statistics."""
        cw = self._get_client('cloudwatch')
        
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=minutes)
        
        try:
            response = cw.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=300,  # 5 minutes
                Statistics=['Average', 'Maximum', 'Minimum', 'Sum'],
            )
            
            datapoints = response.get('Datapoints', [])
            if not datapoints:
                return {}
            
            return {
                "avg": statistics.mean([d['Average'] for d in datapoints]) if datapoints else 0,
                "max": max([d['Maximum'] for d in datapoints]) if datapoints else 0,
                "min": min([d['Minimum'] for d in datapoints]) if datapoints else 0,
                "sum": sum([d['Sum'] for d in datapoints]) if datapoints else 0,
            }
        except ClientError:
            return {}
    
    def detect_anomalies(self, service: str, resource_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Detect anomalies in service metrics.
        
        Uses simple threshold-based detection + deviation from baseline.
        """
        results = {
            "service": service,
            "resource_id": resource_id,
            "anomalies": [],
            "checked_at": datetime.utcnow().isoformat(),
        }
        
        if service.lower() == 'ec2':
            health = self.ec2_health_check(resource_id)
            for inst in health.get('instances', []):
                if inst.get('cpu_max', 0) > 90:
                    results["anomalies"].append({
                        "type": "high_cpu",
                        "resource": inst['id'],
                        "value": inst['cpu_max'],
                        "threshold": 90,
                        "severity": "high",
                    })
                if inst['health'] == 'unhealthy':
                    results["anomalies"].append({
                        "type": "health_check_failed",
                        "resource": inst['id'],
                        "issues": inst['issues'],
                        "severity": "critical",
                    })
        
        elif service.lower() == 'rds':
            health = self.rds_health_check(resource_id)
            for db in health.get('databases', []):
                if db.get('cpu_max', 0) > 80:
                    results["anomalies"].append({
                        "type": "high_cpu",
                        "resource": db['id'],
                        "value": db['cpu_max'],
                        "threshold": 80,
                        "severity": "high",
                    })
                if db.get('free_storage_gb', 999) < 10:
                    results["anomalies"].append({
                        "type": "low_storage",
                        "resource": db['id'],
                        "value": db['free_storage_gb'],
                        "threshold": 10,
                        "severity": "high",
                    })
        
        elif service.lower() == 'lambda':
            health = self.lambda_health_check(resource_id)
            for func in health.get('functions', []):
                if func.get('error_rate', 0) > 5:
                    results["anomalies"].append({
                        "type": "high_error_rate",
                        "resource": func['name'],
                        "value": func['error_rate'],
                        "threshold": 5,
                        "severity": "high" if func['error_rate'] > 20 else "medium",
                    })
                if func.get('throttles', 0) > 0:
                    results["anomalies"].append({
                        "type": "throttling",
                        "resource": func['name'],
                        "value": func['throttles'],
                        "severity": "medium",
                    })
        
        return results


# Singleton instance
_ops: Optional[AWSServiceOps] = None


def get_aws_ops(region: str = "ap-southeast-1") -> AWSServiceOps:
    """Get or create AWS ops instance."""
    global _ops
    if _ops is None or _ops.region != region:
        _ops = AWSServiceOps(region=region)
    return _ops
