"""
AgenticAIOps - Diagnostic Tools

Automated analysis and diagnostic functions.
"""

from typing import Dict, Any, List, Optional
from .kubernetes import KubernetesTools
from .aws import AWSTools


class DiagnosticTools:
    """Automated diagnostic toolkit."""
    
    def __init__(self, k8s: KubernetesTools, aws: AWSTools):
        """Initialize with existing tool instances."""
        self.k8s = k8s
        self.aws = aws
    
    def analyze_pod_issues(
        self,
        pod_name: str,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        Perform comprehensive analysis of a pod's issues.
        
        Args:
            pod_name: Name of the pod to analyze
            namespace: Kubernetes namespace
        
        Returns:
            Analysis results with findings and recommendations
        """
        findings = []
        recommendations = []
        severity = "info"  # info, warning, critical
        
        # Get pod details
        pod_info = self.k8s.describe_pod(pod_name, namespace)
        if not pod_info.get("success"):
            return {
                "success": False,
                "error": f"Could not get pod info: {pod_info.get('error')}"
            }
        
        pod = pod_info["pod"]
        
        # Analyze phase
        phase = pod["phase"]
        if phase == "Pending":
            findings.append({
                "type": "phase",
                "issue": "Pod is in Pending state",
                "detail": "Pod has not been scheduled to a node yet"
            })
            severity = "warning"
            
            # Check events for scheduling issues
            for event in pod.get("events", []):
                if event["type"] == "Warning":
                    if "Insufficient" in event.get("message", ""):
                        findings.append({
                            "type": "resources",
                            "issue": "Insufficient cluster resources",
                            "detail": event["message"]
                        })
                        recommendations.append("Consider scaling up the cluster or reducing resource requests")
                        severity = "critical"
                    elif "FailedScheduling" in event.get("reason", ""):
                        findings.append({
                            "type": "scheduling",
                            "issue": "Scheduling failed",
                            "detail": event["message"]
                        })
        
        elif phase == "Failed":
            findings.append({
                "type": "phase",
                "issue": "Pod has failed",
                "detail": "Pod terminated with errors"
            })
            severity = "critical"
        
        # Analyze containers
        for container in pod.get("containers", []):
            container_name = container["name"]
            
            # Check resource limits
            resources = container.get("resources", {})
            if not resources.get("limits"):
                findings.append({
                    "type": "resources",
                    "issue": f"Container '{container_name}' has no resource limits",
                    "detail": "Without limits, the container could consume excessive resources"
                })
                recommendations.append(f"Set memory and CPU limits for container '{container_name}'")
        
        # Get logs if pod has been running
        logs_result = self.k8s.get_pod_logs(pod_name, namespace, tail_lines=50)
        if logs_result.get("success"):
            logs = logs_result.get("logs", "")
            
            # Look for common error patterns
            error_patterns = [
                ("OutOfMemory", "OOM error detected", "Increase memory limits or fix memory leak"),
                ("connection refused", "Connection failure", "Check target service availability"),
                ("permission denied", "Permission error", "Check file permissions and security context"),
                ("no such file", "Missing file error", "Check volume mounts and file paths"),
                ("timeout", "Timeout error", "Check network connectivity and increase timeouts"),
                ("FATAL", "Fatal error", "Check application logs for root cause"),
                ("panic", "Application panic", "Check application code for unhandled errors")
            ]
            
            for pattern, issue, recommendation in error_patterns:
                if pattern.lower() in logs.lower():
                    findings.append({
                        "type": "logs",
                        "issue": issue,
                        "detail": f"Found '{pattern}' in recent logs"
                    })
                    recommendations.append(recommendation)
                    severity = "critical" if severity != "critical" else severity
        
        # Check previous container logs for crash analysis
        if any(c.get("restart_count", 0) > 0 for c in pod.get("containers", [])):
            prev_logs = self.k8s.get_pod_logs(pod_name, namespace, tail_lines=30, previous=True)
            if prev_logs.get("success"):
                findings.append({
                    "type": "restarts",
                    "issue": "Container has restarted",
                    "detail": "Previous container instance logs available"
                })
                recommendations.append("Review previous container logs for crash cause")
        
        # Analyze events
        for event in pod.get("events", []):
            if event["type"] == "Warning":
                if "OOMKilled" in str(event):
                    findings.append({
                        "type": "oom",
                        "issue": "Container was OOM killed",
                        "detail": "Container exceeded memory limit"
                    })
                    recommendations.append("Increase memory limit or investigate memory leak")
                    severity = "critical"
                
                elif "ImagePull" in event.get("reason", ""):
                    findings.append({
                        "type": "image",
                        "issue": "Image pull problem",
                        "detail": event.get("message", "")
                    })
                    recommendations.append("Check image name, tag, and registry credentials")
                    severity = "critical"
                
                elif "CrashLoopBackOff" in str(event):
                    findings.append({
                        "type": "crash",
                        "issue": "Container in crash loop",
                        "detail": "Container repeatedly crashing and restarting"
                    })
                    recommendations.append("Check container logs for startup errors")
                    severity = "critical"
        
        return {
            "success": True,
            "pod": pod_name,
            "namespace": namespace,
            "severity": severity,
            "findings_count": len(findings),
            "findings": findings,
            "recommendations": recommendations,
            "summary": self._generate_summary(findings, recommendations, severity)
        }
    
    def check_cluster_health(self, cluster_name: str) -> Dict[str, Any]:
        """
        Perform a comprehensive cluster health check.
        
        Args:
            cluster_name: Name of the EKS cluster
        
        Returns:
            Cluster health assessment
        """
        health_status = {
            "overall": "healthy",
            "components": {}
        }
        issues = []
        
        # Check cluster status
        cluster_info = self.aws.describe_cluster(cluster_name)
        if cluster_info.get("success"):
            cluster = cluster_info["cluster"]
            health_status["components"]["cluster"] = {
                "status": cluster["status"],
                "healthy": cluster["status"] == "ACTIVE"
            }
            if cluster["status"] != "ACTIVE":
                issues.append(f"Cluster status is {cluster['status']}")
                health_status["overall"] = "degraded"
        else:
            health_status["components"]["cluster"] = {"status": "unknown", "healthy": False}
            health_status["overall"] = "unknown"
            issues.append(f"Could not get cluster info: {cluster_info.get('error')}")
        
        # Check node groups
        nodegroups_info = self.aws.list_nodegroups(cluster_name)
        if nodegroups_info.get("success"):
            ng_healthy = True
            for ng in nodegroups_info["nodegroups"]:
                if ng["status"] != "ACTIVE":
                    ng_healthy = False
                    issues.append(f"Node group {ng['name']} status is {ng['status']}")
                
                if ng["health"]:
                    ng_healthy = False
                    for issue in ng["health"]:
                        issues.append(f"Node group {ng['name']}: {issue}")
                
                # Check scaling
                scaling = ng["scaling"]
                if scaling["desired"] < scaling["min"]:
                    issues.append(f"Node group {ng['name']} desired ({scaling['desired']}) < min ({scaling['min']})")
            
            health_status["components"]["nodegroups"] = {
                "count": len(nodegroups_info["nodegroups"]),
                "healthy": ng_healthy
            }
            
            if not ng_healthy:
                health_status["overall"] = "degraded"
        
        # Check node health (EC2)
        nodes_info = self.aws.get_node_health(cluster_name)
        if nodes_info.get("success"):
            unhealthy_nodes = []
            for node in nodes_info["nodes"]:
                if node["state"] != "running":
                    unhealthy_nodes.append(node["instance_id"])
                elif node.get("system_status") != "ok" or node.get("instance_status") != "ok":
                    unhealthy_nodes.append(node["instance_id"])
            
            health_status["components"]["nodes"] = {
                "total": len(nodes_info["nodes"]),
                "unhealthy": len(unhealthy_nodes),
                "healthy": len(unhealthy_nodes) == 0
            }
            
            if unhealthy_nodes:
                issues.append(f"{len(unhealthy_nodes)} nodes are unhealthy: {unhealthy_nodes}")
                health_status["overall"] = "degraded"
        
        # Check pods
        pods_info = self.k8s.get_pods(namespace="all")
        if pods_info.get("success"):
            problematic_pods = []
            for pod in pods_info["pods"]:
                if pod["phase"] not in ["Running", "Succeeded"]:
                    problematic_pods.append(f"{pod['namespace']}/{pod['name']}: {pod['phase']}")
            
            health_status["components"]["pods"] = {
                "total": len(pods_info["pods"]),
                "problematic": len(problematic_pods),
                "healthy": len(problematic_pods) == 0
            }
            
            if problematic_pods:
                issues.append(f"{len(problematic_pods)} pods have issues")
                if health_status["overall"] == "healthy":
                    health_status["overall"] = "warning"
        
        return {
            "success": True,
            "cluster": cluster_name,
            "health": health_status,
            "issues": issues,
            "issues_count": len(issues)
        }
    
    def check_resource_usage(
        self,
        cluster_name: str,
        namespace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze resource usage across the cluster.
        
        Args:
            cluster_name: Name of the EKS cluster
            namespace: Optional namespace to filter
        
        Returns:
            Resource usage analysis
        """
        # Get Container Insights metrics
        metrics = self.aws.get_container_insights_metrics(
            cluster_name,
            namespace=namespace,
            period_minutes=30
        )
        
        analysis = {
            "cluster": cluster_name,
            "namespace": namespace,
            "container_insights_available": metrics.get("container_insights_enabled", False)
        }
        
        if metrics.get("success") and metrics.get("metrics"):
            m = metrics["metrics"]
            
            analysis["cpu"] = {
                "pod_utilization": m.get("pod_cpu_utilization", {}).get("latest_average"),
                "node_utilization": m.get("node_cpu_utilization", {}).get("latest_average"),
                "status": self._assess_utilization(m.get("node_cpu_utilization", {}).get("latest_average"))
            }
            
            analysis["memory"] = {
                "pod_utilization": m.get("pod_memory_utilization", {}).get("latest_average"),
                "node_utilization": m.get("node_memory_utilization", {}).get("latest_average"),
                "status": self._assess_utilization(m.get("node_memory_utilization", {}).get("latest_average"))
            }
            
            # Generate recommendations
            recommendations = []
            
            node_cpu = m.get("node_cpu_utilization", {}).get("latest_average")
            node_mem = m.get("node_memory_utilization", {}).get("latest_average")
            
            if node_cpu and node_cpu > 80:
                recommendations.append("CPU utilization is high (>80%). Consider scaling out or optimizing workloads.")
            elif node_cpu and node_cpu < 20:
                recommendations.append("CPU utilization is low (<20%). Consider scaling in to reduce costs.")
            
            if node_mem and node_mem > 80:
                recommendations.append("Memory utilization is high (>80%). Consider scaling out or reducing memory requests.")
            elif node_mem and node_mem < 20:
                recommendations.append("Memory utilization is low (<20%). Consider right-sizing nodes.")
            
            analysis["recommendations"] = recommendations
        else:
            analysis["recommendations"] = [
                "Container Insights not available. Enable it for detailed resource metrics.",
                "Run: aws eks update-cluster-config --name <cluster> --logging '...'"
            ]
        
        return {
            "success": True,
            **analysis
        }
    
    def _assess_utilization(self, value: Optional[float]) -> str:
        """Assess utilization level."""
        if value is None:
            return "unknown"
        if value > 80:
            return "high"
        if value > 50:
            return "moderate"
        if value > 20:
            return "normal"
        return "low"
    
    def _generate_summary(
        self,
        findings: List[Dict],
        recommendations: List[str],
        severity: str
    ) -> str:
        """Generate a human-readable summary."""
        if not findings:
            return "No issues detected. Pod appears healthy."
        
        severity_emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🔴"
        }
        
        summary_parts = [
            f"{severity_emoji.get(severity, '❓')} Found {len(findings)} issue(s) ({severity} severity):"
        ]
        
        for i, finding in enumerate(findings[:3], 1):  # Top 3 findings
            summary_parts.append(f"  {i}. {finding['issue']}")
        
        if len(findings) > 3:
            summary_parts.append(f"  ... and {len(findings) - 3} more")
        
        if recommendations:
            summary_parts.append(f"\nTop recommendation: {recommendations[0]}")
        
        return "\n".join(summary_parts)


# Tool definitions for the LLM agent
DIAGNOSTIC_TOOLS = [
    {
        "name": "analyze_pod_issues",
        "description": "Perform comprehensive analysis of a pod's issues. Checks status, logs, events, and provides recommendations.",
        "parameters": {
            "pod_name": "Name of the pod to analyze (required)",
            "namespace": "Kubernetes namespace (default: 'default')"
        }
    },
    {
        "name": "check_cluster_health",
        "description": "Perform a comprehensive cluster health check. Checks cluster, node groups, nodes, and pods.",
        "parameters": {
            "cluster_name": "Name of the EKS cluster (required)"
        }
    },
    {
        "name": "check_resource_usage",
        "description": "Analyze CPU and memory resource usage across the cluster using Container Insights metrics.",
        "parameters": {
            "cluster_name": "Name of the EKS cluster (required)",
            "namespace": "Optional Kubernetes namespace to filter"
        }
    }
]
