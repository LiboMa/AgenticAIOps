"""
AgenticAIOps - K8sGPT-style Analyzers

Inspired by K8sGPT's analyzer pattern for systematic issue detection.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    """Issue severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AnalysisResult:
    """Result from an analyzer."""
    analyzer: str
    kind: str
    name: str
    namespace: str
    severity: Severity
    issues: List[str]
    recommendations: List[str]
    raw_data: Optional[Dict[str, Any]] = None


class BaseAnalyzer:
    """Base class for analyzers."""
    
    name: str = "base"
    
    def __init__(self, k8s_tools):
        self.k8s = k8s_tools
    
    def analyze(self, namespace: str = "all") -> List[AnalysisResult]:
        raise NotImplementedError


class PodAnalyzer(BaseAnalyzer):
    """
    Analyzes pods for common issues.
    
    Checks for:
    - CrashLoopBackOff
    - ImagePullBackOff
    - OOMKilled
    - Pending state
    - High restart counts
    - Container not ready
    """
    
    name = "pod"
    
    # Known error patterns and their explanations
    ERROR_PATTERNS = {
        "CrashLoopBackOff": {
            "severity": Severity.CRITICAL,
            "explanation": "Container is crashing repeatedly",
            "recommendations": [
                "Check container logs for error messages",
                "Verify the container command and entrypoint",
                "Check if required environment variables are set",
                "Ensure dependent services are available"
            ]
        },
        "ImagePullBackOff": {
            "severity": Severity.ERROR,
            "explanation": "Cannot pull the container image",
            "recommendations": [
                "Verify the image name and tag are correct",
                "Check if the image exists in the registry",
                "Verify imagePullSecrets are configured if using private registry",
                "Check network connectivity to the registry"
            ]
        },
        "ErrImagePull": {
            "severity": Severity.ERROR,
            "explanation": "Failed to pull container image",
            "recommendations": [
                "Check image name for typos",
                "Verify registry credentials",
                "Check if the image tag exists"
            ]
        },
        "OOMKilled": {
            "severity": Severity.CRITICAL,
            "explanation": "Container exceeded memory limit and was killed",
            "recommendations": [
                "Increase the memory limit in the pod spec",
                "Investigate potential memory leaks in the application",
                "Review recent code changes for memory issues",
                "Consider adding memory profiling"
            ]
        },
        "CreateContainerConfigError": {
            "severity": Severity.ERROR,
            "explanation": "Error creating container configuration",
            "recommendations": [
                "Check if referenced ConfigMaps exist",
                "Check if referenced Secrets exist",
                "Verify volume mount configurations"
            ]
        },
        "InvalidImageName": {
            "severity": Severity.ERROR,
            "explanation": "The image name is invalid",
            "recommendations": [
                "Check the image name format",
                "Ensure there are no special characters"
            ]
        },
        "Pending": {
            "severity": Severity.WARNING,
            "explanation": "Pod is waiting to be scheduled",
            "recommendations": [
                "Check if cluster has sufficient resources",
                "Review node selectors and affinity rules",
                "Check for taints that might prevent scheduling",
                "Verify PVC bindings if using persistent volumes"
            ]
        }
    }
    
    def analyze(self, namespace: str = "all") -> List[AnalysisResult]:
        """Analyze all pods in the given namespace."""
        results = []
        
        pods_response = self.k8s.get_pods(namespace=namespace)
        if not pods_response.get("success"):
            return results
        
        for pod in pods_response.get("pods", []):
            issues = []
            recommendations = []
            severity = Severity.INFO
            
            # Check pod phase
            phase = pod.get("phase", "")
            if phase == "Pending":
                pattern = self.ERROR_PATTERNS["Pending"]
                issues.append(f"Pod is in Pending state: {pattern['explanation']}")
                recommendations.extend(pattern["recommendations"])
                severity = max(severity, pattern["severity"], key=lambda x: list(Severity).index(x))
            
            elif phase == "Failed":
                issues.append("Pod has failed")
                severity = Severity.CRITICAL
            
            # Check container statuses
            for container in pod.get("containers", []):
                state = container.get("state", {})
                state_name = state.get("state", "")
                restart_count = container.get("restart_count", 0)
                
                # Check for known error states
                if state_name == "waiting":
                    reason = state.get("reason", "")
                    for pattern_name, pattern_info in self.ERROR_PATTERNS.items():
                        if pattern_name in reason:
                            issues.append(f"Container '{container['name']}': {reason} - {pattern_info['explanation']}")
                            recommendations.extend(pattern_info["recommendations"])
                            severity = max(severity, pattern_info["severity"], key=lambda x: list(Severity).index(x))
                            break
                
                # Check for terminated with error
                elif state_name == "terminated":
                    reason = state.get("reason", "")
                    exit_code = state.get("exit_code", 0)
                    
                    if "OOMKilled" in reason:
                        pattern = self.ERROR_PATTERNS["OOMKilled"]
                        issues.append(f"Container '{container['name']}': {pattern['explanation']}")
                        recommendations.extend(pattern["recommendations"])
                        severity = Severity.CRITICAL
                    elif exit_code != 0:
                        issues.append(f"Container '{container['name']}' exited with code {exit_code}")
                        severity = max(severity, Severity.ERROR, key=lambda x: list(Severity).index(x))
                
                # Check restart count
                if restart_count > 5:
                    issues.append(f"Container '{container['name']}' has restarted {restart_count} times")
                    recommendations.append("Investigate logs from previous container instances")
                    severity = max(severity, Severity.WARNING, key=lambda x: list(Severity).index(x))
                
                # Check if container is not ready
                if not container.get("ready", True) and state_name == "running":
                    issues.append(f"Container '{container['name']}' is running but not ready")
                    recommendations.append("Check readiness probe configuration and application health")
                    severity = max(severity, Severity.WARNING, key=lambda x: list(Severity).index(x))
            
            # Only add results for pods with issues
            if issues:
                results.append(AnalysisResult(
                    analyzer=self.name,
                    kind="Pod",
                    name=pod["name"],
                    namespace=pod["namespace"],
                    severity=severity,
                    issues=issues,
                    recommendations=list(set(recommendations)),  # Deduplicate
                    raw_data=pod
                ))
        
        return results


class DeploymentAnalyzer(BaseAnalyzer):
    """
    Analyzes deployments for common issues.
    
    Checks for:
    - Unavailable replicas
    - Replica mismatch
    - Stalled rollouts
    - Missing deployments
    """
    
    name = "deployment"
    
    def analyze(self, namespace: str = "all") -> List[AnalysisResult]:
        """Analyze all deployments in the given namespace."""
        results = []
        
        deps_response = self.k8s.get_deployments(namespace=namespace)
        if not deps_response.get("success"):
            return results
        
        for dep in deps_response.get("deployments", []):
            issues = []
            recommendations = []
            severity = Severity.INFO
            
            replicas = dep.get("replicas", {})
            desired = replicas.get("desired", 0)
            ready = replicas.get("ready", 0)
            available = replicas.get("available", 0)
            updated = replicas.get("updated", 0)
            
            # Check for replica issues
            if desired > 0:
                if ready == 0:
                    issues.append(f"No replicas ready (0/{desired})")
                    recommendations.append("Check pod status for underlying issues")
                    severity = Severity.CRITICAL
                
                elif ready < desired:
                    issues.append(f"Not all replicas ready ({ready}/{desired})")
                    recommendations.append("Check pod status for failing replicas")
                    severity = max(severity, Severity.WARNING, key=lambda x: list(Severity).index(x))
                
                if available < desired:
                    issues.append(f"Not all replicas available ({available}/{desired})")
                    severity = max(severity, Severity.WARNING, key=lambda x: list(Severity).index(x))
                
                # Check for stalled rollout
                if updated < desired and ready == updated:
                    issues.append(f"Rollout may be stalled ({updated}/{desired} updated)")
                    recommendations.append("Check deployment events for rollout issues")
                    recommendations.append("Consider running 'kubectl rollout status' for details")
                    severity = max(severity, Severity.WARNING, key=lambda x: list(Severity).index(x))
            
            elif desired == 0:
                issues.append("Deployment is scaled to 0 replicas")
                severity = Severity.INFO
            
            # Check conditions
            for condition in dep.get("conditions", []):
                if condition.get("type") == "Available" and condition.get("status") == "False":
                    issues.append(f"Deployment not available: {condition.get('message', 'unknown reason')}")
                    severity = max(severity, Severity.ERROR, key=lambda x: list(Severity).index(x))
                
                if condition.get("type") == "Progressing" and condition.get("status") == "False":
                    issues.append(f"Deployment not progressing: {condition.get('message', 'unknown reason')}")
                    recommendations.append("Check for resource constraints or image issues")
                    severity = max(severity, Severity.WARNING, key=lambda x: list(Severity).index(x))
            
            # Only add results for deployments with issues
            if issues:
                results.append(AnalysisResult(
                    analyzer=self.name,
                    kind="Deployment",
                    name=dep["name"],
                    namespace=dep["namespace"],
                    severity=severity,
                    issues=issues,
                    recommendations=list(set(recommendations)),
                    raw_data=dep
                ))
        
        return results


class NodeAnalyzer(BaseAnalyzer):
    """
    Analyzes nodes for common issues.
    
    Uses AWS tools to check EC2 instance health.
    """
    
    name = "node"
    
    def __init__(self, k8s_tools, aws_tools, cluster_name: str):
        super().__init__(k8s_tools)
        self.aws = aws_tools
        self.cluster_name = cluster_name
    
    def analyze(self, namespace: str = "all") -> List[AnalysisResult]:
        """Analyze all nodes in the cluster."""
        results = []
        
        nodes_response = self.aws.get_node_health(self.cluster_name)
        if not nodes_response.get("success"):
            return results
        
        for node in nodes_response.get("nodes", []):
            issues = []
            recommendations = []
            severity = Severity.INFO
            
            instance_id = node.get("instance_id", "")
            name = node.get("name", instance_id)
            state = node.get("state", "")
            
            # Check instance state
            if state != "running":
                issues.append(f"Node instance is {state}")
                severity = Severity.CRITICAL
            
            # Check status checks
            system_status = node.get("system_status", "unknown")
            instance_status = node.get("instance_status", "unknown")
            
            if system_status != "ok":
                issues.append(f"System status check: {system_status}")
                recommendations.append("Check AWS console for system status details")
                severity = max(severity, Severity.ERROR, key=lambda x: list(Severity).index(x))
            
            if instance_status != "ok":
                issues.append(f"Instance status check: {instance_status}")
                recommendations.append("Check instance logs and metrics")
                severity = max(severity, Severity.ERROR, key=lambda x: list(Severity).index(x))
            
            if issues:
                results.append(AnalysisResult(
                    analyzer=self.name,
                    kind="Node",
                    name=name,
                    namespace="cluster",
                    severity=severity,
                    issues=issues,
                    recommendations=recommendations,
                    raw_data=node
                ))
        
        return results


class EventAnalyzer(BaseAnalyzer):
    """
    Analyzes cluster events for warnings and errors.
    """
    
    name = "event"
    
    # Events that indicate problems
    WARNING_EVENTS = {
        "FailedScheduling": "Pod could not be scheduled",
        "FailedMount": "Volume mount failed",
        "FailedAttachVolume": "Volume attachment failed",
        "NodeNotReady": "Node became not ready",
        "Unhealthy": "Health check failed",
        "BackOff": "Container backoff",
        "Failed": "Operation failed",
        "FailedCreate": "Resource creation failed",
        "FailedKillPod": "Failed to kill pod",
        "NetworkNotReady": "Network not ready"
    }
    
    def analyze(self, namespace: str = "all") -> List[AnalysisResult]:
        """Analyze recent warning events."""
        results = []
        
        events_response = self.k8s.get_events(namespace=namespace, limit=100)
        if not events_response.get("success"):
            return results
        
        # Group events by involved object
        object_events: Dict[str, List[Dict]] = {}
        
        for event in events_response.get("events", []):
            if event.get("type") == "Warning":
                obj_key = event.get("object", "unknown")
                if obj_key not in object_events:
                    object_events[obj_key] = []
                object_events[obj_key].append(event)
        
        # Analyze grouped events
        for obj_key, events in object_events.items():
            issues = []
            recommendations = []
            severity = Severity.WARNING
            
            for event in events:
                reason = event.get("reason", "")
                message = event.get("message", "")
                count = event.get("count", 1)
                
                # Check for known warning patterns
                for pattern, description in self.WARNING_EVENTS.items():
                    if pattern in reason:
                        issue_text = f"{description}: {message}"
                        if count > 1:
                            issue_text += f" (occurred {count} times)"
                        issues.append(issue_text)
                        break
                else:
                    # Generic warning
                    issues.append(f"{reason}: {message}")
            
            if issues:
                # Parse object key (format: Kind/Name)
                parts = obj_key.split("/")
                kind = parts[0] if parts else "Unknown"
                name = parts[1] if len(parts) > 1 else obj_key
                
                results.append(AnalysisResult(
                    analyzer=self.name,
                    kind=kind,
                    name=name,
                    namespace=events[0].get("namespace", "unknown") if events else "unknown",
                    severity=severity,
                    issues=issues,
                    recommendations=["Check resource configuration and logs"],
                    raw_data={"events": events}
                ))
        
        return results


class ClusterAnalyzer:
    """
    Main analyzer that runs all sub-analyzers.
    """
    
    def __init__(self, k8s_tools, aws_tools, cluster_name: str):
        self.analyzers = [
            PodAnalyzer(k8s_tools),
            DeploymentAnalyzer(k8s_tools),
            NodeAnalyzer(k8s_tools, aws_tools, cluster_name),
            EventAnalyzer(k8s_tools)
        ]
    
    def analyze_all(self, namespace: str = "all") -> Dict[str, Any]:
        """
        Run all analyzers and return aggregated results.
        
        Args:
            namespace: Namespace to analyze
        
        Returns:
            Aggregated analysis results
        """
        all_results = []
        
        for analyzer in self.analyzers:
            try:
                results = analyzer.analyze(namespace=namespace)
                all_results.extend(results)
            except Exception as e:
                # Log error but continue with other analyzers
                print(f"Analyzer {analyzer.name} failed: {e}")
        
        # Sort by severity (critical first)
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.ERROR: 1,
            Severity.WARNING: 2,
            Severity.INFO: 3
        }
        all_results.sort(key=lambda x: severity_order.get(x.severity, 999))
        
        # Summarize
        summary = {
            "total_issues": len(all_results),
            "by_severity": {
                "critical": len([r for r in all_results if r.severity == Severity.CRITICAL]),
                "error": len([r for r in all_results if r.severity == Severity.ERROR]),
                "warning": len([r for r in all_results if r.severity == Severity.WARNING]),
                "info": len([r for r in all_results if r.severity == Severity.INFO])
            },
            "by_kind": {}
        }
        
        for result in all_results:
            kind = result.kind
            if kind not in summary["by_kind"]:
                summary["by_kind"][kind] = 0
            summary["by_kind"][kind] += 1
        
        return {
            "success": True,
            "namespace": namespace,
            "summary": summary,
            "results": [
                {
                    "analyzer": r.analyzer,
                    "kind": r.kind,
                    "name": r.name,
                    "namespace": r.namespace,
                    "severity": r.severity.value,
                    "issues": r.issues,
                    "recommendations": r.recommendations
                }
                for r in all_results
            ]
        }
    
    def format_report(self, analysis: Dict[str, Any]) -> str:
        """
        Format analysis results into a readable report.
        
        Args:
            analysis: Analysis results from analyze_all()
        
        Returns:
            Formatted report string
        """
        if not analysis.get("success"):
            return "Analysis failed"
        
        summary = analysis.get("summary", {})
        results = analysis.get("results", [])
        
        lines = [
            "# Cluster Analysis Report",
            "",
            f"**Total Issues Found**: {summary.get('total_issues', 0)}",
            "",
            "## Summary by Severity",
            f"- 🔴 Critical: {summary['by_severity'].get('critical', 0)}",
            f"- 🟠 Error: {summary['by_severity'].get('error', 0)}",
            f"- 🟡 Warning: {summary['by_severity'].get('warning', 0)}",
            f"- 🔵 Info: {summary['by_severity'].get('info', 0)}",
            ""
        ]
        
        if results:
            lines.append("## Issues")
            lines.append("")
            
            for result in results:
                severity_emoji = {
                    "critical": "🔴",
                    "error": "🟠",
                    "warning": "🟡",
                    "info": "🔵"
                }.get(result["severity"], "❓")
                
                lines.append(f"### {severity_emoji} {result['kind']}/{result['name']} ({result['namespace']})")
                lines.append("")
                
                for issue in result["issues"]:
                    lines.append(f"- {issue}")
                
                if result["recommendations"]:
                    lines.append("")
                    lines.append("**Recommendations:**")
                    for rec in result["recommendations"][:3]:  # Top 3
                        lines.append(f"- {rec}")
                
                lines.append("")
        else:
            lines.append("✅ No issues found!")
        
        return "\n".join(lines)
