"""
EKS Plugin - Multi-cluster Kubernetes support
"""

import subprocess
import json
import os
from typing import Dict, List, Any, Callable, Optional
from .base import PluginBase, PluginConfig, PluginStatus, PluginRegistry, ClusterConfig
import logging

logger = logging.getLogger(__name__)


class EKSPlugin(PluginBase):
    """Plugin for managing EKS clusters"""
    
    PLUGIN_TYPE = "eks"
    PLUGIN_NAME = "Amazon EKS"
    PLUGIN_DESCRIPTION = "Manage and monitor Amazon EKS Kubernetes clusters"
    PLUGIN_ICON = "☸️"
    
    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.clusters: List[ClusterConfig] = []
        self.kubeconfig_path = config.config.get("kubeconfig_path", os.path.expanduser("~/.kube/config"))
        self._current_context: Optional[str] = None
    
    def initialize(self) -> bool:
        """Initialize EKS plugin and discover clusters"""
        try:
            # Discover EKS clusters from AWS
            self._discover_clusters()
            self.status = PluginStatus.ENABLED
            return True
        except Exception as e:
            logger.error(f"Failed to initialize EKS plugin: {e}")
            self.status = PluginStatus.ERROR
            return False
    
    def _discover_clusters(self):
        """Discover EKS clusters from configured regions"""
        regions = self.config.config.get("regions", ["ap-southeast-1"])
        
        for region in regions:
            try:
                result = subprocess.run(
                    ["aws", "eks", "list-clusters", "--region", region, "--output", "json"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    for cluster_name in data.get("clusters", []):
                        cluster_id = f"eks-{region}-{cluster_name}"
                        cluster = ClusterConfig(
                            cluster_id=cluster_id,
                            name=cluster_name,
                            region=region,
                            plugin_type="eks",
                            config={"cluster_name": cluster_name}
                        )
                        self.clusters.append(cluster)
                        PluginRegistry.add_cluster(cluster)
            except Exception as e:
                logger.warning(f"Failed to list clusters in {region}: {e}")
    
    def health_check(self) -> Dict[str, Any]:
        """Check EKS plugin health"""
        healthy_clusters = 0
        cluster_status = []
        
        for cluster in self.clusters:
            try:
                result = subprocess.run(
                    ["kubectl", "cluster-info", "--context", f"arn:aws:eks:{cluster.region}:533267047935:cluster/{cluster.name}"],
                    capture_output=True, text=True, timeout=10
                )
                is_healthy = result.returncode == 0
                if is_healthy:
                    healthy_clusters += 1
                cluster_status.append({
                    "cluster_id": cluster.cluster_id,
                    "name": cluster.name,
                    "healthy": is_healthy
                })
            except:
                cluster_status.append({
                    "cluster_id": cluster.cluster_id,
                    "name": cluster.name,
                    "healthy": False
                })
        
        return {
            "healthy": healthy_clusters == len(self.clusters),
            "total_clusters": len(self.clusters),
            "healthy_clusters": healthy_clusters,
            "clusters": cluster_status
        }
    
    def get_tools(self) -> List[Callable]:
        """Return EKS-specific tools"""
        from strands import tool
        
        @tool
        def eks_get_pods(cluster_id: str = None, namespace: str = "default") -> str:
            """Get pods from an EKS cluster.
            
            Args:
                cluster_id: The cluster ID to query. If not specified, uses active cluster.
                namespace: Kubernetes namespace (default: 'default', use 'all' for all namespaces)
            
            Returns:
                Pod information in text format
            """
            cluster = self._get_target_cluster(cluster_id)
            if not cluster:
                return "Error: No cluster specified and no active cluster set"
            
            ns_flag = "-A" if namespace == "all" else f"-n {namespace}"
            cmd = f"kubectl get pods {ns_flag} --context arn:aws:eks:{cluster.region}:533267047935:cluster/{cluster.name} -o wide"
            
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def eks_get_nodes(cluster_id: str = None) -> str:
            """Get nodes from an EKS cluster.
            
            Args:
                cluster_id: The cluster ID to query. If not specified, uses active cluster.
            
            Returns:
                Node information in text format
            """
            cluster = self._get_target_cluster(cluster_id)
            if not cluster:
                return "Error: No cluster specified and no active cluster set"
            
            cmd = f"kubectl get nodes --context arn:aws:eks:{cluster.region}:533267047935:cluster/{cluster.name} -o wide"
            
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def eks_describe_pod(pod_name: str, cluster_id: str = None, namespace: str = "default") -> str:
            """Describe a pod in an EKS cluster.
            
            Args:
                pod_name: Name of the pod
                cluster_id: The cluster ID. If not specified, uses active cluster.
                namespace: Kubernetes namespace
            
            Returns:
                Pod description
            """
            cluster = self._get_target_cluster(cluster_id)
            if not cluster:
                return "Error: No cluster specified and no active cluster set"
            
            cmd = f"kubectl describe pod {pod_name} -n {namespace} --context arn:aws:eks:{cluster.region}:533267047935:cluster/{cluster.name}"
            
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def eks_get_logs(pod_name: str, cluster_id: str = None, namespace: str = "default", tail: int = 100) -> str:
            """Get logs from a pod in an EKS cluster.
            
            Args:
                pod_name: Name of the pod
                cluster_id: The cluster ID. If not specified, uses active cluster.
                namespace: Kubernetes namespace
                tail: Number of lines to show
            
            Returns:
                Pod logs
            """
            cluster = self._get_target_cluster(cluster_id)
            if not cluster:
                return "Error: No cluster specified and no active cluster set"
            
            cmd = f"kubectl logs {pod_name} -n {namespace} --tail={tail} --context arn:aws:eks:{cluster.region}:533267047935:cluster/{cluster.name}"
            
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def eks_list_clusters() -> str:
            """List all configured EKS clusters.
            
            Returns:
                List of clusters with their status
            """
            if not self.clusters:
                return "No EKS clusters configured"
            
            lines = ["EKS Clusters:", "-" * 60]
            active = PluginRegistry.get_active_cluster()
            
            for c in self.clusters:
                marker = " [ACTIVE]" if active and active.cluster_id == c.cluster_id else ""
                lines.append(f"  • {c.name} ({c.region}){marker}")
                lines.append(f"    ID: {c.cluster_id}")
            
            return "\n".join(lines)
        
        @tool
        def eks_switch_cluster(cluster_id: str) -> str:
            """Switch to a different EKS cluster.
            
            Args:
                cluster_id: The cluster ID to switch to
            
            Returns:
                Confirmation message
            """
            if PluginRegistry.set_active_cluster(cluster_id):
                cluster = PluginRegistry.get_cluster(cluster_id)
                return f"Switched to cluster: {cluster.name} ({cluster.region})"
            return f"Error: Cluster {cluster_id} not found"
        
        return [eks_get_pods, eks_get_nodes, eks_describe_pod, eks_get_logs, eks_list_clusters, eks_switch_cluster]
    
    def _get_target_cluster(self, cluster_id: Optional[str]) -> Optional[ClusterConfig]:
        """Get target cluster - specified or active"""
        if cluster_id:
            return PluginRegistry.get_cluster(cluster_id)
        return PluginRegistry.get_active_cluster()
    
    def get_resources(self) -> List[Dict[str, Any]]:
        """Get list of EKS clusters"""
        return [c.to_dict() for c in self.clusters]
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get EKS status summary for dashboard"""
        health = self.health_check()
        return {
            "plugin_type": self.PLUGIN_TYPE,
            "icon": self.PLUGIN_ICON,
            "name": self.PLUGIN_NAME,
            "total_clusters": len(self.clusters),
            "healthy_clusters": health.get("healthy_clusters", 0),
            "clusters": [
                {
                    "id": c.cluster_id,
                    "name": c.name,
                    "region": c.region,
                    "status": "healthy"  # Simplified
                }
                for c in self.clusters
            ]
        }


# Register the plugin
PluginRegistry.register_plugin_class(EKSPlugin)
