"""
Agent-Cloud Interface - Main Interface Class

Provides unified API for AI Agents to interact with cloud resources.
Based on AIOpsLab Framework design.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from .models import (
    TelemetryResult,
    OperationResult,
    ContextResult,
    ResultStatus,
)
from .telemetry.logs import LogsProvider
from .telemetry.events import EventsProvider
from .telemetry.metrics import MetricsProvider
from .operations.kubectl import KubectlExecutor
from .operations.shell import ShellExecutor
from .security.filters import SecurityFilter
from .security.audit import AuditLogger

logger = logging.getLogger(__name__)


class AgentCloudInterface:
    """
    Agent-Cloud Interface (ACI)
    
    Unified interface for AI agents to interact with cloud resources.
    
    Example:
        aci = AgentCloudInterface(cluster_name="testing-cluster")
        
        # Get logs
        logs = aci.get_logs(namespace="default", pod_name="nginx*")
        
        # Get events  
        events = aci.get_events(namespace="kube-system", event_type="Warning")
        
        # Execute kubectl
        result = aci.kubectl(["get", "pods", "-n", "default"])
    """
    
    def __init__(
        self,
        cluster_name: str = "testing-cluster",
        region: str = "ap-southeast-1",
        enable_audit: bool = True,
        safe_mode: bool = True,
    ):
        """
        Initialize ACI.
        
        Args:
            cluster_name: EKS cluster name
            region: AWS region
            enable_audit: Enable audit logging
            safe_mode: Enable security filters
        """
        self.cluster_name = cluster_name
        self.region = region
        self.enable_audit = enable_audit
        self.safe_mode = safe_mode
        
        # Initialize providers
        self._logs_provider = LogsProvider(cluster_name, region)
        self._events_provider = EventsProvider(cluster_name, region)
        self._metrics_provider = MetricsProvider(cluster_name, region)
        self._kubectl = KubectlExecutor(cluster_name, region)
        self._shell = ShellExecutor(safe_mode=safe_mode)
        
        # Security & Audit
        self._security = SecurityFilter()
        self._audit = AuditLogger() if enable_audit else None
        
        logger.info(f"ACI initialized for cluster={cluster_name}, region={region}")
    
    # ============ Telemetry API ============
    
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
        Get Kubernetes logs.
        
        Args:
            namespace: K8s namespace
            pod_name: Pod name (optional, supports wildcards)
            container: Container name (optional)
            duration_minutes: Time range (default 5 minutes)
            keywords: Keyword filter
            severity: Log level filter (error, warning, info)
            limit: Max entries to return
        
        Returns:
            TelemetryResult with log entries
        """
        start_time = time.time()
        
        try:
            result = self._logs_provider.get_logs(
                namespace=namespace,
                pod_name=pod_name,
                container=container,
                duration_minutes=duration_minutes,
                keywords=keywords,
                severity=severity,
                limit=limit,
            )
            
            query_time = int((time.time() - start_time) * 1000)
            result.query_time_ms = query_time
            
            self._log_audit("get_logs", f"ns={namespace}, pod={pod_name}", result.status.value)
            
            return result
            
        except Exception as e:
            logger.error(f"get_logs error: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=str(e),
                query_time_ms=int((time.time() - start_time) * 1000),
            )
    
    def get_events(
        self,
        namespace: str = "all",
        event_type: Optional[str] = None,
        reason: Optional[str] = None,
        involved_object: Optional[str] = None,
        duration_minutes: int = 60,
        limit: int = 50,
    ) -> TelemetryResult:
        """
        Get Kubernetes Events.
        
        Args:
            namespace: Namespace ("all" for all namespaces)
            event_type: Event type (Normal, Warning)
            reason: Event reason (BackOff, OOMKilled, etc.)
            involved_object: Related object name
            duration_minutes: Time range
            limit: Max entries to return
        
        Returns:
            TelemetryResult with event entries
        """
        start_time = time.time()
        
        try:
            result = self._events_provider.get_events(
                namespace=namespace,
                event_type=event_type,
                reason=reason,
                involved_object=involved_object,
                duration_minutes=duration_minutes,
                limit=limit,
            )
            
            query_time = int((time.time() - start_time) * 1000)
            result.query_time_ms = query_time
            
            self._log_audit("get_events", f"ns={namespace}, type={event_type}", result.status.value)
            
            return result
            
        except Exception as e:
            logger.error(f"get_events error: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=str(e),
                query_time_ms=int((time.time() - start_time) * 1000),
            )
    
    def get_metrics(
        self,
        namespace: str,
        query: Optional[str] = None,
        metric_names: Optional[List[str]] = None,
        duration_minutes: int = 5,
        step: str = "1m",
    ) -> TelemetryResult:
        """
        Get metrics from CloudWatch (Prometheus-compatible).
        
        Args:
            namespace: K8s namespace
            query: PromQL query (advanced)
            metric_names: Predefined metric names (simple)
            duration_minutes: Time range
            step: Data step interval
        
        Predefined metrics:
            - cpu_usage
            - memory_usage
            - network_rx
            - network_tx
            - restarts
        
        Returns:
            TelemetryResult with metric points
        """
        start_time = time.time()
        
        try:
            result = self._metrics_provider.get_metrics(
                namespace=namespace,
                query=query,
                metric_names=metric_names,
                duration_minutes=duration_minutes,
                step=step,
            )
            
            query_time = int((time.time() - start_time) * 1000)
            result.query_time_ms = query_time
            
            self._log_audit("get_metrics", f"ns={namespace}, metrics={metric_names}", result.status.value)
            
            return result
            
        except Exception as e:
            logger.error(f"get_metrics error: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=str(e),
                query_time_ms=int((time.time() - start_time) * 1000),
            )
    
    # ============ Operation API ============
    
    def kubectl(
        self,
        args: List[str],
        namespace: Optional[str] = None,
        output_format: str = "json",
    ) -> OperationResult:
        """
        Execute kubectl command.
        
        Args:
            args: kubectl arguments
            namespace: Namespace (optional)
            output_format: Output format (json, yaml, wide)
        
        Returns:
            OperationResult
        """
        command = f"kubectl {' '.join(args)}"
        
        # Security check
        if self.safe_mode:
            is_safe, reason = self._security.check_kubectl(args)
            if not is_safe:
                self._log_audit("kubectl", command, "BLOCKED")
                return OperationResult(
                    status=ResultStatus.ERROR,
                    command=command,
                    error=f"Security blocked: {reason}",
                )
        
        result = self._kubectl.execute(
            args=args,
            namespace=namespace,
            output_format=output_format,
        )
        
        self._log_audit("kubectl", command, result.status.value)
        
        return result
    
    def exec_shell(
        self,
        command: str,
        timeout: int = 30,
        capture_stderr: bool = True,
    ) -> OperationResult:
        """
        Execute shell command (with security filter).
        
        Args:
            command: Shell command
            timeout: Timeout in seconds
            capture_stderr: Capture stderr
        
        Returns:
            OperationResult
        """
        # Security check
        if self.safe_mode:
            is_safe, reason = self._security.check_shell(command)
            if not is_safe:
                self._log_audit("exec_shell", command, "BLOCKED")
                return OperationResult(
                    status=ResultStatus.ERROR,
                    command=command,
                    error=f"Security blocked: {reason}",
                )
        
        result = self._shell.execute(
            command=command,
            timeout=timeout,
            capture_stderr=capture_stderr,
        )
        
        self._log_audit("exec_shell", command, result.status.value)
        
        return result
    
    # ============ Context API ============
    
    def get_topology(self, namespace: str = "all") -> ContextResult:
        """
        Get cluster topology information.
        
        Args:
            namespace: Namespace to query
        
        Returns:
            ContextResult with topology data
        """
        # TODO: Implement topology discovery
        return ContextResult(
            status=ResultStatus.SUCCESS,
            data={"message": "Topology discovery not yet implemented"},
        )
    
    def get_dependencies(self, service_name: str) -> ContextResult:
        """
        Get service dependencies.
        
        Args:
            service_name: Service name
        
        Returns:
            ContextResult with dependency data
        """
        # TODO: Implement dependency analysis
        return ContextResult(
            status=ResultStatus.SUCCESS,
            data={"message": "Dependency analysis not yet implemented"},
        )
    
    # ============ Internal Methods ============
    
    def _log_audit(self, operation: str, details: str, result: str):
        """Log operation for audit."""
        if self._audit:
            self._audit.log(
                operation=operation,
                details=details,
                result=result,
                cluster=self.cluster_name,
            )


# Export tools for Strands Agent integration
def get_aci_tools(aci: AgentCloudInterface) -> List[Any]:
    """
    Get ACI methods as Strands tools.
    
    Usage:
        aci = AgentCloudInterface()
        agent = Agent(tools=get_aci_tools(aci))
    """
    return [
        aci.get_logs,
        aci.get_events,
        aci.get_metrics,
        aci.kubectl,
        aci.exec_shell,
    ]
