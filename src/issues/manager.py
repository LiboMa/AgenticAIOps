"""
Issue Manager - Business Logic

Orchestrates issue lifecycle: detection, analysis, remediation, tracking.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable

from .models import Issue, IssueSeverity, IssueStatus, IssueType
from .store import IssueStore

logger = logging.getLogger(__name__)


# Severity classification rules
SEVERITY_RULES = {
    IssueType.OOM_KILLED: IssueSeverity.MEDIUM,
    IssueType.CRASH_LOOP: IssueSeverity.MEDIUM,
    IssueType.IMAGE_PULL_ERROR: IssueSeverity.HIGH,  # Needs manual check
    IssueType.CPU_THROTTLING: IssueSeverity.LOW,
    IssueType.MEMORY_PRESSURE: IssueSeverity.MEDIUM,
    IssueType.NODE_NOT_READY: IssueSeverity.HIGH,
    IssueType.NETWORK_ERROR: IssueSeverity.HIGH,
    IssueType.SERVICE_UNREACHABLE: IssueSeverity.HIGH,
    IssueType.HIGH_LATENCY: IssueSeverity.LOW,
    IssueType.ERROR_RATE_HIGH: IssueSeverity.MEDIUM,
    IssueType.DISK_PRESSURE: IssueSeverity.MEDIUM,
    IssueType.UNKNOWN: IssueSeverity.HIGH,  # Unknown = needs investigation
}


class IssueManager:
    """
    Manages issue lifecycle and orchestrates detection/remediation.
    
    Responsibilities:
    - Create issues from detected anomalies
    - Classify severity based on rules
    - Trigger auto-remediation for low/medium issues
    - Track issue status through lifecycle
    - Provide issue statistics for dashboard
    
    Example:
        manager = IssueManager()
        
        # Create from detection
        issue = manager.create_from_event(
            event_type="OOMKilled",
            namespace="default",
            resource="my-pod-xyz"
        )
        
        # Process issue (analyze + remediate if possible)
        manager.process_issue(issue.id)
        
        # Get dashboard data
        stats = manager.get_dashboard_data()
    """
    
    def __init__(self, store: Optional[IssueStore] = None):
        """
        Initialize the issue manager.
        
        Args:
            store: IssueStore instance (creates default if None)
        """
        self.store = store or IssueStore()
        self._remediation_handlers: Dict[IssueType, Callable] = {}
        logger.info("IssueManager initialized")
    
    def create_issue(
        self,
        issue_type: IssueType,
        title: str,
        namespace: str,
        resource: str,
        symptoms: List[str] = None,
        description: str = "",
        metadata: Dict[str, Any] = None,
    ) -> Issue:
        """
        Create and save a new issue.
        
        Args:
            issue_type: Type of issue
            title: Human-readable title
            namespace: K8s namespace
            resource: Affected resource name
            symptoms: List of observed symptoms
            description: Detailed description
            metadata: Additional context
            
        Returns:
            Created Issue
        """
        severity = self._classify_severity(issue_type, metadata or {})
        
        issue = Issue(
            type=issue_type,
            severity=severity,
            title=title,
            namespace=namespace,
            resource=resource,
            symptoms=symptoms or [],
            description=description,
            auto_fixable=severity in [IssueSeverity.LOW, IssueSeverity.MEDIUM],
            metadata=metadata or {},
        )
        
        self.store.save(issue)
        logger.info(f"Created issue {issue.id}: {title} (severity={severity.value})")
        
        return issue
    
    def create_from_event(
        self,
        event_type: str,
        namespace: str,
        resource: str,
        message: str = "",
        metadata: Dict[str, Any] = None,
    ) -> Issue:
        """
        Create issue from a K8s event.
        
        Args:
            event_type: K8s event reason (OOMKilled, CrashLoopBackOff, etc.)
            namespace: K8s namespace
            resource: Resource name
            message: Event message
            metadata: Additional data
            
        Returns:
            Created Issue
        """
        # Map event type to IssueType
        issue_type = self._map_event_to_type(event_type)
        
        title = f"{event_type}: {resource}"
        symptoms = [event_type]
        if message:
            symptoms.append(message[:200])
        
        return self.create_issue(
            issue_type=issue_type,
            title=title,
            namespace=namespace,
            resource=resource,
            symptoms=symptoms,
            description=message,
            metadata=metadata,
        )
    
    def update_status(self, issue_id: str, status: IssueStatus) -> Optional[Issue]:
        """
        Update issue status.
        
        Args:
            issue_id: Issue ID
            status: New status
            
        Returns:
            Updated Issue or None if not found
        """
        issue = self.store.get(issue_id)
        if not issue:
            logger.warning(f"Issue {issue_id} not found")
            return None
        
        issue.update_status(status)
        self.store.save(issue)
        logger.info(f"Updated issue {issue_id} status to {status.value}")
        
        return issue
    
    def add_root_cause(
        self,
        issue_id: str,
        root_cause: str,
        suggested_fix: str = "",
    ) -> Optional[Issue]:
        """
        Add root cause analysis result to issue.
        
        Args:
            issue_id: Issue ID
            root_cause: Diagnosed root cause
            suggested_fix: Recommended fix
            
        Returns:
            Updated Issue or None
        """
        issue = self.store.get(issue_id)
        if not issue:
            return None
        
        issue.root_cause = root_cause
        issue.suggested_fix = suggested_fix
        issue.update_status(IssueStatus.PENDING_FIX)
        
        self.store.save(issue)
        logger.info(f"Added RCA to issue {issue_id}: {root_cause}")
        
        return issue
    
    def record_fix_attempt(
        self,
        issue_id: str,
        action: str,
        result: str,
        success: bool,
    ) -> Optional[Issue]:
        """
        Record a remediation attempt.
        
        Args:
            issue_id: Issue ID
            action: Action taken
            result: Result of action
            success: Whether action succeeded
            
        Returns:
            Updated Issue or None
        """
        issue = self.store.get(issue_id)
        if not issue:
            return None
        
        issue.add_fix_action(action, result, success)
        
        if success:
            issue.update_status(IssueStatus.FIXED)
        else:
            issue.update_status(IssueStatus.FAILED)
        
        self.store.save(issue)
        logger.info(f"Recorded fix attempt for {issue_id}: {action} (success={success})")
        
        return issue
    
    def approve_fix(self, issue_id: str) -> Optional[Issue]:
        """
        Approve a high-severity issue for auto-remediation.
        
        Args:
            issue_id: Issue ID
            
        Returns:
            Updated Issue or None
        """
        issue = self.store.get(issue_id)
        if not issue:
            return None
        
        issue.update_status(IssueStatus.ACKNOWLEDGED)
        issue.auto_fixable = True  # Now allowed to auto-fix
        self.store.save(issue)
        
        logger.info(f"Approved issue {issue_id} for remediation")
        return issue
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get data for Issue Center dashboard.
        
        Returns:
            Dashboard data dict with:
            - stats: Overall statistics
            - pending_approval: High-severity issues awaiting approval
            - resolved_today: Issues fixed in last 24h
            - active_issues: Currently active issues
        """
        stats = self.store.get_stats()
        
        return {
            "stats": stats,
            "pending_approval": [i.to_dict() for i in self.store.get_pending_approval()],
            "resolved_today": [i.to_dict() for i in self.store.get_resolved_today()],
            "active_issues": [
                i.to_dict() for i in self.store.get_recent(hours=24, include_resolved=False)
            ],
        }
    
    def register_remediation_handler(
        self,
        issue_type: IssueType,
        handler: Callable[[Issue], bool],
    ) -> None:
        """
        Register a remediation handler for an issue type.
        
        Args:
            issue_type: Issue type to handle
            handler: Function that takes Issue and returns success bool
        """
        self._remediation_handlers[issue_type] = handler
        logger.info(f"Registered remediation handler for {issue_type.value}")
    
    def _classify_severity(
        self,
        issue_type: IssueType,
        metadata: Dict[str, Any],
    ) -> IssueSeverity:
        """Classify severity based on type and context."""
        base_severity = SEVERITY_RULES.get(issue_type, IssueSeverity.MEDIUM)
        
        # Upgrade severity based on context
        if metadata.get("restarts", 0) > 10:
            if base_severity == IssueSeverity.LOW:
                return IssueSeverity.MEDIUM
        
        if metadata.get("production", False):
            if base_severity in [IssueSeverity.LOW, IssueSeverity.MEDIUM]:
                return IssueSeverity.HIGH
        
        return base_severity
    
    def _map_event_to_type(self, event_type: str) -> IssueType:
        """Map K8s event reason to IssueType."""
        mapping = {
            "OOMKilled": IssueType.OOM_KILLED,
            "OOMKilling": IssueType.OOM_KILLED,
            "CrashLoopBackOff": IssueType.CRASH_LOOP,
            "BackOff": IssueType.CRASH_LOOP,
            "ImagePullBackOff": IssueType.IMAGE_PULL_ERROR,
            "ErrImagePull": IssueType.IMAGE_PULL_ERROR,
            "FailedMount": IssueType.DISK_PRESSURE,
            "NodeNotReady": IssueType.NODE_NOT_READY,
            "NetworkNotReady": IssueType.NETWORK_ERROR,
            "Unhealthy": IssueType.SERVICE_UNREACHABLE,
            "FailedScheduling": IssueType.NODE_NOT_READY,
        }
        
        return mapping.get(event_type, IssueType.UNKNOWN)
    
    def list_issues(
        self, 
        status: str = None, 
        severity: str = None, 
        namespace: str = None, 
        limit: int = 100
    ) -> List[Issue]:
        """List issues with optional filters."""
        issues = self.store.get_all(limit=limit)
        
        # Apply filters
        if status:
            issues = [i for i in issues if i.status.value == status]
        if severity:
            issues = [i for i in issues if i.severity.value == severity]
        if namespace:
            issues = [i for i in issues if i.namespace == namespace]
        
        return issues
    
    def get_issue(self, issue_id: str) -> Optional[Issue]:
        """Get a single issue by ID."""
        return self.store.get(issue_id)
