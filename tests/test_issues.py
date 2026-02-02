"""
Tests for Issue Management System
"""

import pytest
from datetime import datetime, timedelta
import tempfile
import os

from src.issues import (
    Issue, IssueType, IssueSeverity, IssueStatus,
    IssueStore, IssueManager
)


class TestIssueModels:
    """Tests for Issue data models."""
    
    def test_issue_creation(self):
        """Test creating an issue."""
        issue = Issue(
            type=IssueType.OOM_KILLED,
            severity=IssueSeverity.MEDIUM,
            title="OOM: my-pod",
            namespace="default",
            resource="my-pod-xyz"
        )
        
        assert issue.type == IssueType.OOM_KILLED
        assert issue.severity == IssueSeverity.MEDIUM
        assert issue.status == IssueStatus.DETECTED
        assert issue.namespace == "default"
        assert len(issue.id) == 8
    
    def test_issue_to_dict(self):
        """Test serialization to dict."""
        issue = Issue(
            type=IssueType.CRASH_LOOP,
            severity=IssueSeverity.HIGH,
            title="CrashLoop: api-server",
            namespace="production",
            resource="api-server-abc",
            symptoms=["CrashLoopBackOff", "Exit code 1"]
        )
        
        data = issue.to_dict()
        
        assert data["type"] == "crash_loop"
        assert data["severity"] == "high"
        assert data["status"] == "detected"
        assert len(data["symptoms"]) == 2
    
    def test_issue_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "id": "test123",
            "type": "oom_killed",
            "severity": "medium",
            "status": "fixing",
            "title": "Test Issue",
            "namespace": "test-ns",
            "resource": "test-pod",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        issue = Issue.from_dict(data)
        
        assert issue.id == "test123"
        assert issue.type == IssueType.OOM_KILLED
        assert issue.status == IssueStatus.FIXING
    
    def test_requires_approval(self):
        """Test approval requirement check."""
        low_issue = Issue(
            type=IssueType.CPU_THROTTLING,
            severity=IssueSeverity.LOW,
            title="Test",
            namespace="test",
            resource="test"
        )
        
        high_issue = Issue(
            type=IssueType.NODE_NOT_READY,
            severity=IssueSeverity.HIGH,
            title="Test",
            namespace="test",
            resource="test"
        )
        
        assert not low_issue.requires_approval()
        assert high_issue.requires_approval()
    
    def test_update_status(self):
        """Test status update with timestamp."""
        issue = Issue(
            type=IssueType.OOM_KILLED,
            severity=IssueSeverity.MEDIUM,
            title="Test",
            namespace="test",
            resource="test"
        )
        
        old_updated = issue.updated_at
        issue.update_status(IssueStatus.FIXED)
        
        assert issue.status == IssueStatus.FIXED
        assert issue.updated_at > old_updated
        assert issue.resolved_at is not None


class TestIssueStore:
    """Tests for IssueStore SQLite backend."""
    
    @pytest.fixture
    def store(self):
        """Create temporary store for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        store = IssueStore(db_path)
        yield store
        
        # Cleanup
        os.unlink(db_path)
    
    def test_save_and_get(self, store):
        """Test saving and retrieving issue."""
        issue = Issue(
            type=IssueType.OOM_KILLED,
            severity=IssueSeverity.MEDIUM,
            title="Test Issue",
            namespace="default",
            resource="test-pod"
        )
        
        store.save(issue)
        retrieved = store.get(issue.id)
        
        assert retrieved is not None
        assert retrieved.id == issue.id
        assert retrieved.type == issue.type
        assert retrieved.title == issue.title
    
    def test_get_by_status(self, store):
        """Test querying by status."""
        # Create issues with different statuses
        for status in [IssueStatus.DETECTED, IssueStatus.DETECTED, IssueStatus.FIXED]:
            issue = Issue(
                type=IssueType.CRASH_LOOP,
                severity=IssueSeverity.MEDIUM,
                title="Test",
                namespace="test",
                resource="test"
            )
            issue.status = status
            store.save(issue)
        
        detected = store.get_by_status(IssueStatus.DETECTED)
        fixed = store.get_by_status(IssueStatus.FIXED)
        
        assert len(detected) == 2
        assert len(fixed) == 1
    
    def test_get_by_severity(self, store):
        """Test querying by severity."""
        for severity in [IssueSeverity.LOW, IssueSeverity.MEDIUM, IssueSeverity.HIGH]:
            issue = Issue(
                type=IssueType.OOM_KILLED,
                severity=severity,
                title="Test",
                namespace="test",
                resource="test"
            )
            store.save(issue)
        
        high = store.get_by_severity(IssueSeverity.HIGH)
        assert len(high) == 1
    
    def test_get_pending_approval(self, store):
        """Test getting issues pending approval."""
        # High severity pending
        high = Issue(
            type=IssueType.NODE_NOT_READY,
            severity=IssueSeverity.HIGH,
            title="High Issue",
            namespace="prod",
            resource="node-1"
        )
        high.status = IssueStatus.PENDING_FIX
        store.save(high)
        
        # Low severity pending (should not appear)
        low = Issue(
            type=IssueType.CPU_THROTTLING,
            severity=IssueSeverity.LOW,
            title="Low Issue",
            namespace="test",
            resource="pod-1"
        )
        low.status = IssueStatus.PENDING_FIX
        store.save(low)
        
        pending = store.get_pending_approval()
        assert len(pending) == 1
        assert pending[0].severity == IssueSeverity.HIGH
    
    def test_get_stats(self, store):
        """Test statistics generation."""
        # Create some issues
        for i in range(5):
            issue = Issue(
                type=IssueType.OOM_KILLED,
                severity=IssueSeverity.MEDIUM,
                title=f"Issue {i}",
                namespace="test",
                resource=f"pod-{i}"
            )
            if i < 2:
                issue.update_status(IssueStatus.FIXED)
            store.save(issue)
        
        stats = store.get_stats()
        
        assert stats["total"] == 5
        assert stats["by_status"]["detected"] == 3
        assert stats["by_status"]["fixed"] == 2


class TestIssueManager:
    """Tests for IssueManager business logic."""
    
    @pytest.fixture
    def manager(self):
        """Create manager with temporary store."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        store = IssueStore(db_path)
        manager = IssueManager(store)
        yield manager
        
        os.unlink(db_path)
    
    def test_create_issue(self, manager):
        """Test issue creation with severity classification."""
        issue = manager.create_issue(
            issue_type=IssueType.OOM_KILLED,
            title="OOM: test-pod",
            namespace="default",
            resource="test-pod",
            symptoms=["OOMKilled", "Container restarted"]
        )
        
        assert issue.type == IssueType.OOM_KILLED
        assert issue.severity == IssueSeverity.MEDIUM  # Default for OOM
        assert issue.auto_fixable is True
    
    def test_create_from_event(self, manager):
        """Test creating issue from K8s event."""
        issue = manager.create_from_event(
            event_type="OOMKilled",
            namespace="production",
            resource="api-server-xyz",
            message="Container killed due to OOM"
        )
        
        assert issue.type == IssueType.OOM_KILLED
        assert "OOMKilled" in issue.symptoms
    
    def test_create_from_unknown_event(self, manager):
        """Test creating issue from unknown event type."""
        issue = manager.create_from_event(
            event_type="SomeUnknownEvent",
            namespace="test",
            resource="test-pod"
        )
        
        assert issue.type == IssueType.UNKNOWN
        assert issue.severity == IssueSeverity.HIGH  # Unknown = needs investigation
    
    def test_update_status(self, manager):
        """Test updating issue status."""
        issue = manager.create_issue(
            issue_type=IssueType.CRASH_LOOP,
            title="Test",
            namespace="test",
            resource="test"
        )
        
        updated = manager.update_status(issue.id, IssueStatus.FIXING)
        
        assert updated.status == IssueStatus.FIXING
    
    def test_add_root_cause(self, manager):
        """Test adding RCA result."""
        issue = manager.create_issue(
            issue_type=IssueType.OOM_KILLED,
            title="Test",
            namespace="test",
            resource="test"
        )
        
        updated = manager.add_root_cause(
            issue.id,
            root_cause="Memory limit too low for workload",
            suggested_fix="Increase memory limit to 512Mi"
        )
        
        assert updated.root_cause == "Memory limit too low for workload"
        assert updated.status == IssueStatus.PENDING_FIX
    
    def test_record_fix_attempt_success(self, manager):
        """Test recording successful fix."""
        issue = manager.create_issue(
            issue_type=IssueType.CRASH_LOOP,
            title="Test",
            namespace="test",
            resource="test"
        )
        
        updated = manager.record_fix_attempt(
            issue.id,
            action="kubectl rollout restart deployment/test",
            result="Deployment restarted successfully",
            success=True
        )
        
        assert updated.status == IssueStatus.FIXED
        assert len(updated.fix_actions) == 1
        assert updated.fix_actions[0]["success"] is True
    
    def test_approve_fix(self, manager):
        """Test approving high-severity issue."""
        issue = manager.create_issue(
            issue_type=IssueType.NODE_NOT_READY,
            title="Test",
            namespace="test",
            resource="test"
        )
        issue.severity = IssueSeverity.HIGH
        issue.auto_fixable = False
        manager.store.save(issue)
        
        approved = manager.approve_fix(issue.id)
        
        assert approved.status == IssueStatus.ACKNOWLEDGED
        assert approved.auto_fixable is True
    
    def test_get_dashboard_data(self, manager):
        """Test dashboard data generation."""
        # Create some issues
        manager.create_issue(
            issue_type=IssueType.OOM_KILLED,
            title="Active Issue",
            namespace="test",
            resource="test"
        )
        
        data = manager.get_dashboard_data()
        
        assert "stats" in data
        assert "pending_approval" in data
        assert "resolved_today" in data
        assert "active_issues" in data
        assert len(data["active_issues"]) == 1
