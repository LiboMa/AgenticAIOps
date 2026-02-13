"""
AWS Cloud Scanner - Full Resource Discovery

Provides APIs for:
- Account/Region selection
- Full cloud resource scanning
- CloudWatch Metrics/Logs integration
"""

import boto3
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Default region
DEFAULT_REGION = "ap-southeast-1"


class AWSCloudScanner:
    """
    AWS Cloud Scanner for full resource discovery and monitoring.
    
    Supports:
    - Multi-account (via Assume Role)
    - Multi-region scanning
    - CloudWatch Metrics/Logs
    """
    
    def __init__(self, region: str = DEFAULT_REGION, role_arn: Optional[str] = None):
        """
        Initialize scanner.
        
        Args:
            region: AWS region to scan
            role_arn: Optional IAM role ARN to assume
        """
        self.region = region
        self.role_arn = role_arn
        self._session = None
        self._credentials = None
        
    def _get_session(self) -> boto3.Session:
        """Get boto3 session, assuming role if configured."""
        if self._session:
            return self._session
            
        if self.role_arn:
            # Assume role
            sts = boto3.client('sts')
            try:
                response = sts.assume_role(
                    RoleArn=self.role_arn,
                    RoleSessionName='AgenticAIOpsScanner'
                )
                self._credentials = response['Credentials']
                self._session = boto3.Session(
                    aws_access_key_id=self._credentials['AccessKeyId'],
                    aws_secret_access_key=self._credentials['SecretAccessKey'],
                    aws_session_token=self._credentials['SessionToken'],
                    region_name=self.region
                )
            except ClientError as e:
                logger.error(f"Failed to assume role: {e}")
                self._session = boto3.Session(region_name=self.region)
        else:
            self._session = boto3.Session(region_name=self.region)
            
        return self._session
    
    def _get_client(self, service: str):
        """Get boto3 client for a service."""
        return self._get_session().client(service, region_name=self.region)
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get current AWS account information."""
        try:
            sts = self._get_client('sts')
            identity = sts.get_caller_identity()
            return {
                "account_id": identity['Account'],
                "arn": identity['Arn'],
                "user_id": identity['UserId'],
            }
        except ClientError as e:
            logger.error(f"Failed to get account info: {e}")
            return {"error": str(e)}
    
    def list_regions(self) -> List[Dict[str, str]]:
        """List available AWS regions."""
        try:
            ec2 = self._get_client('ec2')
            response = ec2.describe_regions()
            return [
                {"name": r['RegionName'], "endpoint": r['Endpoint']}
                for r in response['Regions']
            ]
        except ClientError as e:
            logger.error(f"Failed to list regions: {e}")
            return []
    
    def scan_all_resources(self) -> Dict[str, Any]:
        """
        Perform full cloud scan of all major services.
        
        Returns summary with resource counts and potential issues.
        """
        logger.info(f"Starting full cloud scan for region: {self.region}")
        
        results = {
            "region": self.region,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "account": self.get_account_info(),
            "services": {},
            "issues": [],
            "summary": {},
        }
        
        # Scan each service
        services = [
            ("ec2", self._scan_ec2),
            ("lambda", self._scan_lambda),
            ("s3", self._scan_s3),
            ("rds", self._scan_rds),
            ("iam", self._scan_iam),
            ("vpc", self._scan_vpc),
            ("elb", self._scan_elb),
            ("route53", self._scan_route53),
            ("dynamodb", self._scan_dynamodb),
            ("ecs", self._scan_ecs),
            ("elasticache", self._scan_elasticache),
            ("eks", self._scan_eks),
            ("cloudwatch", self._scan_cloudwatch_alarms),
        ]
        
        for service_name, scanner_func in services:
            try:
                results["services"][service_name] = scanner_func()
            except Exception as e:
                logger.error(f"Error scanning {service_name}: {e}")
                results["services"][service_name] = {"error": str(e)}
        
        # Generate summary
        results["summary"] = self._generate_summary(results["services"])
        
        return results
    
    def _scan_ec2(self) -> Dict[str, Any]:
        """Scan EC2 instances."""
        ec2 = self._get_client('ec2')
        
        try:
            response = ec2.describe_instances()
            instances = []
            status_counts = {"running": 0, "stopped": 0, "other": 0}
            
            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    state = instance['State']['Name']
                    if state == 'running':
                        status_counts['running'] += 1
                    elif state == 'stopped':
                        status_counts['stopped'] += 1
                    else:
                        status_counts['other'] += 1
                    
                    # Get instance name from tags
                    name = "unnamed"
                    for tag in instance.get('Tags', []):
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                            break
                    
                    instances.append({
                        "id": instance['InstanceId'],
                        "name": name,
                        "type": instance['InstanceType'],
                        "state": state,
                        "az": instance.get('Placement', {}).get('AvailabilityZone', ''),
                        "private_ip": instance.get('PrivateIpAddress', ''),
                        "public_ip": instance.get('PublicIpAddress', ''),
                        "launch_time": instance.get('LaunchTime', '').isoformat() if instance.get('LaunchTime') else '',
                    })
            
            return {
                "count": len(instances),
                "status": status_counts,
                "instances": instances,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _scan_lambda(self) -> Dict[str, Any]:
        """Scan Lambda functions."""
        lambda_client = self._get_client('lambda')
        
        try:
            response = lambda_client.list_functions()
            functions = []
            
            for func in response.get('Functions', []):
                functions.append({
                    "name": func['FunctionName'],
                    "runtime": func.get('Runtime', 'N/A'),
                    "memory": func.get('MemorySize', 0),
                    "timeout": func.get('Timeout', 0),
                    "last_modified": func.get('LastModified', ''),
                    "code_size": func.get('CodeSize', 0),
                })
            
            return {
                "count": len(functions),
                "functions": functions,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _scan_s3(self) -> Dict[str, Any]:
        """Scan S3 buckets."""
        s3 = self._get_client('s3')
        
        try:
            response = s3.list_buckets()
            buckets = []
            public_count = 0
            
            for bucket in response.get('Buckets', []):
                bucket_name = bucket['Name']
                
                # Check public access (simplified)
                is_public = False
                try:
                    acl = s3.get_bucket_acl(Bucket=bucket_name)
                    for grant in acl.get('Grants', []):
                        grantee = grant.get('Grantee', {})
                        if grantee.get('URI') == 'http://acs.amazonaws.com/groups/global/AllUsers':
                            is_public = True
                            public_count += 1
                            break
                except:
                    pass
                
                buckets.append({
                    "name": bucket_name,
                    "created": bucket.get('CreationDate', '').isoformat() if bucket.get('CreationDate') else '',
                    "public": is_public,
                })
            
            return {
                "count": len(buckets),
                "public_count": public_count,
                "buckets": buckets[:50],  # Limit for display
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _scan_rds(self) -> Dict[str, Any]:
        """Scan RDS instances."""
        rds = self._get_client('rds')
        
        try:
            response = rds.describe_db_instances()
            instances = []
            
            for db in response.get('DBInstances', []):
                instances.append({
                    "id": db['DBInstanceIdentifier'],
                    "engine": db['Engine'],
                    "version": db.get('EngineVersion', ''),
                    "class": db['DBInstanceClass'],
                    "status": db['DBInstanceStatus'],
                    "storage": db.get('AllocatedStorage', 0),
                    "multi_az": db.get('MultiAZ', False),
                    "public": db.get('PubliclyAccessible', False),
                })
            
            return {
                "count": len(instances),
                "instances": instances,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _scan_iam(self) -> Dict[str, Any]:
        """Scan IAM (basic security check)."""
        iam = self._get_client('iam')
        
        try:
            users = iam.list_users().get('Users', [])
            roles = iam.list_roles().get('Roles', [])
            
            # Check for MFA
            users_without_mfa = []
            for user in users[:10]:  # Limit for performance
                try:
                    mfa = iam.list_mfa_devices(UserName=user['UserName'])
                    if not mfa.get('MFADevices'):
                        users_without_mfa.append(user['UserName'])
                except:
                    pass
            
            return {
                "users_count": len(users),
                "roles_count": len(roles),
                "users_without_mfa": users_without_mfa,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _scan_vpc(self) -> Dict[str, Any]:
        """Scan VPCs."""
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
    
    def _scan_elb(self) -> Dict[str, Any]:
        """Scan Elastic Load Balancers (ALB/NLB)."""
        elbv2 = self._get_client('elbv2')
        
        try:
            response = elbv2.describe_load_balancers()
            lbs = []
            status_counts = {"active": 0, "provisioning": 0, "other": 0}
            
            for lb in response.get('LoadBalancers', []):
                state = lb['State']['Code']
                if state == 'active':
                    status_counts['active'] += 1
                elif state == 'provisioning':
                    status_counts['provisioning'] += 1
                else:
                    status_counts['other'] += 1
                
                lbs.append({
                    "name": lb['LoadBalancerName'],
                    "type": lb['Type'],
                    "scheme": lb.get('Scheme', ''),
                    "state": state,
                    "dns_name": lb.get('DNSName', ''),
                    "vpc_id": lb.get('VpcId', ''),
                })
            
            return {
                "count": len(lbs),
                "status": status_counts,
                "load_balancers": lbs,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _scan_route53(self) -> Dict[str, Any]:
        """Scan Route 53 hosted zones."""
        route53 = self._get_client('route53')
        
        try:
            zones_response = route53.list_hosted_zones()
            health_response = route53.list_health_checks()
            
            zones = [
                {
                    "id": z['Id'].split('/')[-1],
                    "name": z['Name'],
                    "private": z.get('Config', {}).get('PrivateZone', False),
                    "record_count": z.get('ResourceRecordSetCount', 0),
                }
                for z in zones_response.get('HostedZones', [])
            ]
            
            return {
                "count": len(zones),
                "health_checks_count": len(health_response.get('HealthChecks', [])),
                "hosted_zones": zones,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _scan_dynamodb(self) -> Dict[str, Any]:
        """Scan DynamoDB tables."""
        dynamodb = self._get_client('dynamodb')
        
        try:
            response = dynamodb.list_tables()
            table_names = response.get('TableNames', [])
            tables = []
            
            for tname in table_names[:30]:
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
    
    def _scan_ecs(self) -> Dict[str, Any]:
        """Scan ECS clusters."""
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
    
    def _scan_elasticache(self) -> Dict[str, Any]:
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
    
    def _scan_eks(self) -> Dict[str, Any]:
        """Scan EKS clusters."""
        eks = self._get_client('eks')
        
        try:
            response = eks.list_clusters()
            clusters = []
            
            for cluster_name in response.get('clusters', []):
                try:
                    detail = eks.describe_cluster(name=cluster_name)['cluster']
                    clusters.append({
                        "name": cluster_name,
                        "version": detail.get('version', ''),
                        "status": detail.get('status', ''),
                        "endpoint": detail.get('endpoint', ''),
                    })
                except:
                    clusters.append({"name": cluster_name})
            
            return {
                "count": len(clusters),
                "clusters": clusters,
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _scan_cloudwatch_alarms(self) -> Dict[str, Any]:
        """Scan CloudWatch alarms."""
        cw = self._get_client('cloudwatch')
        
        try:
            response = cw.describe_alarms()
            alarms = []
            alarm_state = {"OK": 0, "ALARM": 0, "INSUFFICIENT_DATA": 0}
            
            for alarm in response.get('MetricAlarms', []):
                state = alarm.get('StateValue', 'UNKNOWN')
                if state in alarm_state:
                    alarm_state[state] += 1
                
                alarms.append({
                    "name": alarm['AlarmName'],
                    "state": state,
                    "metric": alarm.get('MetricName', ''),
                    "namespace": alarm.get('Namespace', ''),
                })
            
            return {
                "count": len(alarms),
                "by_state": alarm_state,
                "alarms": alarms[:20],  # Limit for display
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def _generate_summary(self, services: Dict[str, Any]) -> Dict[str, Any]:
        """Generate scan summary."""
        summary = {
            "total_resources": 0,
            "issues_found": [],
        }
        
        # Count resources
        for service, data in services.items():
            if "count" in data:
                summary["total_resources"] += data["count"]
        
        # Check for issues
        ec2 = services.get("ec2", {})
        if ec2.get("status", {}).get("stopped", 0) > 0:
            summary["issues_found"].append({
                "service": "ec2",
                "type": "stopped_instances",
                "count": ec2["status"]["stopped"],
                "severity": "low",
            })
        
        s3 = services.get("s3", {})
        if s3.get("public_count", 0) > 0:
            summary["issues_found"].append({
                "service": "s3",
                "type": "public_buckets",
                "count": s3["public_count"],
                "severity": "high",
            })
        
        iam = services.get("iam", {})
        if len(iam.get("users_without_mfa", [])) > 0:
            summary["issues_found"].append({
                "service": "iam",
                "type": "users_without_mfa",
                "count": len(iam["users_without_mfa"]),
                "severity": "critical",
            })
        
        cw = services.get("cloudwatch", {})
        if cw.get("by_state", {}).get("ALARM", 0) > 0:
            summary["issues_found"].append({
                "service": "cloudwatch",
                "type": "active_alarms",
                "count": cw["by_state"]["ALARM"],
                "severity": "high",
            })
        
        return summary
    
    # CloudWatch Metrics Methods
    
    def get_cloudwatch_metrics(
        self,
        namespace: str,
        metric_name: str,
        dimensions: List[Dict[str, str]],
        period: int = 300,
        hours: int = 1
    ) -> Dict[str, Any]:
        """Get CloudWatch metrics for a resource."""
        cw = self._get_client('cloudwatch')
        
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)
        
        try:
            response = cw.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Average', 'Maximum', 'Minimum'],
            )
            
            datapoints = sorted(
                response.get('Datapoints', []),
                key=lambda x: x['Timestamp']
            )
            
            return {
                "namespace": namespace,
                "metric": metric_name,
                "dimensions": dimensions,
                "datapoints": [
                    {
                        "timestamp": dp['Timestamp'].isoformat(),
                        "average": dp.get('Average'),
                        "maximum": dp.get('Maximum'),
                        "minimum": dp.get('Minimum'),
                    }
                    for dp in datapoints
                ],
            }
        except ClientError as e:
            return {"error": str(e)}
    
    def get_ec2_metrics(self, instance_id: str, metric_name: str = "CPUUtilization", hours: int = 1) -> Dict[str, Any]:
        """Get EC2 instance metrics."""
        return self.get_cloudwatch_metrics(
            namespace="AWS/EC2",
            metric_name=metric_name,
            dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            hours=hours,
        )
    
    def get_rds_metrics(self, db_id: str, metric_name: str = "CPUUtilization", hours: int = 1) -> Dict[str, Any]:
        """Get RDS instance metrics."""
        return self.get_cloudwatch_metrics(
            namespace="AWS/RDS",
            metric_name=metric_name,
            dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
            hours=hours,
        )
    
    def get_lambda_metrics(self, function_name: str, metric_name: str = "Duration", hours: int = 1) -> Dict[str, Any]:
        """Get Lambda function metrics."""
        return self.get_cloudwatch_metrics(
            namespace="AWS/Lambda",
            metric_name=metric_name,
            dimensions=[{"Name": "FunctionName", "Value": function_name}],
            hours=hours,
        )
    
    # CloudWatch Logs Methods
    
    def get_cloudwatch_logs(
        self,
        log_group: str,
        filter_pattern: str = "",
        limit: int = 100,
        hours: int = 1
    ) -> Dict[str, Any]:
        """Get CloudWatch logs."""
        logs = self._get_client('logs')
        
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = end_time - (hours * 3600 * 1000)
        
        try:
            response = logs.filter_log_events(
                logGroupName=log_group,
                startTime=start_time,
                endTime=end_time,
                filterPattern=filter_pattern,
                limit=limit,
            )
            
            return {
                "log_group": log_group,
                "filter_pattern": filter_pattern,
                "events": [
                    {
                        "timestamp": datetime.fromtimestamp(e['timestamp'] / 1000).isoformat(),
                        "message": e['message'],
                    }
                    for e in response.get('events', [])
                ],
            }
        except ClientError as e:
            return {"error": str(e)}


# Singleton instance
_scanner: Optional[AWSCloudScanner] = None


def get_scanner(region: str = DEFAULT_REGION, role_arn: Optional[str] = None) -> AWSCloudScanner:
    """Get or create scanner instance."""
    global _scanner
    if _scanner is None or _scanner.region != region:
        _scanner = AWSCloudScanner(region=region, role_arn=role_arn)
    return _scanner
