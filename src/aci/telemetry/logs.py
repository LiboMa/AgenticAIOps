"""
ACI Logs Provider

Provides log retrieval from Kubernetes pods via kubectl or CloudWatch.
"""

import json
import logging
import subprocess
from datetime import datetime, timedelta
from typing import List, Optional

from ..models import TelemetryResult, ResultStatus, LogEntry

logger = logging.getLogger(__name__)


class LogsProvider:
    """
    Kubernetes logs provider.
    
    Uses kubectl logs or CloudWatch Logs for log retrieval.
    """
    
    def __init__(self, cluster_name: str, region: str):
        self.cluster_name = cluster_name
        self.region = region
    
    def get_logs(
        self,
        namespace: str,
        pod_name: Optional[str] = None,
        container: Optional[str] = None,
        duration_minutes: int = 5,
        keywords: Optional[List[str]] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> TelemetryResult:
        """
        Get logs from Kubernetes pods.
        
        Args:
            namespace: K8s namespace
            pod_name: Pod name (supports wildcards like "nginx*")
            container: Container name
            duration_minutes: Time range
            keywords: Filter by keywords
            severity: Filter by level (error, warning, info)
            limit: Max entries
        
        Returns:
            TelemetryResult with LogEntry list
        """
        try:
            # Get pod list if wildcard or no pod specified
            pods = self._get_pods(namespace, pod_name)
            
            if not pods:
                return TelemetryResult(
                    status=ResultStatus.SUCCESS,
                    data=[],
                    metadata={"message": f"No pods found matching '{pod_name}' in namespace '{namespace}'"},
                )
            
            all_logs: List[LogEntry] = []
            
            for pod in pods[:5]:  # Limit to 5 pods to avoid timeout
                pod_logs = self._get_pod_logs(
                    namespace=namespace,
                    pod_name=pod,
                    container=container,
                    duration_minutes=duration_minutes,
                    limit=limit // len(pods) + 1,
                )
                all_logs.extend(pod_logs)
            
            # Apply filters
            if keywords:
                all_logs = [log for log in all_logs if any(kw.lower() in log.message.lower() for kw in keywords)]
            
            if severity:
                all_logs = [log for log in all_logs if log.level.lower() == severity.lower()]
            
            # Sort by timestamp and limit
            all_logs.sort(key=lambda x: x.timestamp, reverse=True)
            all_logs = all_logs[:limit]
            
            return TelemetryResult(
                status=ResultStatus.SUCCESS,
                data=[log.to_dict() for log in all_logs],
                metadata={
                    "namespace": namespace,
                    "pods_queried": pods[:5],
                    "total_entries": len(all_logs),
                },
            )
            
        except Exception as e:
            logger.error(f"Error getting logs: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=str(e),
            )
    
    def _get_pods(self, namespace: str, pod_pattern: Optional[str] = None) -> List[str]:
        """Get pod names matching pattern."""
        try:
            cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "jsonpath={.items[*].metadata.name}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                logger.warning(f"kubectl get pods failed: {result.stderr}")
                return []
            
            pods = result.stdout.strip().split()
            
            # Filter by pattern
            if pod_pattern:
                import fnmatch
                pods = [p for p in pods if fnmatch.fnmatch(p, pod_pattern)]
            
            return pods
            
        except subprocess.TimeoutExpired:
            logger.error("kubectl get pods timeout")
            return []
        except Exception as e:
            logger.error(f"Error getting pods: {e}")
            return []
    
    def _get_pod_logs(
        self,
        namespace: str,
        pod_name: str,
        container: Optional[str] = None,
        duration_minutes: int = 5,
        limit: int = 50,
    ) -> List[LogEntry]:
        """Get logs from a specific pod."""
        try:
            cmd = [
                "kubectl", "logs",
                "-n", namespace,
                pod_name,
                f"--since={duration_minutes}m",
                f"--tail={limit}",
                "--timestamps=true",
            ]
            
            if container:
                cmd.extend(["-c", container])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                logger.warning(f"kubectl logs failed for {pod_name}: {result.stderr}")
                return []
            
            logs = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                
                entry = self._parse_log_line(line, namespace, pod_name, container or "default")
                if entry:
                    logs.append(entry)
            
            return logs
            
        except subprocess.TimeoutExpired:
            logger.error(f"kubectl logs timeout for {pod_name}")
            return []
        except Exception as e:
            logger.error(f"Error getting logs for {pod_name}: {e}")
            return []
    
    def _parse_log_line(self, line: str, namespace: str, pod: str, container: str) -> Optional[LogEntry]:
        """Parse a log line with timestamp."""
        try:
            # Format: 2024-01-15T10:30:00.000000000Z message
            parts = line.split(" ", 1)
            if len(parts) < 2:
                return None
            
            timestamp_str, message = parts
            
            # Parse timestamp (remove nanoseconds)
            timestamp_str = timestamp_str.split(".")[0] + "Z"
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            
            # Detect log level
            level = self._detect_log_level(message)
            
            return LogEntry(
                timestamp=timestamp,
                namespace=namespace,
                pod=pod,
                container=container,
                message=message,
                level=level,
            )
            
        except Exception as e:
            logger.debug(f"Failed to parse log line: {e}")
            return None
    
    def _detect_log_level(self, message: str) -> str:
        """Detect log level from message content."""
        message_lower = message.lower()
        
        if any(kw in message_lower for kw in ["error", "exception", "fail", "fatal", "critical"]):
            return "error"
        elif any(kw in message_lower for kw in ["warn", "warning"]):
            return "warning"
        else:
            return "info"
