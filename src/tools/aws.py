"""
AgenticAIOps - AWS Tools

AWS SDK (boto3) wrappers for EKS and related services.
"""

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone


class AWSTools:
    """AWS operations toolkit for the agent."""
    
    def __init__(self, region: Optional[str] = None):
        """Initialize AWS clients."""
        self.region = region or boto3.Session().region_name or "us-east-1"
        
        try:
            self.eks = boto3.client("eks", region_name=self.region)
            self.ec2 = boto3.client("ec2", region_name=self.region)
            self.cloudwatch = boto3.client("cloudwatch", region_name=self.region)
            self.logs = boto3.client("logs", region_name=self.region)
        except NoCredentialsError:
            raise RuntimeError("AWS credentials not configured")
    
    def describe_cluster(self, cluster_name: str) -> Dict[str, Any]:
        """
        Get detailed information about an EKS cluster.
        
        Args:
            cluster_name: Name of the EKS cluster
        
        Returns:
            Cluster details including version, endpoint, and status
        """
        try:
            response = self.eks.describe_cluster(name=cluster_name)
            cluster = response["cluster"]
            
            return {
                "success": True,
                "cluster": {
                    "name": cluster["name"],
                    "arn": cluster["arn"],
                    "version": cluster["version"],
                    "status": cluster["status"],
                    "endpoint": cluster["endpoint"],
                    "role_arn": cluster["roleArn"],
                    "vpc_id": cluster["resourcesVpcConfig"]["vpcId"],
                    "subnets": cluster["resourcesVpcConfig"]["subnetIds"],
                    "security_groups": cluster["resourcesVpcConfig"]["securityGroupIds"],
                    "created_at": cluster["createdAt"].isoformat(),
                    "platform_version": cluster.get("platformVersion"),
                    "tags": cluster.get("tags", {})
                }
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e),
                "error_code": e.response["Error"]["Code"]
            }
    
    def list_clusters(self) -> Dict[str, Any]:
        """
        List all EKS clusters in the region.
        
        Returns:
            List of cluster names
        """
        try:
            clusters = []
            paginator = self.eks.get_paginator("list_clusters")
            
            for page in paginator.paginate():
                clusters.extend(page["clusters"])
            
            return {
                "success": True,
                "region": self.region,
                "count": len(clusters),
                "clusters": clusters
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def list_nodegroups(self, cluster_name: str) -> Dict[str, Any]:
        """
        List node groups for an EKS cluster.
        
        Args:
            cluster_name: Name of the EKS cluster
        
        Returns:
            List of node groups with details
        """
        try:
            # List node group names
            response = self.eks.list_nodegroups(clusterName=cluster_name)
            nodegroup_names = response["nodegroups"]
            
            # Get details for each node group
            nodegroups = []
            for ng_name in nodegroup_names:
                ng_response = self.eks.describe_nodegroup(
                    clusterName=cluster_name,
                    nodegroupName=ng_name
                )
                ng = ng_response["nodegroup"]
                
                nodegroups.append({
                    "name": ng["nodegroupName"],
                    "status": ng["status"],
                    "instance_types": ng.get("instanceTypes", []),
                    "scaling": {
                        "min": ng["scalingConfig"]["minSize"],
                        "max": ng["scalingConfig"]["maxSize"],
                        "desired": ng["scalingConfig"]["desiredSize"]
                    },
                    "ami_type": ng.get("amiType"),
                    "disk_size": ng.get("diskSize"),
                    "subnets": ng.get("subnets", []),
                    "health": ng.get("health", {}).get("issues", [])
                })
            
            return {
                "success": True,
                "cluster": cluster_name,
                "count": len(nodegroups),
                "nodegroups": nodegroups
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_node_health(self, cluster_name: str) -> Dict[str, Any]:
        """
        Get health status of EC2 nodes in an EKS cluster.
        
        Args:
            cluster_name: Name of the EKS cluster
        
        Returns:
            Node health information
        """
        try:
            # Get instances with the cluster tag
            response = self.ec2.describe_instances(
                Filters=[
                    {
                        "Name": f"tag:kubernetes.io/cluster/{cluster_name}",
                        "Values": ["owned", "shared"]
                    },
                    {
                        "Name": "instance-state-name",
                        "Values": ["pending", "running", "stopping", "stopped"]
                    }
                ]
            )
            
            nodes = []
            for reservation in response["Reservations"]:
                for instance in reservation["Instances"]:
                    # Get instance name from tags
                    name = None
                    for tag in instance.get("Tags", []):
                        if tag["Key"] == "Name":
                            name = tag["Value"]
                            break
                    
                    nodes.append({
                        "instance_id": instance["InstanceId"],
                        "name": name,
                        "type": instance["InstanceType"],
                        "state": instance["State"]["Name"],
                        "private_ip": instance.get("PrivateIpAddress"),
                        "availability_zone": instance["Placement"]["AvailabilityZone"],
                        "launch_time": instance["LaunchTime"].isoformat()
                    })
            
            # Get instance status checks
            if nodes:
                status_response = self.ec2.describe_instance_status(
                    InstanceIds=[n["instance_id"] for n in nodes]
                )
                
                status_map = {
                    s["InstanceId"]: {
                        "system_status": s["SystemStatus"]["Status"],
                        "instance_status": s["InstanceStatus"]["Status"]
                    }
                    for s in status_response.get("InstanceStatuses", [])
                }
                
                for node in nodes:
                    status = status_map.get(node["instance_id"], {})
                    node["system_status"] = status.get("system_status", "unknown")
                    node["instance_status"] = status.get("instance_status", "unknown")
            
            return {
                "success": True,
                "cluster": cluster_name,
                "count": len(nodes),
                "nodes": nodes
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_cloudwatch_metrics(
        self,
        cluster_name: str,
        metric_names: Optional[List[str]] = None,
        period_minutes: int = 60
    ) -> Dict[str, Any]:
        """
        Get CloudWatch metrics for an EKS cluster.
        
        Args:
            cluster_name: Name of the EKS cluster
            metric_names: List of metrics to fetch (default: common metrics)
            period_minutes: Time range to query
        
        Returns:
            Metrics data
        """
        if metric_names is None:
            metric_names = [
                "cluster_failed_node_count",
                "cluster_node_count"
            ]
        
        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(minutes=period_minutes)
            
            results = {}
            
            for metric_name in metric_names:
                response = self.cloudwatch.get_metric_statistics(
                    Namespace="AWS/EKS",
                    MetricName=metric_name,
                    Dimensions=[
                        {"Name": "ClusterName", "Value": cluster_name}
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=300,  # 5 minutes
                    Statistics=["Average", "Maximum", "Minimum"]
                )
                
                datapoints = sorted(
                    response.get("Datapoints", []),
                    key=lambda x: x["Timestamp"]
                )
                
                results[metric_name] = {
                    "datapoints": [
                        {
                            "timestamp": dp["Timestamp"].isoformat(),
                            "average": dp.get("Average"),
                            "maximum": dp.get("Maximum"),
                            "minimum": dp.get("Minimum")
                        }
                        for dp in datapoints
                    ],
                    "latest": datapoints[-1] if datapoints else None
                }
            
            return {
                "success": True,
                "cluster": cluster_name,
                "period_minutes": period_minutes,
                "metrics": results
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_container_insights_metrics(
        self,
        cluster_name: str,
        namespace: Optional[str] = None,
        period_minutes: int = 60
    ) -> Dict[str, Any]:
        """
        Get Container Insights metrics (requires Container Insights enabled).
        
        Args:
            cluster_name: Name of the EKS cluster
            namespace: Kubernetes namespace to filter
            period_minutes: Time range to query
        
        Returns:
            Container Insights metrics
        """
        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(minutes=period_minutes)
            
            dimensions = [
                {"Name": "ClusterName", "Value": cluster_name}
            ]
            
            if namespace:
                dimensions.append({"Name": "Namespace", "Value": namespace})
            
            # Common Container Insights metrics
            metrics_to_fetch = [
                ("pod_cpu_utilization", "ContainerInsights"),
                ("pod_memory_utilization", "ContainerInsights"),
                ("pod_network_rx_bytes", "ContainerInsights"),
                ("pod_network_tx_bytes", "ContainerInsights"),
                ("node_cpu_utilization", "ContainerInsights"),
                ("node_memory_utilization", "ContainerInsights")
            ]
            
            results = {}
            
            for metric_name, namespace_cw in metrics_to_fetch:
                try:
                    response = self.cloudwatch.get_metric_statistics(
                        Namespace=namespace_cw,
                        MetricName=metric_name,
                        Dimensions=dimensions,
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=300,
                        Statistics=["Average", "Maximum"]
                    )
                    
                    datapoints = sorted(
                        response.get("Datapoints", []),
                        key=lambda x: x["Timestamp"]
                    )
                    
                    if datapoints:
                        latest = datapoints[-1]
                        results[metric_name] = {
                            "latest_average": latest.get("Average"),
                            "latest_maximum": latest.get("Maximum"),
                            "timestamp": latest["Timestamp"].isoformat()
                        }
                except Exception:
                    # Metric might not exist if Container Insights not enabled
                    pass
            
            return {
                "success": True,
                "cluster": cluster_name,
                "container_insights_enabled": len(results) > 0,
                "metrics": results
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_cloudwatch_logs(
        self,
        log_group: str,
        filter_pattern: Optional[str] = None,
        start_time_minutes_ago: int = 60,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get logs from CloudWatch Logs.
        
        Args:
            log_group: CloudWatch log group name
            filter_pattern: Filter pattern for logs
            start_time_minutes_ago: How far back to search
            limit: Maximum number of log events
        
        Returns:
            Log events
        """
        try:
            end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
            start_time = int((datetime.now(timezone.utc) - timedelta(minutes=start_time_minutes_ago)).timestamp() * 1000)
            
            kwargs = {
                "logGroupName": log_group,
                "startTime": start_time,
                "endTime": end_time,
                "limit": limit
            }
            
            if filter_pattern:
                kwargs["filterPattern"] = filter_pattern
            
            response = self.logs.filter_log_events(**kwargs)
            
            events = [
                {
                    "timestamp": datetime.fromtimestamp(e["timestamp"] / 1000).isoformat(),
                    "message": e["message"],
                    "log_stream": e["logStreamName"]
                }
                for e in response.get("events", [])
            ]
            
            return {
                "success": True,
                "log_group": log_group,
                "count": len(events),
                "events": events
            }
        
        except ClientError as e:
            return {
                "success": False,
                "error": str(e)
            }


# Tool definitions for the LLM agent
AWS_TOOLS = [
    {
        "name": "describe_cluster",
        "description": "Get detailed information about an EKS cluster including version, endpoint, VPC config, and status.",
        "parameters": {
            "cluster_name": "Name of the EKS cluster (required)"
        }
    },
    {
        "name": "list_clusters",
        "description": "List all EKS clusters in the current AWS region.",
        "parameters": {}
    },
    {
        "name": "list_nodegroups",
        "description": "List node groups for an EKS cluster with scaling configuration and health status.",
        "parameters": {
            "cluster_name": "Name of the EKS cluster (required)"
        }
    },
    {
        "name": "get_node_health",
        "description": "Get health status of EC2 nodes running in an EKS cluster. Shows instance state and status checks.",
        "parameters": {
            "cluster_name": "Name of the EKS cluster (required)"
        }
    },
    {
        "name": "get_cloudwatch_metrics",
        "description": "Get CloudWatch metrics for an EKS cluster.",
        "parameters": {
            "cluster_name": "Name of the EKS cluster (required)",
            "metric_names": "List of metric names to fetch (optional)",
            "period_minutes": "Time range to query (default: 60)"
        }
    },
    {
        "name": "get_container_insights_metrics",
        "description": "Get Container Insights metrics like CPU, memory, network for pods and nodes. Requires Container Insights enabled.",
        "parameters": {
            "cluster_name": "Name of the EKS cluster (required)",
            "namespace": "Kubernetes namespace to filter (optional)",
            "period_minutes": "Time range to query (default: 60)"
        }
    },
    {
        "name": "get_cloudwatch_logs",
        "description": "Search and retrieve logs from CloudWatch Logs. Useful for application logs shipped to CloudWatch.",
        "parameters": {
            "log_group": "CloudWatch log group name (required)",
            "filter_pattern": "Filter pattern for logs (optional)",
            "start_time_minutes_ago": "How far back to search (default: 60)",
            "limit": "Maximum number of log events (default: 100)"
        }
    }
]
