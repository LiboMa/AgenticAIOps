"""
AgenticAIOps - Kubernetes Tools

Wrapper functions for kubectl operations on EKS clusters.
"""

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from typing import Optional, List, Dict, Any
import json


class KubernetesTools:
    """Kubernetes operations toolkit for the agent."""
    
    def __init__(self, kubeconfig_path: Optional[str] = None):
        """Initialize Kubernetes client."""
        try:
            if kubeconfig_path:
                config.load_kube_config(config_file=kubeconfig_path)
            else:
                # Try in-cluster config first, fall back to kubeconfig
                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()
        except Exception as e:
            raise RuntimeError(f"Failed to load Kubernetes config: {e}")
        
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
    
    def get_pods(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List pods in a namespace with their status.
        
        Args:
            namespace: Kubernetes namespace (use "all" for all namespaces)
            label_selector: Filter by labels (e.g., "app=nginx")
            field_selector: Filter by fields (e.g., "status.phase=Running")
        
        Returns:
            Dictionary with pod information
        """
        try:
            if namespace == "all":
                pods = self.core_v1.list_pod_for_all_namespaces(
                    label_selector=label_selector,
                    field_selector=field_selector
                )
            else:
                pods = self.core_v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=label_selector,
                    field_selector=field_selector
                )
            
            result = []
            for pod in pods.items:
                container_statuses = []
                if pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        status_info = {
                            "name": cs.name,
                            "ready": cs.ready,
                            "restart_count": cs.restart_count,
                            "state": self._get_container_state(cs.state)
                        }
                        container_statuses.append(status_info)
                
                result.append({
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase,
                    "node": pod.spec.node_name,
                    "containers": container_statuses,
                    "conditions": self._get_pod_conditions(pod.status.conditions),
                    "created": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
                })
            
            return {
                "success": True,
                "count": len(result),
                "pods": result
            }
        
        except ApiException as e:
            return {
                "success": False,
                "error": f"Kubernetes API error: {e.reason}",
                "status_code": e.status
            }
    
    def get_pod_logs(
        self,
        pod_name: str,
        namespace: str = "default",
        container: Optional[str] = None,
        tail_lines: int = 100,
        previous: bool = False
    ) -> Dict[str, Any]:
        """
        Get logs from a pod.
        
        Args:
            pod_name: Name of the pod
            namespace: Kubernetes namespace
            container: Specific container (if pod has multiple)
            tail_lines: Number of lines from the end
            previous: Get logs from previous container instance
        
        Returns:
            Dictionary with log content
        """
        try:
            logs = self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
                previous=previous
            )
            
            return {
                "success": True,
                "pod": pod_name,
                "namespace": namespace,
                "container": container,
                "lines": tail_lines,
                "logs": logs
            }
        
        except ApiException as e:
            return {
                "success": False,
                "error": f"Failed to get logs: {e.reason}",
                "status_code": e.status
            }
    
    def describe_pod(self, pod_name: str, namespace: str = "default") -> Dict[str, Any]:
        """
        Get detailed information about a pod.
        
        Args:
            pod_name: Name of the pod
            namespace: Kubernetes namespace
        
        Returns:
            Detailed pod information
        """
        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            
            return {
                "success": True,
                "pod": {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "labels": pod.metadata.labels,
                    "annotations": pod.metadata.annotations,
                    "node": pod.spec.node_name,
                    "service_account": pod.spec.service_account_name,
                    "phase": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "host_ip": pod.status.host_ip,
                    "containers": self._get_container_specs(pod.spec.containers),
                    "conditions": self._get_pod_conditions(pod.status.conditions),
                    "events": self._get_pod_events(pod_name, namespace)
                }
            }
        
        except ApiException as e:
            return {
                "success": False,
                "error": f"Failed to describe pod: {e.reason}",
                "status_code": e.status
            }
    
    def get_events(
        self,
        namespace: str = "default",
        field_selector: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get cluster events.
        
        Args:
            namespace: Kubernetes namespace (use "all" for all namespaces)
            field_selector: Filter events (e.g., "involvedObject.name=my-pod")
            limit: Maximum number of events
        
        Returns:
            List of events
        """
        try:
            if namespace == "all":
                events = self.core_v1.list_event_for_all_namespaces(
                    field_selector=field_selector,
                    limit=limit
                )
            else:
                events = self.core_v1.list_namespaced_event(
                    namespace=namespace,
                    field_selector=field_selector,
                    limit=limit
                )
            
            result = []
            for event in events.items:
                result.append({
                    "type": event.type,
                    "reason": event.reason,
                    "message": event.message,
                    "object": f"{event.involved_object.kind}/{event.involved_object.name}",
                    "namespace": event.metadata.namespace,
                    "count": event.count,
                    "first_seen": event.first_timestamp.isoformat() if event.first_timestamp else None,
                    "last_seen": event.last_timestamp.isoformat() if event.last_timestamp else None
                })
            
            # Sort by last_seen descending
            result.sort(key=lambda x: x["last_seen"] or "", reverse=True)
            
            return {
                "success": True,
                "count": len(result),
                "events": result
            }
        
        except ApiException as e:
            return {
                "success": False,
                "error": f"Failed to get events: {e.reason}",
                "status_code": e.status
            }
    
    def get_deployments(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List deployments with their status.
        
        Args:
            namespace: Kubernetes namespace (use "all" for all namespaces)
            label_selector: Filter by labels
        
        Returns:
            List of deployments
        """
        try:
            if namespace == "all":
                deployments = self.apps_v1.list_deployment_for_all_namespaces(
                    label_selector=label_selector
                )
            else:
                deployments = self.apps_v1.list_namespaced_deployment(
                    namespace=namespace,
                    label_selector=label_selector
                )
            
            result = []
            for dep in deployments.items:
                result.append({
                    "name": dep.metadata.name,
                    "namespace": dep.metadata.namespace,
                    "replicas": {
                        "desired": dep.spec.replicas,
                        "ready": dep.status.ready_replicas or 0,
                        "available": dep.status.available_replicas or 0,
                        "updated": dep.status.updated_replicas or 0
                    },
                    "strategy": dep.spec.strategy.type,
                    "conditions": self._get_deployment_conditions(dep.status.conditions),
                    "created": dep.metadata.creation_timestamp.isoformat() if dep.metadata.creation_timestamp else None
                })
            
            return {
                "success": True,
                "count": len(result),
                "deployments": result
            }
        
        except ApiException as e:
            return {
                "success": False,
                "error": f"Failed to get deployments: {e.reason}",
                "status_code": e.status
            }
    
    def scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        Scale a deployment to specified replicas.
        
        Args:
            deployment_name: Name of the deployment
            replicas: Desired number of replicas
            namespace: Kubernetes namespace
        
        Returns:
            Result of scaling operation
        """
        try:
            # Get current deployment
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=namespace
            )
            
            old_replicas = deployment.spec.replicas
            
            # Patch the deployment
            body = {"spec": {"replicas": replicas}}
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=body
            )
            
            return {
                "success": True,
                "deployment": deployment_name,
                "namespace": namespace,
                "old_replicas": old_replicas,
                "new_replicas": replicas,
                "message": f"Scaled {deployment_name} from {old_replicas} to {replicas} replicas"
            }
        
        except ApiException as e:
            return {
                "success": False,
                "error": f"Failed to scale deployment: {e.reason}",
                "status_code": e.status
            }
    
    def restart_deployment(
        self,
        deployment_name: str,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        Perform a rolling restart of a deployment.
        
        Args:
            deployment_name: Name of the deployment
            namespace: Kubernetes namespace
        
        Returns:
            Result of restart operation
        """
        try:
            from datetime import datetime, timezone
            
            # Patch with annotation to trigger rolling restart
            now = datetime.now(timezone.utc).isoformat()
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": now
                            }
                        }
                    }
                }
            }
            
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=body
            )
            
            return {
                "success": True,
                "deployment": deployment_name,
                "namespace": namespace,
                "message": f"Initiated rolling restart for {deployment_name}",
                "restarted_at": now
            }
        
        except ApiException as e:
            return {
                "success": False,
                "error": f"Failed to restart deployment: {e.reason}",
                "status_code": e.status
            }
    
    def rollback_deployment(
        self,
        deployment_name: str,
        namespace: str = "default",
        revision: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Rollback a deployment to previous version.
        
        Note: In modern Kubernetes, rollback is done via kubectl rollout undo
        which effectively patches the deployment with the previous ReplicaSet spec.
        
        Args:
            deployment_name: Name of the deployment
            namespace: Kubernetes namespace
            revision: Specific revision to rollback to (default: previous)
        
        Returns:
            Result of rollback operation
        """
        try:
            # Get deployment's ReplicaSets to find previous version
            label_selector = f"app={deployment_name}"
            
            replicasets = self.apps_v1.list_namespaced_replica_set(
                namespace=namespace,
                label_selector=label_selector
            )
            
            if len(replicasets.items) < 2:
                return {
                    "success": False,
                    "error": "No previous revision found to rollback to"
                }
            
            # Sort by creation time to find previous
            sorted_rs = sorted(
                replicasets.items,
                key=lambda x: x.metadata.creation_timestamp,
                reverse=True
            )
            
            # The current one is the newest, get the previous
            previous_rs = sorted_rs[1]
            
            # Get the previous pod template spec
            previous_spec = previous_rs.spec.template.spec
            
            # Patch the deployment with previous spec
            body = {
                "spec": {
                    "template": {
                        "spec": previous_spec.to_dict()
                    }
                }
            }
            
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=body
            )
            
            return {
                "success": True,
                "deployment": deployment_name,
                "namespace": namespace,
                "message": f"Initiated rollback for {deployment_name}",
                "rolled_back_from": sorted_rs[0].metadata.name,
                "rolled_back_to": previous_rs.metadata.name
            }
        
        except ApiException as e:
            return {
                "success": False,
                "error": f"Failed to rollback deployment: {e.reason}",
                "status_code": e.status
            }
    
    # Helper methods
    
    def _get_container_state(self, state) -> Dict[str, Any]:
        """Extract container state information."""
        if state.running:
            return {"state": "running", "started_at": state.running.started_at.isoformat() if state.running.started_at else None}
        elif state.waiting:
            return {"state": "waiting", "reason": state.waiting.reason, "message": state.waiting.message}
        elif state.terminated:
            return {
                "state": "terminated",
                "reason": state.terminated.reason,
                "exit_code": state.terminated.exit_code,
                "message": state.terminated.message
            }
        return {"state": "unknown"}
    
    def _get_pod_conditions(self, conditions) -> List[Dict[str, Any]]:
        """Extract pod conditions."""
        if not conditions:
            return []
        return [
            {
                "type": c.type,
                "status": c.status,
                "reason": c.reason,
                "message": c.message,
                "last_transition": c.last_transition_time.isoformat() if c.last_transition_time else None
            }
            for c in conditions
        ]
    
    def _get_deployment_conditions(self, conditions) -> List[Dict[str, Any]]:
        """Extract deployment conditions."""
        if not conditions:
            return []
        return [
            {
                "type": c.type,
                "status": c.status,
                "reason": c.reason,
                "message": c.message
            }
            for c in conditions
        ]
    
    def _get_container_specs(self, containers) -> List[Dict[str, Any]]:
        """Extract container specifications."""
        result = []
        for c in containers:
            resources = {}
            if c.resources:
                if c.resources.requests:
                    resources["requests"] = dict(c.resources.requests)
                if c.resources.limits:
                    resources["limits"] = dict(c.resources.limits)
            
            result.append({
                "name": c.name,
                "image": c.image,
                "ports": [{"container_port": p.container_port, "protocol": p.protocol} for p in (c.ports or [])],
                "resources": resources,
                "env_count": len(c.env) if c.env else 0
            })
        return result
    
    def _get_pod_events(self, pod_name: str, namespace: str) -> List[Dict[str, Any]]:
        """Get events related to a specific pod."""
        result = self.get_events(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name}",
            limit=10
        )
        return result.get("events", []) if result.get("success") else []


# Tool definitions for the LLM agent
KUBERNETES_TOOLS = [
    {
        "name": "get_pods",
        "description": "List Kubernetes pods in a namespace with their status. Use this to see which pods are running, failing, or having issues.",
        "parameters": {
            "namespace": "Kubernetes namespace (default: 'default', use 'all' for all namespaces)",
            "label_selector": "Optional label filter (e.g., 'app=nginx')",
            "field_selector": "Optional field filter (e.g., 'status.phase=Running')"
        }
    },
    {
        "name": "get_pod_logs",
        "description": "Get logs from a specific pod. Use this to investigate errors, crashes, or application behavior.",
        "parameters": {
            "pod_name": "Name of the pod (required)",
            "namespace": "Kubernetes namespace (default: 'default')",
            "container": "Specific container name if pod has multiple",
            "tail_lines": "Number of lines to fetch (default: 100)",
            "previous": "Get logs from previous container instance (default: false)"
        }
    },
    {
        "name": "describe_pod",
        "description": "Get detailed information about a pod including its configuration, status, and recent events.",
        "parameters": {
            "pod_name": "Name of the pod (required)",
            "namespace": "Kubernetes namespace (default: 'default')"
        }
    },
    {
        "name": "get_events",
        "description": "Get Kubernetes cluster events. Events show what's happening in the cluster - pod scheduling, failures, scaling, etc.",
        "parameters": {
            "namespace": "Kubernetes namespace (default: 'default', use 'all' for all namespaces)",
            "field_selector": "Filter events (e.g., 'involvedObject.name=my-pod')",
            "limit": "Maximum number of events (default: 50)"
        }
    },
    {
        "name": "get_deployments",
        "description": "List deployments with their replica status. Shows desired vs actual replicas.",
        "parameters": {
            "namespace": "Kubernetes namespace (default: 'default', use 'all' for all namespaces)",
            "label_selector": "Optional label filter"
        }
    },
    {
        "name": "scale_deployment",
        "description": "Scale a deployment to a specified number of replicas. WRITE OPERATION - requires confirmation.",
        "parameters": {
            "deployment_name": "Name of the deployment (required)",
            "replicas": "Desired number of replicas (required)",
            "namespace": "Kubernetes namespace (default: 'default')"
        }
    },
    {
        "name": "restart_deployment",
        "description": "Perform a rolling restart of a deployment. WRITE OPERATION - requires confirmation.",
        "parameters": {
            "deployment_name": "Name of the deployment (required)",
            "namespace": "Kubernetes namespace (default: 'default')"
        }
    },
    {
        "name": "rollback_deployment",
        "description": "Rollback a deployment to its previous version. WRITE OPERATION - requires confirmation.",
        "parameters": {
            "deployment_name": "Name of the deployment (required)",
            "namespace": "Kubernetes namespace (default: 'default')",
            "revision": "Specific revision number (default: previous)"
        }
    }
]
