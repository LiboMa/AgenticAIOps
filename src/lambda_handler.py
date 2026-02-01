"""
AgenticAIOps - Lambda Handler for Bedrock Agent Action Group

This Lambda function handles action group invocations from the Bedrock Agent.
It routes requests to the appropriate K8s/AWS tools.
"""

import json
import os
from typing import Dict, Any

# These would be imported from the tools module in actual deployment
# from tools.kubernetes import KubernetesTools
# from tools.aws import AWSTools
# from tools.diagnostics import DiagnosticTools


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle Bedrock Agent action group invocations.
    
    Event structure:
    {
        "actionGroup": "eks-operations",
        "apiPath": "/pods",
        "httpMethod": "GET",
        "parameters": [...],
        "requestBody": {...}
    }
    """
    print(f"Received event: {json.dumps(event)}")
    
    action_group = event.get("actionGroup", "")
    api_path = event.get("apiPath", "")
    http_method = event.get("httpMethod", "GET")
    parameters = {p["name"]: p["value"] for p in event.get("parameters", [])}
    request_body = event.get("requestBody", {})
    
    # Route to appropriate handler
    try:
        if api_path == "/pods" and http_method == "GET":
            result = handle_get_pods(parameters)
        
        elif api_path.startswith("/pods/") and api_path.endswith("/logs"):
            pod_name = api_path.split("/")[2]
            result = handle_get_pod_logs(pod_name, parameters)
        
        elif api_path == "/events" and http_method == "GET":
            result = handle_get_events(parameters)
        
        elif api_path == "/deployments" and http_method == "GET":
            result = handle_get_deployments(parameters)
        
        elif api_path.endswith("/scale") and http_method == "POST":
            deployment_name = api_path.split("/")[2]
            result = handle_scale_deployment(deployment_name, parameters, request_body)
        
        elif api_path.endswith("/restart") and http_method == "POST":
            deployment_name = api_path.split("/")[2]
            result = handle_restart_deployment(deployment_name, parameters)
        
        elif api_path == "/cluster/health" and http_method == "GET":
            result = handle_cluster_health()
        
        elif api_path.startswith("/analyze/pod/"):
            pod_name = api_path.split("/")[3]
            result = handle_analyze_pod(pod_name, parameters)
        
        else:
            result = {
                "success": False,
                "error": f"Unknown action: {http_method} {api_path}"
            }
        
        return format_response(result)
    
    except Exception as e:
        return format_response({
            "success": False,
            "error": str(e)
        })


def format_response(result: Dict[str, Any]) -> Dict[str, Any]:
    """Format response for Bedrock Agent."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": "eks-operations",
            "apiPath": "/",
            "httpMethod": "GET",
            "httpStatusCode": 200 if result.get("success", True) else 500,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(result)
                }
            }
        }
    }


# Handler functions (simplified - in production would use actual K8s client)

def handle_get_pods(params: Dict) -> Dict:
    """Handle getPods action."""
    namespace = params.get("namespace", "default")
    label_selector = params.get("labelSelector")
    
    # In production: use KubernetesTools().get_pods(namespace, label_selector)
    # For Lambda, need to configure kubeconfig or use EKS API
    
    return {
        "success": True,
        "namespace": namespace,
        "message": f"Would list pods in {namespace}",
        "note": "Connect to actual EKS cluster for real data"
    }


def handle_get_pod_logs(pod_name: str, params: Dict) -> Dict:
    """Handle getPodLogs action."""
    namespace = params.get("namespace", "default")
    tail_lines = int(params.get("tailLines", 100))
    
    return {
        "success": True,
        "pod": pod_name,
        "namespace": namespace,
        "message": f"Would get last {tail_lines} lines of logs"
    }


def handle_get_events(params: Dict) -> Dict:
    """Handle getEvents action."""
    namespace = params.get("namespace", "default")
    
    return {
        "success": True,
        "namespace": namespace,
        "message": "Would list cluster events"
    }


def handle_get_deployments(params: Dict) -> Dict:
    """Handle getDeployments action."""
    namespace = params.get("namespace", "default")
    
    return {
        "success": True,
        "namespace": namespace,
        "message": "Would list deployments"
    }


def handle_scale_deployment(name: str, params: Dict, body: Dict) -> Dict:
    """Handle scaleDeployment action."""
    namespace = params.get("namespace", "default")
    replicas = body.get("content", {}).get("application/json", {}).get("properties", {}).get("replicas", 1)
    
    return {
        "success": True,
        "deployment": name,
        "namespace": namespace,
        "replicas": replicas,
        "message": f"Would scale {name} to {replicas} replicas",
        "requires_confirmation": True
    }


def handle_restart_deployment(name: str, params: Dict) -> Dict:
    """Handle restartDeployment action."""
    namespace = params.get("namespace", "default")
    
    return {
        "success": True,
        "deployment": name,
        "namespace": namespace,
        "message": f"Would restart {name}",
        "requires_confirmation": True
    }


def handle_cluster_health() -> Dict:
    """Handle getClusterHealth action."""
    return {
        "success": True,
        "message": "Would check cluster health",
        "checks": ["nodes", "pods", "deployments", "events"]
    }


def handle_analyze_pod(pod_name: str, params: Dict) -> Dict:
    """Handle analyzePod action."""
    namespace = params.get("namespace", "default")
    
    return {
        "success": True,
        "pod": pod_name,
        "namespace": namespace,
        "message": "Would analyze pod issues and provide recommendations"
    }


# Local testing
if __name__ == "__main__":
    # Test event
    test_event = {
        "actionGroup": "eks-operations",
        "apiPath": "/pods",
        "httpMethod": "GET",
        "parameters": [
            {"name": "namespace", "value": "production"}
        ]
    }
    
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
