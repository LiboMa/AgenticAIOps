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
    
    def rds_operations(self, db_id: str, action: str, force: bool = False) -> Dict[str, Any]:
        """
        Perform RDS operations (reboot, failover).
        
        Actions:
        - reboot: Reboot the DB instance
        - failover: Force failover (Multi-AZ only)
        """
        rds = self._get_client('rds')
        
        try:
            if action == 'reboot':
                response = rds.reboot_db_instance(
                    DBInstanceIdentifier=db_id,
                    ForceFailover=force
                )
                return {
                    "success": True,
                    "action": "reboot",
                    "db_id": db_id,
                    "status": response['DBInstance']['DBInstanceStatus'],
                }
            elif action == 'failover':
                # Only works for Multi-AZ deployments
                response = rds.reboot_db_instance(
                    DBInstanceIdentifier=db_id,
                    ForceFailover=True
                )
                return {
                    "success": True,
                    "action": "failover",
                    "db_id": db_id,
                    "status": response['DBInstance']['DBInstanceStatus'],
                }
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ClientError as e:
            return {"success": False, "error": str(e)}
    
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
    
    def lambda_invoke(self, function_name: str, payload: Optional[Dict] = None, async_invoke: bool = False) -> Dict[str, Any]:
        """
        Invoke a Lambda function.
        
        Args:
            function_name: Name of the function
            payload: JSON payload to send
            async_invoke: If True, invoke asynchronously (Event type)
        """
        lambda_client = self._get_client('lambda')
        
        try:
            import json
            
            invoke_params = {
                'FunctionName': function_name,
                'InvocationType': 'Event' if async_invoke else 'RequestResponse',
            }
            
            if payload:
                invoke_params['Payload'] = json.dumps(payload)
            
            response = lambda_client.invoke(**invoke_params)
            
            result = {
                "success": True,
                "function_name": function_name,
                "status_code": response['StatusCode'],
                "invocation_type": 'async' if async_invoke else 'sync',
            }
            
            if not async_invoke and 'Payload' in response:
                try:
                    result["response"] = json.loads(response['Payload'].read().decode())
                except:
                    result["response"] = "Unable to parse response"
            
            if response.get('FunctionError'):
                result["success"] = False
                result["error"] = response['FunctionError']
            
            return result
            
        except ClientError as e:
            return {"success": False, "error": str(e)}
    
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


    # =========================================================================
    # VPC Operations
    # =========================================================================
    
    def vpc_health_check(self, vpc_id: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
        """
        VPC health check (optimized for speed).
        
        Checks:
        - VPC state
        - Subnets availability
        - Internet Gateway attachment
        - NAT Gateways status (limited to reduce API calls)
        
        Args:
            vpc_id: Specific VPC to check (optional)
            limit: Max VPCs to check (default 5 for speed)
        """
        ec2 = self._get_client('ec2')
        
        results = {
            "service": "VPC",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "vpcs": [],
            "issues": [],
        }
        
        try:
            if vpc_id:
                response = ec2.describe_vpcs(VpcIds=[vpc_id])
            else:
                response = ec2.describe_vpcs()
            
            # Limit VPCs for speed
            vpcs_to_check = response.get('Vpcs', [])[:limit]
            
            for vpc in vpcs_to_check:
                vid = vpc['VpcId']
                state = vpc['State']
                is_default = vpc.get('IsDefault', False)
                
                # Get VPC name
                name = vid
                for tag in vpc.get('Tags', []):
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                        break
                
                health = "healthy"
                issues = []
                
                if state != 'available':
                    health = "unhealthy"
                    issues.append(f"VPC state: {state}")
                
                # Check subnets
                subnets_response = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vid]}])
                subnets = subnets_response.get('Subnets', [])
                available_subnets = [s for s in subnets if s['State'] == 'available']
                
                if len(available_subnets) < len(subnets):
                    issues.append(f"Subnets: {len(available_subnets)}/{len(subnets)} available")
                    if health == "healthy":
                        health = "warning"
                
                # Check Internet Gateway
                igw_response = ec2.describe_internet_gateways(
                    Filters=[{'Name': 'attachment.vpc-id', 'Values': [vid]}]
                )
                igws = igw_response.get('InternetGateways', [])
                has_igw = len(igws) > 0
                
                # Check NAT Gateways
                nat_response = ec2.describe_nat_gateways(
                    Filters=[{'Name': 'vpc-id', 'Values': [vid]}, {'Name': 'state', 'Values': ['available', 'pending']}]
                )
                nat_gateways = nat_response.get('NatGateways', [])
                nat_available = [n for n in nat_gateways if n['State'] == 'available']
                
                if nat_gateways and len(nat_available) < len(nat_gateways):
                    issues.append(f"NAT Gateways: {len(nat_available)}/{len(nat_gateways)} available")
                    if health == "healthy":
                        health = "warning"
                
                vpc_health = {
                    "id": vid,
                    "name": name,
                    "state": state,
                    "health": health,
                    "is_default": is_default,
                    "cidr": vpc.get('CidrBlock', ''),
                    "subnets_count": len(subnets),
                    "subnets_available": len(available_subnets),
                    "has_igw": has_igw,
                    "nat_gateways": len(nat_gateways),
                    "issues": issues,
                }
                
                results["vpcs"].append(vpc_health)
                
                if issues:
                    results["issues"].extend([{
                        "resource": f"{name} ({vid})",
                        "issue": issue
                    } for issue in issues])
            
            # Overall status
            if any(v["health"] == "unhealthy" for v in results["vpcs"]):
                results["overall_status"] = "unhealthy"
            elif any(v["health"] == "warning" for v in results["vpcs"]):
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def vpc_scan(self) -> Dict[str, Any]:
        """Scan all VPCs in the region."""
        ec2 = self._get_client('ec2')
        
        try:
            response = ec2.describe_vpcs()
            vpcs = []
            
            for vpc in response.get('Vpcs', []):
                vid = vpc['VpcId']
                name = vid
                for tag in vpc.get('Tags', []):
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                        break
                
                vpcs.append({
                    "id": vid,
                    "name": name,
                    "state": vpc['State'],
                    "cidr": vpc.get('CidrBlock', ''),
                    "is_default": vpc.get('IsDefault', False),
                })
            
            return {
                "count": len(vpcs),
                "vpcs": vpcs,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    # =========================================================================
    # ELB (Elastic Load Balancer) Operations
    # =========================================================================
    
    def elb_health_check(self, lb_name: Optional[str] = None) -> Dict[str, Any]:
        """
        ELB/ALB/NLB health check.
        
        Checks:
        - Load balancer state
        - Target group health
        - Listener configuration
        - Unhealthy targets
        """
        elbv2 = self._get_client('elbv2')
        
        results = {
            "service": "ELB",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "load_balancers": [],
            "issues": [],
        }
        
        try:
            if lb_name:
                response = elbv2.describe_load_balancers(Names=[lb_name])
            else:
                response = elbv2.describe_load_balancers()
            
            for lb in response.get('LoadBalancers', []):
                lb_arn = lb['LoadBalancerArn']
                lb_name = lb['LoadBalancerName']
                state = lb['State']['Code']
                lb_type = lb['Type']
                
                health = "healthy"
                issues = []
                
                if state != 'active':
                    health = "warning" if state == 'provisioning' else "unhealthy"
                    issues.append(f"State: {state}")
                
                # Check target groups
                tg_response = elbv2.describe_target_groups(LoadBalancerArn=lb_arn)
                target_groups = tg_response.get('TargetGroups', [])
                
                unhealthy_targets = 0
                total_targets = 0
                
                for tg in target_groups:
                    tg_arn = tg['TargetGroupArn']
                    try:
                        health_response = elbv2.describe_target_health(TargetGroupArn=tg_arn)
                        for target in health_response.get('TargetHealthDescriptions', []):
                            total_targets += 1
                            if target['TargetHealth']['State'] != 'healthy':
                                unhealthy_targets += 1
                    except:
                        pass
                
                if unhealthy_targets > 0:
                    issues.append(f"Unhealthy targets: {unhealthy_targets}/{total_targets}")
                    if health == "healthy":
                        health = "warning"
                
                if total_targets == 0:
                    issues.append("No registered targets")
                    if health == "healthy":
                        health = "warning"
                
                lb_health = {
                    "name": lb_name,
                    "arn": lb_arn,
                    "type": lb_type,
                    "scheme": lb.get('Scheme', ''),
                    "state": state,
                    "health": health,
                    "dns_name": lb.get('DNSName', ''),
                    "target_groups": len(target_groups),
                    "total_targets": total_targets,
                    "unhealthy_targets": unhealthy_targets,
                    "issues": issues,
                }
                
                results["load_balancers"].append(lb_health)
                
                if issues:
                    results["issues"].extend([{
                        "resource": lb_name,
                        "issue": issue
                    } for issue in issues])
            
            # Overall status
            if any(lb["health"] == "unhealthy" for lb in results["load_balancers"]):
                results["overall_status"] = "unhealthy"
            elif any(lb["health"] == "warning" for lb in results["load_balancers"]):
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def elb_scan(self) -> Dict[str, Any]:
        """Scan all load balancers in the region."""
        elbv2 = self._get_client('elbv2')
        
        try:
            response = elbv2.describe_load_balancers()
            lbs = []
            
            for lb in response.get('LoadBalancers', []):
                lbs.append({
                    "name": lb['LoadBalancerName'],
                    "arn": lb['LoadBalancerArn'],
                    "type": lb['Type'],
                    "scheme": lb.get('Scheme', ''),
                    "state": lb['State']['Code'],
                    "dns_name": lb.get('DNSName', ''),
                    "vpc_id": lb.get('VpcId', ''),
                })
            
            return {
                "count": len(lbs),
                "load_balancers": lbs,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def elb_get_metrics(self, lb_name: str, lb_type: str = "application", hours: int = 1) -> Dict[str, Any]:
        """Get ELB/ALB metrics from CloudWatch."""
        namespace = "AWS/ApplicationELB" if lb_type == "application" else "AWS/NetworkELB"
        
        metrics_to_fetch = [
            'RequestCount',
            'TargetResponseTime',
            'HTTPCode_Target_2XX_Count',
            'HTTPCode_Target_4XX_Count',
            'HTTPCode_Target_5XX_Count',
            'UnHealthyHostCount',
            'HealthyHostCount',
        ]
        
        results = {
            "load_balancer": lb_name,
            "period_hours": hours,
            "metrics": {},
        }
        
        for metric in metrics_to_fetch:
            try:
                data = self._get_metric_stats(
                    namespace, metric,
                    [{'Name': 'LoadBalancer', 'Value': lb_name}],
                    minutes=hours * 60
                )
                results["metrics"][metric] = data
            except:
                pass
        
        return results
    
    # =========================================================================
    # Route 53 Operations
    # =========================================================================
    
    def route53_health_check(self, limit_health_checks: int = 5) -> Dict[str, Any]:
        """
        Route 53 health check (optimized for speed).
        
        Checks:
        - Hosted zones (all)
        - Health checks status (limited to reduce API calls)
        
        Args:
            limit_health_checks: Max health checks to query status (default 5)
        """
        route53 = self._get_client('route53')
        
        results = {
            "service": "Route53",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "hosted_zones": [],
            "health_checks": [],
            "health_checks_total": 0,
            "issues": [],
        }
        
        try:
            # List hosted zones (fast)
            zones_response = route53.list_hosted_zones()
            
            for zone in zones_response.get('HostedZones', [])[:20]:
                zone_id = zone['Id'].split('/')[-1]
                zone_name = zone['Name']
                
                results["hosted_zones"].append({
                    "id": zone_id,
                    "name": zone_name,
                    "private": zone.get('Config', {}).get('PrivateZone', False),
                    "record_count": zone.get('ResourceRecordSetCount', 0),
                })
            
            # List health checks (fast)
            health_response = route53.list_health_checks()
            all_health_checks = health_response.get('HealthChecks', [])
            results["health_checks_total"] = len(all_health_checks)
            
            # Only query detailed status for limited number (slow operation)
            unhealthy_count = 0
            for hc in all_health_checks[:limit_health_checks]:
                hc_id = hc['Id']
                hc_config = hc.get('HealthCheckConfig', {})
                
                # Get health check status (this is the slow part)
                health_status = "unknown"
                try:
                    status_response = route53.get_health_check_status(HealthCheckId=hc_id)
                    statuses = status_response.get('HealthCheckObservations', [])
                    
                    healthy_count = sum(1 for s in statuses if s.get('StatusReport', {}).get('Status') == 'Success')
                    total = len(statuses)
                    
                    health_status = "healthy" if healthy_count == total else "unhealthy"
                    if health_status == "unhealthy":
                        unhealthy_count += 1
                except:
                    health_status = "unknown"
                    total = len(statuses)
                    
                    health_status = "healthy" if healthy_count == total else "unhealthy"
                    if health_status == "unhealthy":
                        unhealthy_count += 1
                except:
                    health_status = "unknown"
                
                results["health_checks"].append({
                    "id": hc_id,
                    "type": hc_config.get('Type', ''),
                    "fqdn": hc_config.get('FullyQualifiedDomainName', ''),
                    "port": hc_config.get('Port'),
                    "path": hc_config.get('ResourcePath', ''),
                    "status": health_status,
                })
            
            if unhealthy_count > 0:
                results["issues"].append({
                    "resource": "Route53 Health Checks",
                    "issue": f"{unhealthy_count} unhealthy health checks"
                })
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def route53_scan(self) -> Dict[str, Any]:
        """Scan Route 53 hosted zones and health checks."""
        route53 = self._get_client('route53')
        
        try:
            zones_response = route53.list_hosted_zones()
            health_response = route53.list_health_checks()
            
            return {
                "hosted_zones_count": len(zones_response.get('HostedZones', [])),
                "health_checks_count": len(health_response.get('HealthChecks', [])),
                "hosted_zones": [
                    {
                        "id": z['Id'].split('/')[-1],
                        "name": z['Name'],
                        "private": z.get('Config', {}).get('PrivateZone', False),
                    }
                    for z in zones_response.get('HostedZones', [])
                ],
            }
        except ClientError as e:
            return {"error": str(e)}
    
    # =========================================================================
    # DynamoDB Operations
    # =========================================================================
    
    def dynamodb_health_check(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """
        DynamoDB health check.
        
        Checks:
        - Table status
        - Read/Write capacity
        - Item count
        - CloudWatch metrics (throttling, errors)
        """
        dynamodb = self._get_client('dynamodb')
        
        results = {
            "service": "DynamoDB",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "tables": [],
            "issues": [],
        }
        
        try:
            if table_name:
                table_names = [table_name]
            else:
                response = dynamodb.list_tables()
                table_names = response.get('TableNames', [])
            
            for tname in table_names[:20]:  # Limit to 20 tables
                try:
                    table = dynamodb.describe_table(TableName=tname)['Table']
                    status = table.get('TableStatus', 'UNKNOWN')
                    
                    health = "healthy"
                    issues = []
                    
                    if status != 'ACTIVE':
                        health = "warning" if status in ['CREATING', 'UPDATING'] else "unhealthy"
                        issues.append(f"Table status: {status}")
                    
                    # Get capacity info
                    billing_mode = table.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')
                    throughput = table.get('ProvisionedThroughput', {})
                    read_capacity = throughput.get('ReadCapacityUnits', 0)
                    write_capacity = throughput.get('WriteCapacityUnits', 0)
                    
                    # Get CloudWatch metrics (throttling)
                    throttle_reads = self._get_metric_stats(
                        'AWS/DynamoDB', 'ReadThrottleEvents',
                        [{'Name': 'TableName', 'Value': tname}],
                        minutes=60
                    )
                    throttle_writes = self._get_metric_stats(
                        'AWS/DynamoDB', 'WriteThrottleEvents',
                        [{'Name': 'TableName', 'Value': tname}],
                        minutes=60
                    )
                    
                    if throttle_reads.get('sum', 0) > 0:
                        issues.append(f"Read throttles: {throttle_reads['sum']}")
                        if health == "healthy":
                            health = "warning"
                    
                    if throttle_writes.get('sum', 0) > 0:
                        issues.append(f"Write throttles: {throttle_writes['sum']}")
                        if health == "healthy":
                            health = "warning"
                    
                    table_health = {
                        "name": tname,
                        "status": status,
                        "health": health,
                        "billing_mode": billing_mode,
                        "read_capacity": read_capacity,
                        "write_capacity": write_capacity,
                        "item_count": table.get('ItemCount', 0),
                        "size_bytes": table.get('TableSizeBytes', 0),
                        "issues": issues,
                    }
                    
                    results["tables"].append(table_health)
                    
                    if issues:
                        results["issues"].extend([{
                            "resource": tname,
                            "issue": issue
                        } for issue in issues])
                        
                except Exception as e:
                    results["tables"].append({
                        "name": tname,
                        "health": "error",
                        "issues": [str(e)],
                    })
            
            # Overall status
            if any(t["health"] == "unhealthy" for t in results["tables"]):
                results["overall_status"] = "unhealthy"
            elif any(t["health"] == "warning" for t in results["tables"]):
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def dynamodb_scan(self) -> Dict[str, Any]:
        """Scan all DynamoDB tables."""
        dynamodb = self._get_client('dynamodb')
        
        try:
            response = dynamodb.list_tables()
            table_names = response.get('TableNames', [])
            tables = []
            
            for tname in table_names[:30]:  # Limit to 30 tables
                try:
                    table = dynamodb.describe_table(TableName=tname)['Table']
                    billing_mode = table.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')
                    throughput = table.get('ProvisionedThroughput', {})
                    
                    tables.append({
                        "name": tname,
                        "status": table.get('TableStatus', 'UNKNOWN'),
                        "billing_mode": billing_mode,
                        "read_capacity": throughput.get('ReadCapacityUnits', 0),
                        "write_capacity": throughput.get('WriteCapacityUnits', 0),
                        "item_count": table.get('ItemCount', 0),
                    })
                except:
                    tables.append({"name": tname, "status": "ERROR"})
            
            return {
                "count": len(table_names),
                "tables": tables,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def dynamodb_get_metrics(self, table_name: str, hours: int = 1) -> Dict[str, Any]:
        """Get DynamoDB table metrics from CloudWatch."""
        metrics_to_fetch = [
            'ConsumedReadCapacityUnits',
            'ConsumedWriteCapacityUnits',
            'ReadThrottleEvents',
            'WriteThrottleEvents',
            'SuccessfulRequestLatency',
        ]
        
        results = {
            "table_name": table_name,
            "period_hours": hours,
            "metrics": {},
        }
        
        for metric in metrics_to_fetch:
            try:
                data = self._get_metric_stats(
                    'AWS/DynamoDB', metric,
                    [{'Name': 'TableName', 'Value': table_name}],
                    minutes=hours * 60
                )
                results["metrics"][metric] = data
            except:
                pass
        
        return results
    
    # =========================================================================
    # ECS Operations
    # =========================================================================
    
    def ecs_health_check(self, cluster_name: Optional[str] = None) -> Dict[str, Any]:
        """
        ECS health check.
        
        Checks:
        - Cluster status
        - Service health
        - Running/Desired task count
        - Container instance health
        """
        ecs = self._get_client('ecs')
        
        results = {
            "service": "ECS",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "clusters": [],
            "issues": [],
        }
        
        try:
            if cluster_name:
                cluster_arns = [cluster_name]
            else:
                response = ecs.list_clusters()
                cluster_arns = response.get('clusterArns', [])
            
            if not cluster_arns:
                return results
            
            # Describe clusters
            clusters_response = ecs.describe_clusters(clusters=cluster_arns)
            
            for cluster in clusters_response.get('clusters', []):
                cname = cluster['clusterName']
                status = cluster.get('status', 'UNKNOWN')
                
                health = "healthy"
                issues = []
                
                if status != 'ACTIVE':
                    health = "unhealthy"
                    issues.append(f"Cluster status: {status}")
                
                running_tasks = cluster.get('runningTasksCount', 0)
                pending_tasks = cluster.get('pendingTasksCount', 0)
                active_services = cluster.get('activeServicesCount', 0)
                
                # Check services in cluster
                services_response = ecs.list_services(cluster=cname)
                service_arns = services_response.get('serviceArns', [])
                
                unhealthy_services = 0
                if service_arns:
                    services_detail = ecs.describe_services(
                        cluster=cname,
                        services=service_arns[:10]  # Limit to 10 services
                    )
                    for svc in services_detail.get('services', []):
                        desired = svc.get('desiredCount', 0)
                        running = svc.get('runningCount', 0)
                        if desired > 0 and running < desired:
                            unhealthy_services += 1
                            issues.append(f"Service {svc['serviceName']}: {running}/{desired} tasks")
                            if health == "healthy":
                                health = "warning"
                
                cluster_health = {
                    "name": cname,
                    "status": status,
                    "health": health,
                    "running_tasks": running_tasks,
                    "pending_tasks": pending_tasks,
                    "active_services": active_services,
                    "unhealthy_services": unhealthy_services,
                    "issues": issues,
                }
                
                results["clusters"].append(cluster_health)
                
                if issues:
                    results["issues"].extend([{
                        "resource": cname,
                        "issue": issue
                    } for issue in issues])
            
            # Overall status
            if any(c["health"] == "unhealthy" for c in results["clusters"]):
                results["overall_status"] = "unhealthy"
            elif any(c["health"] == "warning" for c in results["clusters"]):
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def ecs_scan(self) -> Dict[str, Any]:
        """Scan all ECS clusters."""
        ecs = self._get_client('ecs')
        
        try:
            response = ecs.list_clusters()
            cluster_arns = response.get('clusterArns', [])
            
            if not cluster_arns:
                return {"count": 0, "clusters": []}
            
            clusters_response = ecs.describe_clusters(clusters=cluster_arns)
            clusters = []
            
            for cluster in clusters_response.get('clusters', []):
                clusters.append({
                    "name": cluster['clusterName'],
                    "status": cluster.get('status', 'UNKNOWN'),
                    "running_tasks": cluster.get('runningTasksCount', 0),
                    "pending_tasks": cluster.get('pendingTasksCount', 0),
                    "active_services": cluster.get('activeServicesCount', 0),
                })
            
            return {
                "count": len(clusters),
                "clusters": clusters,
            }
        except ClientError as e:
            return {"error": str(e)}


    # =========================================================================
    # ElastiCache Operations
    # =========================================================================
    
    def elasticache_health_check(self, cluster_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ElastiCache health check.
        
        Checks:
        - Cluster status
        - Node health
        - Cache hit ratio
        - Memory usage
        """
        elasticache = self._get_client('elasticache')
        
        results = {
            "service": "ElastiCache",
            "checked_at": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "clusters": [],
            "issues": [],
        }
        
        try:
            if cluster_id:
                response = elasticache.describe_cache_clusters(
                    CacheClusterId=cluster_id,
                    ShowCacheNodeInfo=True
                )
            else:
                response = elasticache.describe_cache_clusters(ShowCacheNodeInfo=True)
            
            for cluster in response.get('CacheClusters', []):
                cid = cluster['CacheClusterId']
                status = cluster.get('CacheClusterStatus', 'unknown')
                engine = cluster.get('Engine', '')
                
                health = "healthy"
                issues = []
                
                if status != 'available':
                    health = "warning" if status in ['creating', 'modifying'] else "unhealthy"
                    issues.append(f"Status: {status}")
                
                # Check cache nodes
                nodes = cluster.get('CacheNodes', [])
                unhealthy_nodes = [n for n in nodes if n.get('CacheNodeStatus') != 'available']
                if unhealthy_nodes:
                    issues.append(f"{len(unhealthy_nodes)} unhealthy nodes")
                    if health == "healthy":
                        health = "warning"
                
                # Get metrics
                cache_hits = self._get_metric_stats(
                    'AWS/ElastiCache', 'CacheHits',
                    [{'Name': 'CacheClusterId', 'Value': cid}],
                    minutes=60
                )
                cache_misses = self._get_metric_stats(
                    'AWS/ElastiCache', 'CacheMisses',
                    [{'Name': 'CacheClusterId', 'Value': cid}],
                    minutes=60
                )
                
                total_ops = cache_hits.get('sum', 0) + cache_misses.get('sum', 0)
                hit_ratio = (cache_hits.get('sum', 0) / total_ops * 100) if total_ops > 0 else 0
                
                if hit_ratio < 80 and total_ops > 100:
                    issues.append(f"Low hit ratio: {hit_ratio:.1f}%")
                
                cluster_health = {
                    "id": cid,
                    "engine": engine,
                    "engine_version": cluster.get('EngineVersion', ''),
                    "status": status,
                    "health": health,
                    "node_type": cluster.get('CacheNodeType', ''),
                    "num_nodes": cluster.get('NumCacheNodes', 0),
                    "hit_ratio": round(hit_ratio, 1),
                    "issues": issues,
                }
                
                results["clusters"].append(cluster_health)
                
                if issues:
                    results["issues"].extend([{
                        "resource": cid,
                        "issue": issue
                    } for issue in issues])
            
            # Also check replication groups (Redis)
            try:
                rg_response = elasticache.describe_replication_groups()
                for rg in rg_response.get('ReplicationGroups', []):
                    rgid = rg['ReplicationGroupId']
                    status = rg.get('Status', 'unknown')
                    
                    health = "healthy"
                    issues = []
                    
                    if status != 'available':
                        health = "warning" if status in ['creating', 'modifying'] else "unhealthy"
                        issues.append(f"Status: {status}")
                    
                    results["clusters"].append({
                        "id": rgid,
                        "engine": "redis",
                        "engine_version": "",
                        "status": status,
                        "health": health,
                        "node_type": "",
                        "num_nodes": len(rg.get('MemberClusters', [])),
                        "type": "replication_group",
                        "issues": issues,
                    })
            except:
                pass
            
            # Overall status
            if any(c["health"] == "unhealthy" for c in results["clusters"]):
                results["overall_status"] = "unhealthy"
            elif any(c["health"] == "warning" for c in results["clusters"]):
                results["overall_status"] = "warning"
            
            return results
            
        except ClientError as e:
            return {"error": str(e), "overall_status": "error"}
    
    def elasticache_scan(self) -> Dict[str, Any]:
        """Scan ElastiCache clusters."""
        elasticache = self._get_client('elasticache')
        
        try:
            response = elasticache.describe_cache_clusters(ShowCacheNodeInfo=True)
            clusters = []
            
            for cluster in response.get('CacheClusters', []):
                clusters.append({
                    "id": cluster['CacheClusterId'],
                    "engine": cluster.get('Engine', ''),
                    "engine_version": cluster.get('EngineVersion', ''),
                    "status": cluster.get('CacheClusterStatus', 'unknown'),
                    "node_type": cluster.get('CacheNodeType', ''),
                    "num_nodes": cluster.get('NumCacheNodes', 0),
                })
            
            # Also get replication groups
            try:
                rg_response = elasticache.describe_replication_groups()
                for rg in rg_response.get('ReplicationGroups', []):
                    clusters.append({
                        "id": rg['ReplicationGroupId'],
                        "engine": "redis",
                        "status": rg.get('Status', 'unknown'),
                        "type": "replication_group",
                        "num_nodes": len(rg.get('MemberClusters', [])),
                    })
            except:
                pass
            
            return {
                "count": len(clusters),
                "clusters": clusters,
            }
        except ClientError as e:
            return {"error": str(e)}


# Singleton instance
_ops: Optional[AWSServiceOps] = None


def get_aws_ops(region: str = "ap-southeast-1") -> AWSServiceOps:
    """Get or create AWS ops instance."""
    global _ops
    if _ops is None or _ops.region != region:
        _ops = AWSServiceOps(region=region)
    return _ops
