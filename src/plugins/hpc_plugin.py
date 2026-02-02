"""
HPC Plugin - AWS ParallelCluster management
"""

import subprocess
import json
from typing import Dict, List, Any, Callable
from .base import PluginBase, PluginConfig, PluginStatus, PluginRegistry
import logging

logger = logging.getLogger(__name__)


class HPCPlugin(PluginBase):
    """Plugin for managing AWS ParallelCluster HPC clusters"""
    
    PLUGIN_TYPE = "hpc"
    PLUGIN_NAME = "AWS ParallelCluster"
    PLUGIN_DESCRIPTION = "Monitor and manage AWS ParallelCluster HPC workloads"
    PLUGIN_ICON = "🖧"
    
    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.regions = config.config.get("regions", ["ap-southeast-1"])
        self.clusters: List[Dict] = []
        self.head_node_ssh = config.config.get("head_node_ssh", {})  # SSH config for head nodes
    
    def initialize(self) -> bool:
        """Initialize HPC plugin"""
        try:
            self._discover_clusters()
            self.status = PluginStatus.ENABLED
            return True
        except Exception as e:
            logger.error(f"Failed to initialize HPC plugin: {e}")
            self.status = PluginStatus.ERROR
            return False
    
    def _discover_clusters(self):
        """Discover ParallelCluster clusters"""
        self.clusters = []
        
        for region in self.regions:
            try:
                # Try using pcluster CLI if available
                cmd = f"pcluster list-clusters --region {region} --output json 2>/dev/null"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    for cluster in data.get("clusters", []):
                        self.clusters.append({
                            "cluster_name": cluster.get("clusterName"),
                            "status": cluster.get("clusterStatus"),
                            "region": region,
                            "version": cluster.get("version"),
                        })
                else:
                    # Fallback: check CloudFormation stacks with parallelcluster tag
                    cmd = f"""aws cloudformation describe-stacks --region {region} --output json 2>/dev/null | \\
                        jq '.Stacks[] | select(.Tags[]? | select(.Key=="parallelcluster:version"))'"""
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0 and result.stdout.strip():
                        stacks = result.stdout.strip().split('\n')
                        for stack_json in stacks:
                            if stack_json:
                                try:
                                    stack = json.loads(stack_json)
                                    self.clusters.append({
                                        "cluster_name": stack.get("StackName"),
                                        "status": stack.get("StackStatus"),
                                        "region": region,
                                        "version": "unknown",
                                    })
                                except:
                                    pass
            except Exception as e:
                logger.warning(f"Failed to list HPC clusters in {region}: {e}")
    
    def health_check(self) -> Dict[str, Any]:
        """Check HPC plugin health"""
        active = sum(1 for c in self.clusters if c.get("status") in ["CREATE_COMPLETE", "UPDATE_COMPLETE"])
        return {
            "healthy": True,
            "total_clusters": len(self.clusters),
            "active_clusters": active
        }
    
    def get_tools(self) -> List[Callable]:
        """Return HPC-specific tools"""
        from strands import tool
        
        @tool
        def hpc_list_clusters(region: str = None) -> str:
            """List ParallelCluster HPC clusters.
            
            Args:
                region: Filter by region (optional)
            
            Returns:
                List of HPC clusters
            """
            self._discover_clusters()  # Refresh
            
            clusters = self.clusters
            if region:
                clusters = [c for c in clusters if c["region"] == region]
            
            if not clusters:
                return "No HPC clusters found"
            
            lines = ["ParallelCluster HPC Clusters:", "-" * 60]
            for c in clusters:
                lines.append(f"  • {c['cluster_name']}")
                lines.append(f"    Region: {c['region']} | Status: {c['status']} | Version: {c.get('version', 'N/A')}")
            
            return "\n".join(lines)
        
        @tool
        def hpc_get_cluster_info(cluster_name: str, region: str = "ap-southeast-1") -> str:
            """Get detailed HPC cluster information.
            
            Args:
                cluster_name: Name of the ParallelCluster
                region: AWS region
            
            Returns:
                Cluster details
            """
            try:
                cmd = f"pcluster describe-cluster --cluster-name {cluster_name} --region {region} --output json 2>/dev/null"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    lines = [f"HPC Cluster: {cluster_name}", "-" * 50]
                    lines.append(f"Status: {data.get('clusterStatus')}")
                    lines.append(f"Version: {data.get('version')}")
                    lines.append(f"Region: {data.get('region')}")
                    
                    # Scheduler info
                    scheduler = data.get("scheduler", {})
                    lines.append(f"Scheduler: {scheduler.get('type', 'slurm')}")
                    
                    # Compute fleet
                    compute = data.get("computeFleetStatus")
                    if compute:
                        lines.append(f"Compute Fleet: {compute}")
                    
                    # Head node
                    head = data.get("headNode", {})
                    if head:
                        lines.append(f"Head Node: {head.get('instanceType')} ({head.get('state')})")
                        lines.append(f"Head Node IP: {head.get('publicIpAddress') or head.get('privateIpAddress')}")
                    
                    return "\n".join(lines)
                
                # Fallback to CloudFormation
                cmd = f"aws cloudformation describe-stacks --stack-name {cluster_name} --region {region} --output json"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    stack = data.get("Stacks", [{}])[0]
                    lines = [f"HPC Cluster (via CloudFormation): {cluster_name}", "-" * 50]
                    lines.append(f"Status: {stack.get('StackStatus')}")
                    lines.append(f"Created: {str(stack.get('CreationTime', ''))[:19]}")
                    
                    # Get outputs
                    outputs = {o.get("OutputKey"): o.get("OutputValue") for o in stack.get("Outputs", [])}
                    if outputs:
                        lines.append("Outputs:")
                        for k, v in list(outputs.items())[:5]:
                            lines.append(f"  {k}: {v}")
                    
                    return "\n".join(lines)
                
                return f"Error: Could not get info for cluster {cluster_name}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def hpc_get_queue_status(cluster_name: str, head_node_ip: str = None) -> str:
            """Get Slurm queue status from HPC cluster.
            
            Args:
                cluster_name: Name of the ParallelCluster
                head_node_ip: IP address of head node (required for SSH)
            
            Returns:
                Slurm queue status
            """
            ssh_config = self.head_node_ssh.get(cluster_name, {})
            ip = head_node_ip or ssh_config.get("ip")
            user = ssh_config.get("user", "ec2-user")
            key = ssh_config.get("key_file")
            
            if not ip:
                return f"Error: Head node IP not configured for {cluster_name}. Please provide head_node_ip or configure in plugin settings."
            
            try:
                key_arg = f"-i {key}" if key else ""
                cmd = f"ssh -o StrictHostKeyChecking=no {key_arg} {user}@{ip} 'squeue -l' 2>/dev/null"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    return f"Slurm Queue Status ({cluster_name}):\n{result.stdout}"
                return f"Error connecting to head node: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def hpc_get_node_status(cluster_name: str, head_node_ip: str = None) -> str:
            """Get Slurm node status from HPC cluster.
            
            Args:
                cluster_name: Name of the ParallelCluster
                head_node_ip: IP address of head node
            
            Returns:
                Slurm node status
            """
            ssh_config = self.head_node_ssh.get(cluster_name, {})
            ip = head_node_ip or ssh_config.get("ip")
            user = ssh_config.get("user", "ec2-user")
            key = ssh_config.get("key_file")
            
            if not ip:
                return f"Error: Head node IP not configured for {cluster_name}"
            
            try:
                key_arg = f"-i {key}" if key else ""
                cmd = f"ssh -o StrictHostKeyChecking=no {key_arg} {user}@{ip} 'sinfo -N -l' 2>/dev/null"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    return f"Slurm Node Status ({cluster_name}):\n{result.stdout}"
                return f"Error connecting to head node: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def hpc_get_job_history(cluster_name: str, head_node_ip: str = None, days: int = 1) -> str:
            """Get Slurm job history from HPC cluster.
            
            Args:
                cluster_name: Name of the ParallelCluster
                head_node_ip: IP address of head node
                days: Number of days of history (default: 1)
            
            Returns:
                Job history
            """
            ssh_config = self.head_node_ssh.get(cluster_name, {})
            ip = head_node_ip or ssh_config.get("ip")
            user = ssh_config.get("user", "ec2-user")
            key = ssh_config.get("key_file")
            
            if not ip:
                return f"Error: Head node IP not configured for {cluster_name}"
            
            try:
                key_arg = f"-i {key}" if key else ""
                cmd = f"ssh -o StrictHostKeyChecking=no {key_arg} {user}@{ip} 'sacct -S $(date -d \"{days} days ago\" +%Y-%m-%d) --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS' 2>/dev/null"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    return f"Slurm Job History ({cluster_name}, last {days} day(s)):\n{result.stdout}"
                return f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        return [hpc_list_clusters, hpc_get_cluster_info, hpc_get_queue_status, hpc_get_node_status, hpc_get_job_history]
    
    def get_resources(self) -> List[Dict[str, Any]]:
        """Get list of HPC clusters"""
        return self.clusters
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get HPC status summary"""
        health = self.health_check()
        return {
            "plugin_type": self.PLUGIN_TYPE,
            "icon": self.PLUGIN_ICON,
            "name": self.PLUGIN_NAME,
            "total_clusters": health["total_clusters"],
            "active_clusters": health["active_clusters"],
            "clusters": self.clusters
        }


# Register the plugin
PluginRegistry.register_plugin_class(HPCPlugin)
