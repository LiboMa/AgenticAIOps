#!/usr/bin/env python3
"""
AgenticAIOps - Strands Agent with K8s Tools

Extended version with kubectl-equivalent tools for Pod-level operations.
"""

import boto3
from kubernetes import client, config
from strands import Agent, tool
from strands.models import BedrockModel
from typing import Dict, Any, List, Optional
from datetime import datetime


# Configuration
CLUSTER_NAME = "testing-cluster"
REGION = "ap-southeast-1"

# Initialize clients
eks_client = boto3.client('eks', region_name=REGION)

# Load kubernetes config
try:
    config.load_kube_config()
    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    K8S_AVAILABLE = True
except Exception as e:
    print(f"Warning: K8s config not loaded: {e}")
    K8S_AVAILABLE = False
    v1 = None
    apps_v1 = None


# ============================================
# EKS API Tools (boto3)
# ============================================

@tool
def get_cluster_health(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Check the health status of an EKS cluster.
    
    Use this tool when users ask about cluster health, status, or overall condition.
    """
    cluster = eks_client.describe_cluster(name=cluster_name)['cluster']
    compute = cluster.get('computeConfig', {})
    
    return {
        "success": True,
        "cluster": cluster_name,
        "status": cluster['status'],
        "version": cluster['version'],
        "healthy": cluster['status'] == 'ACTIVE',
        "computeMode": "EKS Auto Mode" if compute.get('enabled') else "Standard"
    }


@tool
def get_cluster_info(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Get basic information about an EKS cluster."""
    cluster = eks_client.describe_cluster(name=cluster_name)['cluster']
    
    return {
        "success": True,
        "name": cluster['name'],
        "version": cluster['version'],
        "status": cluster['status'],
        "platformVersion": cluster.get('platformVersion'),
        "endpoint": cluster['endpoint'][:50] + "..."
    }


# ============================================
# Kubernetes API Tools (kubectl equivalent)
# ============================================

@tool
def get_pods(namespace: str = "default", all_namespaces: bool = False) -> Dict[str, Any]:
    """List pods in a namespace or across all namespaces.
    
    Use this when users ask about pods, workloads, or container status.
    
    Args:
        namespace: Kubernetes namespace (default: "default")
        all_namespaces: If true, list pods across all namespaces
    """
    if not K8S_AVAILABLE:
        return {"success": False, "error": "Kubernetes API not available"}
    
    try:
        if all_namespaces:
            pods = v1.list_pod_for_all_namespaces()
        else:
            pods = v1.list_namespaced_pod(namespace)
        
        pod_list = []
        for pod in pods.items:
            # Get container statuses
            container_statuses = []
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    status = {
                        "name": cs.name,
                        "ready": cs.ready,
                        "restartCount": cs.restart_count
                    }
                    if cs.state.waiting:
                        status["state"] = "Waiting"
                        status["reason"] = cs.state.waiting.reason
                    elif cs.state.running:
                        status["state"] = "Running"
                    elif cs.state.terminated:
                        status["state"] = "Terminated"
                        status["reason"] = cs.state.terminated.reason
                    container_statuses.append(status)
            
            pod_list.append({
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "containers": container_statuses,
                "nodeName": pod.spec.node_name,
                "createdAt": str(pod.metadata.creation_timestamp)
            })
        
        return {
            "success": True,
            "count": len(pod_list),
            "pods": pod_list
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_pod_logs(pod_name: str, namespace: str = "default", tail_lines: int = 50) -> Dict[str, Any]:
    """Get logs from a specific pod.
    
    Use this when users want to see container logs for debugging.
    
    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace
        tail_lines: Number of log lines to retrieve (default: 50)
    """
    if not K8S_AVAILABLE:
        return {"success": False, "error": "Kubernetes API not available"}
    
    try:
        logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=tail_lines
        )
        
        return {
            "success": True,
            "pod": pod_name,
            "namespace": namespace,
            "tailLines": tail_lines,
            "logs": logs
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def describe_pod(pod_name: str, namespace: str = "default") -> Dict[str, Any]:
    """Get detailed information about a specific pod.
    
    Use this when users want to investigate a specific pod's configuration,
    events, or troubleshoot issues.
    
    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace
    """
    if not K8S_AVAILABLE:
        return {"success": False, "error": "Kubernetes API not available"}
    
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        # Get events for this pod
        events = v1.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name}"
        )
        
        event_list = []
        for event in events.items[-10:]:  # Last 10 events
            event_list.append({
                "type": event.type,
                "reason": event.reason,
                "message": event.message,
                "count": event.count,
                "lastTimestamp": str(event.last_timestamp)
            })
        
        return {
            "success": True,
            "pod": {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "hostIP": pod.status.host_ip,
                "podIP": pod.status.pod_ip,
                "nodeName": pod.spec.node_name,
                "containers": [c.name for c in pod.spec.containers],
                "conditions": [
                    {"type": c.type, "status": c.status}
                    for c in (pod.status.conditions or [])
                ]
            },
            "events": event_list
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_deployments(namespace: str = "default", all_namespaces: bool = False) -> Dict[str, Any]:
    """List deployments in a namespace.
    
    Use this when users ask about deployments, applications, or workload status.
    """
    if not K8S_AVAILABLE:
        return {"success": False, "error": "Kubernetes API not available"}
    
    try:
        if all_namespaces:
            deployments = apps_v1.list_deployment_for_all_namespaces()
        else:
            deployments = apps_v1.list_namespaced_deployment(namespace)
        
        dep_list = []
        for dep in deployments.items:
            dep_list.append({
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas": dep.spec.replicas,
                "readyReplicas": dep.status.ready_replicas or 0,
                "availableReplicas": dep.status.available_replicas or 0,
                "updatedReplicas": dep.status.updated_replicas or 0
            })
        
        return {
            "success": True,
            "count": len(dep_list),
            "deployments": dep_list
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_events(namespace: str = "default", all_namespaces: bool = False) -> Dict[str, Any]:
    """Get Kubernetes events to help diagnose issues.
    
    Use this when investigating cluster problems or recent changes.
    """
    if not K8S_AVAILABLE:
        return {"success": False, "error": "Kubernetes API not available"}
    
    try:
        if all_namespaces:
            events = v1.list_event_for_all_namespaces()
        else:
            events = v1.list_namespaced_event(namespace)
        
        # Get recent events (last 20)
        event_list = []
        for event in sorted(events.items, key=lambda x: x.last_timestamp or x.event_time or datetime.min, reverse=True)[:20]:
            event_list.append({
                "type": event.type,
                "reason": event.reason,
                "message": event.message[:200] if event.message else "",
                "object": f"{event.involved_object.kind}/{event.involved_object.name}",
                "namespace": event.metadata.namespace,
                "count": event.count,
                "lastTimestamp": str(event.last_timestamp)
            })
        
        return {
            "success": True,
            "count": len(event_list),
            "events": event_list
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_nodes() -> Dict[str, Any]:
    """Get information about cluster nodes.
    
    Use this when users ask about node health, capacity, or resources.
    """
    if not K8S_AVAILABLE:
        return {"success": False, "error": "Kubernetes API not available"}
    
    try:
        nodes = v1.list_node()
        
        node_list = []
        for node in nodes.items:
            conditions = {c.type: c.status for c in node.status.conditions}
            
            node_list.append({
                "name": node.metadata.name,
                "ready": conditions.get("Ready") == "True",
                "kubeletVersion": node.status.node_info.kubelet_version,
                "osImage": node.status.node_info.os_image,
                "capacity": {
                    "cpu": node.status.capacity.get("cpu"),
                    "memory": node.status.capacity.get("memory"),
                    "pods": node.status.capacity.get("pods")
                }
            })
        
        return {
            "success": True,
            "count": len(node_list),
            "nodes": node_list
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_hpa(namespace: str = "default", all_namespaces: bool = False) -> Dict[str, Any]:
    """Get Horizontal Pod Autoscaler status.
    
    Use this when users ask about autoscaling configuration or status.
    """
    if not K8S_AVAILABLE:
        return {"success": False, "error": "Kubernetes API not available"}
    
    try:
        autoscaling_v2 = client.AutoscalingV2Api()
        
        if all_namespaces:
            hpas = autoscaling_v2.list_horizontal_pod_autoscaler_for_all_namespaces()
        else:
            hpas = autoscaling_v2.list_namespaced_horizontal_pod_autoscaler(namespace)
        
        hpa_list = []
        for hpa in hpas.items:
            hpa_list.append({
                "name": hpa.metadata.name,
                "namespace": hpa.metadata.namespace,
                "target": f"{hpa.spec.scale_target_ref.kind}/{hpa.spec.scale_target_ref.name}",
                "minReplicas": hpa.spec.min_replicas,
                "maxReplicas": hpa.spec.max_replicas,
                "currentReplicas": hpa.status.current_replicas,
                "desiredReplicas": hpa.status.desired_replicas
            })
        
        return {
            "success": True,
            "count": len(hpa_list),
            "hpas": hpa_list
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================
# Write Operations (with confirmation reminder)
# ============================================

@tool
def scale_deployment(deployment_name: str, replicas: int, namespace: str = "default") -> Dict[str, Any]:
    """Scale a deployment to a specific number of replicas.
    
    ⚠️ This is a WRITE operation that modifies the cluster.
    
    Args:
        deployment_name: Name of the deployment to scale
        replicas: Desired number of replicas
        namespace: Kubernetes namespace
    """
    if not K8S_AVAILABLE:
        return {"success": False, "error": "Kubernetes API not available"}
    
    try:
        # Get current deployment
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace
        )
        
        old_replicas = deployment.spec.replicas
        
        # Patch the deployment
        body = {"spec": {"replicas": replicas}}
        apps_v1.patch_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            body=body
        )
        
        return {
            "success": True,
            "deployment": deployment_name,
            "namespace": namespace,
            "oldReplicas": old_replicas,
            "newReplicas": replicas,
            "message": f"Scaled {deployment_name} from {old_replicas} to {replicas} replicas"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================
# Agent Configuration
# ============================================

SYSTEM_PROMPT = """You are an expert SRE AI assistant for Amazon EKS clusters.

Your capabilities:
- Check cluster health and status (EKS API)
- List and describe pods, deployments, nodes (Kubernetes API)
- View pod logs for debugging
- Check events for recent cluster activities
- Monitor HPA autoscaling status
- Scale deployments (write operation - confirm first)

Current cluster: {cluster_name}
Region: {region}

Guidelines:
1. For issues, check events and pod logs
2. Be concise but thorough
3. For write operations, explain what will change before executing
4. Format responses clearly with bullet points

Available namespaces: onlineshop, bookstore, faulty-apps, default, kube-system
""".format(cluster_name=CLUSTER_NAME, region=REGION)


def create_eks_agent() -> Agent:
    """Create the EKS operations agent with all tools."""
    
    model = BedrockModel(
        model_id="apac.anthropic.claude-3-haiku-20240307-v1:0",
        region_name=REGION
    )
    
    tools = [
        # EKS API tools
        get_cluster_health,
        get_cluster_info,
        # Kubernetes API tools
        get_pods,
        get_pod_logs,
        describe_pod,
        get_deployments,
        get_events,
        get_nodes,
        get_hpa,
        # Write operations
        scale_deployment
    ]
    
    return Agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT
    )


def main():
    """Interactive agent session."""
    print("=" * 70)
    print("  AgenticAIOps - Strands Agent (Full K8s Support)")
    print("=" * 70)
    print(f"Cluster: {CLUSTER_NAME}")
    print(f"Region: {REGION}")
    print(f"K8s API: {'✅ Available' if K8S_AVAILABLE else '❌ Not available'}")
    print("Type 'quit' to exit\n")
    
    agent = create_eks_agent()
    
    while True:
        try:
            user_input = input("You: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            print("\nAgent: ", end="", flush=True)
            response = agent(user_input)
            print(f"{response}\n")
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()
