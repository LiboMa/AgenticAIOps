"""
Health Checker - K8s Cluster Health Check Implementation

Performs health checks on K8s resources and integrates with
RCA engine and Issue Manager.
"""

import logging
import time
from datetime import datetime, UTC
from typing import List, Dict, Optional, Any

from .models import (
    HealthCheckResult, CheckItem, CheckType, CheckStatus, HealthCheckConfig
)

logger = logging.getLogger(__name__)


class HealthChecker:
    """
    K8s cluster health checker.
    
    Performs health checks on pods, nodes, services, and events.
    Integrates with RCA engine for root cause analysis and
    Issue Manager for tracking problems.
    
    Example:
        checker = HealthChecker()
        result = checker.check_pods(namespace="default")
        
        if result.critical_count > 0:
            print(f"Critical issues found: {result.critical_count}")
    """
    
    def __init__(
        self,
        aci=None,
        rca_engine=None,
        issue_manager=None,
        config: Optional[HealthCheckConfig] = None,
    ):
        """
        Initialize the health checker.
        
        Args:
            aci: AgentCloudInterface instance (lazy-loaded if None)
            rca_engine: RCAEngine instance (lazy-loaded if None)
            issue_manager: IssueManager instance (lazy-loaded if None)
            config: Health check configuration
        """
        self._aci = aci
        self._rca_engine = rca_engine
        self._issue_manager = issue_manager
        self.config = config or HealthCheckConfig()
    
    @property
    def aci(self):
        """Lazy-load ACI."""
        if self._aci is None:
            try:
                from src.aci import AgentCloudInterface
                self._aci = AgentCloudInterface()
            except ImportError:
                logger.warning("ACI not available")
        return self._aci
    
    @property
    def rca_engine(self):
        """Lazy-load RCA engine."""
        if self._rca_engine is None:
            try:
                from src.rca import RCAEngine
                self._rca_engine = RCAEngine()
            except ImportError:
                logger.warning("RCA engine not available")
        return self._rca_engine
    
    @property
    def issue_manager(self):
        """Lazy-load Issue manager."""
        if self._issue_manager is None:
            try:
                from src.issues import IssueManager
                self._issue_manager = IssueManager()
            except ImportError:
                logger.warning("Issue manager not available")
        return self._issue_manager
    
    def run_full_check(
        self, 
        namespaces: Optional[List[str]] = None
    ) -> HealthCheckResult:
        """
        Run full health check on all resource types.
        
        Args:
            namespaces: Namespaces to check (None = all)
            
        Returns:
            Aggregated HealthCheckResult
        """
        start_time = time.time()
        all_items = []
        issues_created = 0
        issues_updated = 0
        
        # Run individual checks
        for check_type in self.config.check_types:
            if check_type == CheckType.PODS:
                result = self.check_pods(namespaces)
            elif check_type == CheckType.NODES:
                result = self.check_nodes()
            elif check_type == CheckType.EVENTS:
                result = self.check_events(namespaces)
            elif check_type == CheckType.SERVICES:
                result = self.check_services(namespaces)
            elif check_type == CheckType.RESOURCES:
                result = self.check_resources(namespaces)
            else:
                continue
            
            all_items.extend(result.items)
            issues_created += result.issues_created
            issues_updated += result.issues_updated
        
        # Determine overall status
        if any(i.status == CheckStatus.CRITICAL for i in all_items):
            overall_status = CheckStatus.CRITICAL
        elif any(i.status == CheckStatus.WARNING for i in all_items):
            overall_status = CheckStatus.WARNING
        elif all_items:
            overall_status = CheckStatus.HEALTHY
        else:
            overall_status = CheckStatus.UNKNOWN
        
        duration_ms = (time.time() - start_time) * 1000
        
        return HealthCheckResult(
            check_type=CheckType.FULL,
            status=overall_status,
            items=all_items,
            issues_created=issues_created,
            issues_updated=issues_updated,
            duration_ms=duration_ms,
        )
    
    def check_pods(
        self, 
        namespaces: Optional[List[str]] = None
    ) -> HealthCheckResult:
        """
        Check pod health across namespaces.
        
        Args:
            namespaces: Namespaces to check
            
        Returns:
            HealthCheckResult
        """
        start_time = time.time()
        items = []
        issues_created = 0
        issues_updated = 0
        
        if not self.aci:
            return HealthCheckResult(
                check_type=CheckType.PODS,
                status=CheckStatus.UNKNOWN,
                items=[],
                duration_ms=(time.time() - start_time) * 1000,
            )
        
        try:
            # Get pods from ACI
            ns_list = namespaces or self.config.namespaces or [None]
            
            for ns in ns_list:
                result = self.aci.get_pods(namespace=ns)
                
                if result.status.value != "success":
                    logger.warning(f"Failed to get pods for namespace {ns}")
                    continue
                
                pods = result.data or []
                
                for pod in pods:
                    item = self._check_pod(pod)
                    items.append(item)
                    
                    # Create/update issues for unhealthy pods
                    if item.status in [CheckStatus.WARNING, CheckStatus.CRITICAL]:
                        created, updated = self._handle_unhealthy_pod(item, pod)
                        issues_created += created
                        issues_updated += updated
        
        except Exception as e:
            logger.error(f"Error checking pods: {e}")
        
        # Determine overall status
        if any(i.status == CheckStatus.CRITICAL for i in items):
            overall_status = CheckStatus.CRITICAL
        elif any(i.status == CheckStatus.WARNING for i in items):
            overall_status = CheckStatus.WARNING
        elif items:
            overall_status = CheckStatus.HEALTHY
        else:
            overall_status = CheckStatus.UNKNOWN
        
        return HealthCheckResult(
            check_type=CheckType.PODS,
            status=overall_status,
            items=items,
            issues_created=issues_created,
            issues_updated=issues_updated,
            duration_ms=(time.time() - start_time) * 1000,
        )
    
    def _check_pod(self, pod: Dict[str, Any]) -> CheckItem:
        """Check individual pod health."""
        name = pod.get("name", "unknown")
        namespace = pod.get("namespace", "default")
        status = pod.get("status", "Unknown")
        phase = pod.get("phase", "Unknown")
        restart_count = pod.get("restart_count", 0)
        ready = pod.get("ready", False)
        
        # Determine check status
        if phase == "Running" and ready:
            if restart_count > 5:
                check_status = CheckStatus.WARNING
                message = f"Pod running but high restart count ({restart_count})"
            else:
                check_status = CheckStatus.HEALTHY
                message = "Pod running normally"
        elif phase in ["Pending", "Unknown"]:
            check_status = CheckStatus.WARNING
            message = f"Pod in {phase} state"
        elif phase in ["Failed", "CrashLoopBackOff"]:
            check_status = CheckStatus.CRITICAL
            message = f"Pod in {phase} state"
        elif status in ["CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"]:
            check_status = CheckStatus.CRITICAL
            message = f"Pod status: {status}"
        elif not ready:
            check_status = CheckStatus.WARNING
            message = "Pod not ready"
        else:
            check_status = CheckStatus.WARNING
            message = f"Pod status: {status}"
        
        return CheckItem(
            name=name,
            namespace=namespace,
            status=check_status,
            message=message,
            details={
                "phase": phase,
                "status": status,
                "restart_count": restart_count,
                "ready": ready,
            }
        )
    
    def _handle_unhealthy_pod(
        self, 
        item: CheckItem, 
        pod: Dict[str, Any]
    ) -> tuple[int, int]:
        """Handle unhealthy pod - create/update issue."""
        created = 0
        updated = 0
        
        if not self.issue_manager:
            return 0, 0
        
        try:
            from src.issues import Severity as IssueSeverity
            
            # Map check status to issue severity
            if item.status == CheckStatus.CRITICAL:
                severity = IssueSeverity.HIGH
            else:
                severity = IssueSeverity.MEDIUM
            
            # Run RCA if available
            rca_result = None
            if self.rca_engine:
                rca_result = self.rca_engine.analyze(
                    namespace=item.namespace,
                    pod=item.name,
                )
            
            # Create or update issue
            issue = self.issue_manager.create_or_update_issue(
                namespace=item.namespace,
                resource_type="pod",
                resource_name=item.name,
                title=f"Pod {item.name}: {item.message}",
                description=item.message,
                severity=severity,
                root_cause=rca_result.root_cause if rca_result else None,
                remediation=rca_result.remediation.suggestion if rca_result else None,
            )
            
            if issue:
                # Check if it was created vs updated
                # Simplified: just count as created
                created = 1
        
        except Exception as e:
            logger.error(f"Error handling unhealthy pod: {e}")
        
        return created, updated
    
    def check_nodes(self) -> HealthCheckResult:
        """Check node health."""
        start_time = time.time()
        items = []
        
        if not self.aci:
            return HealthCheckResult(
                check_type=CheckType.NODES,
                status=CheckStatus.UNKNOWN,
                items=[],
                duration_ms=(time.time() - start_time) * 1000,
            )
        
        try:
            result = self.aci.get_nodes()
            
            if result.status.value == "success":
                nodes = result.data or []
                
                for node in nodes:
                    name = node.get("name", "unknown")
                    status = node.get("status", "Unknown")
                    conditions = node.get("conditions", {})
                    
                    ready = conditions.get("Ready", False)
                    memory_pressure = conditions.get("MemoryPressure", False)
                    disk_pressure = conditions.get("DiskPressure", False)
                    
                    if ready and not memory_pressure and not disk_pressure:
                        check_status = CheckStatus.HEALTHY
                        message = "Node is healthy"
                    elif not ready:
                        check_status = CheckStatus.CRITICAL
                        message = "Node is not ready"
                    else:
                        check_status = CheckStatus.WARNING
                        message = f"Node has pressure: memory={memory_pressure}, disk={disk_pressure}"
                    
                    items.append(CheckItem(
                        name=name,
                        namespace="",
                        status=check_status,
                        message=message,
                        details={"status": status, "conditions": conditions}
                    ))
        
        except Exception as e:
            logger.error(f"Error checking nodes: {e}")
        
        if any(i.status == CheckStatus.CRITICAL for i in items):
            overall_status = CheckStatus.CRITICAL
        elif any(i.status == CheckStatus.WARNING for i in items):
            overall_status = CheckStatus.WARNING
        elif items:
            overall_status = CheckStatus.HEALTHY
        else:
            overall_status = CheckStatus.UNKNOWN
        
        return HealthCheckResult(
            check_type=CheckType.NODES,
            status=overall_status,
            items=items,
            duration_ms=(time.time() - start_time) * 1000,
        )
    
    def check_events(
        self, 
        namespaces: Optional[List[str]] = None
    ) -> HealthCheckResult:
        """Check for warning/error events."""
        start_time = time.time()
        items = []
        issues_created = 0
        
        if not self.aci:
            return HealthCheckResult(
                check_type=CheckType.EVENTS,
                status=CheckStatus.UNKNOWN,
                items=[],
                duration_ms=(time.time() - start_time) * 1000,
            )
        
        try:
            ns_list = namespaces or self.config.namespaces or [None]
            
            for ns in ns_list:
                result = self.aci.get_events(
                    namespace=ns,
                    event_type="Warning",
                    duration_minutes=30,
                    limit=50,
                )
                
                if result.status.value != "success":
                    continue
                
                events = result.data or []
                
                for event in events:
                    reason = event.get("reason", "Unknown")
                    message = event.get("message", "")
                    involved_obj = event.get("involvedObject", {})
                    obj_name = involved_obj.get("name", "unknown")
                    obj_namespace = involved_obj.get("namespace", ns or "default")
                    
                    # Determine severity based on reason
                    critical_reasons = ["OOMKilled", "CrashLoopBackOff", "NodeNotReady", "FailedMount"]
                    
                    if reason in critical_reasons:
                        check_status = CheckStatus.CRITICAL
                    else:
                        check_status = CheckStatus.WARNING
                    
                    items.append(CheckItem(
                        name=obj_name,
                        namespace=obj_namespace,
                        status=check_status,
                        message=f"{reason}: {message[:100]}",
                        details={"reason": reason, "full_message": message}
                    ))
        
        except Exception as e:
            logger.error(f"Error checking events: {e}")
        
        if any(i.status == CheckStatus.CRITICAL for i in items):
            overall_status = CheckStatus.CRITICAL
        elif items:
            overall_status = CheckStatus.WARNING
        else:
            overall_status = CheckStatus.HEALTHY
        
        return HealthCheckResult(
            check_type=CheckType.EVENTS,
            status=overall_status,
            items=items,
            issues_created=issues_created,
            duration_ms=(time.time() - start_time) * 1000,
        )
    
    def check_services(
        self, 
        namespaces: Optional[List[str]] = None
    ) -> HealthCheckResult:
        """Check service health (endpoints availability)."""
        start_time = time.time()
        items = []
        
        # Placeholder - would check service endpoints
        # In real implementation, check if services have endpoints
        
        return HealthCheckResult(
            check_type=CheckType.SERVICES,
            status=CheckStatus.HEALTHY,
            items=items,
            duration_ms=(time.time() - start_time) * 1000,
        )
    
    def check_resources(
        self, 
        namespaces: Optional[List[str]] = None
    ) -> HealthCheckResult:
        """Check resource usage (CPU/memory)."""
        start_time = time.time()
        items = []
        
        if not self.aci:
            return HealthCheckResult(
                check_type=CheckType.RESOURCES,
                status=CheckStatus.UNKNOWN,
                items=[],
                duration_ms=(time.time() - start_time) * 1000,
            )
        
        try:
            ns_list = namespaces or self.config.namespaces or [None]
            
            for ns in ns_list:
                result = self.aci.get_metrics(namespace=ns)
                
                if result.status.value != "success":
                    continue
                
                metrics = result.data or {}
                
                # Check CPU usage
                cpu_usage = metrics.get("cpu_usage_percent", 0)
                if cpu_usage > 90:
                    items.append(CheckItem(
                        name="cpu",
                        namespace=ns or "cluster",
                        status=CheckStatus.CRITICAL,
                        message=f"CPU usage critical: {cpu_usage}%",
                        details={"usage_percent": cpu_usage}
                    ))
                elif cpu_usage > 75:
                    items.append(CheckItem(
                        name="cpu",
                        namespace=ns or "cluster",
                        status=CheckStatus.WARNING,
                        message=f"CPU usage high: {cpu_usage}%",
                        details={"usage_percent": cpu_usage}
                    ))
                
                # Check memory usage
                mem_usage = metrics.get("memory_usage_percent", 0)
                if mem_usage > 90:
                    items.append(CheckItem(
                        name="memory",
                        namespace=ns or "cluster",
                        status=CheckStatus.CRITICAL,
                        message=f"Memory usage critical: {mem_usage}%",
                        details={"usage_percent": mem_usage}
                    ))
                elif mem_usage > 80:
                    items.append(CheckItem(
                        name="memory",
                        namespace=ns or "cluster",
                        status=CheckStatus.WARNING,
                        message=f"Memory usage high: {mem_usage}%",
                        details={"usage_percent": mem_usage}
                    ))
        
        except Exception as e:
            logger.error(f"Error checking resources: {e}")
        
        if any(i.status == CheckStatus.CRITICAL for i in items):
            overall_status = CheckStatus.CRITICAL
        elif any(i.status == CheckStatus.WARNING for i in items):
            overall_status = CheckStatus.WARNING
        else:
            overall_status = CheckStatus.HEALTHY
        
        return HealthCheckResult(
            check_type=CheckType.RESOURCES,
            status=overall_status,
            items=items,
            duration_ms=(time.time() - start_time) * 1000,
        )
