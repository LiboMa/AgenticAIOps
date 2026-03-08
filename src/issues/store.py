"""
Issue Store - SQLite Backend

Persistent storage for issues with query capabilities.
Designed for easy migration to Redis in production.
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
from src.utils.time import ensure_aware
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from .models import Issue, IssueSeverity, IssueStatus, IssueType

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "issues.db"


class IssueStore:
    """
    SQLite-based issue storage.
    
    Features:
    - CRUD operations for issues
    - Query by status, severity, namespace
    - Time-based queries (last 24h, etc.)
    - Designed for Redis migration
    
    Example:
        store = IssueStore()
        
        # Create issue
        issue = Issue(type=IssueType.OOM_KILLED, ...)
        store.save(issue)
        
        # Query issues
        pending = store.get_by_status(IssueStatus.PENDING_FIX)
        recent = store.get_recent(hours=24)
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the issue store.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"IssueStore initialized at {self.db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS issues (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    namespace TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    root_cause TEXT,
                    symptoms TEXT,
                    suggested_fix TEXT,
                    auto_fixable INTEGER DEFAULT 1,
                    fix_actions TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT,
                    metadata TEXT
                )
            """)
            
            # Create indexes for common queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON issues(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_severity ON issues(severity)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_namespace ON issues(namespace)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON issues(created_at)")
    
    def save(self, issue: Issue) -> str:
        """
        Save or update an issue.
        
        Args:
            issue: Issue to save
            
        Returns:
            Issue ID
        """
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO issues (
                    id, type, severity, status, title, description,
                    namespace, resource, root_cause, symptoms,
                    suggested_fix, auto_fixable, fix_actions,
                    created_at, updated_at, resolved_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                issue.id,
                issue.type.value,
                issue.severity.value,
                issue.status.value,
                issue.title,
                issue.description,
                issue.namespace,
                issue.resource,
                issue.root_cause,
                json.dumps(issue.symptoms),
                issue.suggested_fix,
                1 if issue.auto_fixable else 0,
                json.dumps(issue.fix_actions),
                issue.created_at.isoformat(),
                issue.updated_at.isoformat(),
                issue.resolved_at.isoformat() if issue.resolved_at else None,
                json.dumps(issue.metadata),
            ))
        
        logger.debug(f"Saved issue {issue.id}")
        return issue.id
    
    def get(self, issue_id: str) -> Optional[Issue]:
        """
        Get issue by ID.
        
        Args:
            issue_id: Issue ID
            
        Returns:
            Issue or None if not found
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM issues WHERE id = ?", (issue_id,)
            ).fetchone()
            
        return self._row_to_issue(row) if row else None
    
    def delete(self, issue_id: str) -> bool:
        """
        Delete an issue.
        
        Args:
            issue_id: Issue ID
            
        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
            return cursor.rowcount > 0
    
    def get_all(self, limit: int = 100) -> List[Issue]:
        """Get all issues, most recent first."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM issues ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        
        return [self._row_to_issue(row) for row in rows]
    
    def get_by_status(self, status: IssueStatus, limit: int = 50) -> List[Issue]:
        """Get issues by status."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM issues WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status.value, limit)
            ).fetchall()
        
        return [self._row_to_issue(row) for row in rows]
    
    def get_by_severity(self, severity: IssueSeverity, limit: int = 50) -> List[Issue]:
        """Get issues by severity."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM issues WHERE severity = ? ORDER BY created_at DESC LIMIT ?",
                (severity.value, limit)
            ).fetchall()
        
        return [self._row_to_issue(row) for row in rows]
    
    def get_by_namespace(self, namespace: str, limit: int = 50) -> List[Issue]:
        """Get issues by namespace."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM issues WHERE namespace = ? ORDER BY created_at DESC LIMIT ?",
                (namespace, limit)
            ).fetchall()
        
        return [self._row_to_issue(row) for row in rows]
    
    def get_pending_approval(self) -> List[Issue]:
        """Get high-severity issues pending human approval."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM issues 
                WHERE severity IN ('high', 'critical') 
                AND status = 'pending_fix'
                ORDER BY created_at DESC
            """).fetchall()
        
        return [self._row_to_issue(row) for row in rows]
    
    def get_recent(self, hours: int = 24, include_resolved: bool = True) -> List[Issue]:
        """Get issues from the last N hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        with self._get_connection() as conn:
            if include_resolved:
                rows = conn.execute(
                    "SELECT * FROM issues WHERE created_at >= ? ORDER BY created_at DESC",
                    (cutoff,)
                ).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM issues 
                    WHERE created_at >= ? AND status NOT IN ('fixed', 'closed')
                    ORDER BY created_at DESC
                """, (cutoff,)).fetchall()
        
        return [self._row_to_issue(row) for row in rows]
    
    def get_resolved_today(self) -> List[Issue]:
        """Get issues resolved in the last 24 hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM issues 
                WHERE resolved_at >= ? AND status IN ('fixed', 'closed')
                ORDER BY resolved_at DESC
            """, (cutoff,)).fetchall()
        
        return [self._row_to_issue(row) for row in rows]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get issue statistics."""
        with self._get_connection() as conn:
            # Total counts
            total = conn.execute("SELECT COUNT(*) as count FROM issues").fetchone()["count"]
            
            # By status
            status_counts = {}
            for status in IssueStatus:
                count = conn.execute(
                    "SELECT COUNT(*) as count FROM issues WHERE status = ?",
                    (status.value,)
                ).fetchone()["count"]
                if count > 0:
                    status_counts[status.value] = count
            
            # By severity
            severity_counts = {}
            for severity in IssueSeverity:
                count = conn.execute(
                    "SELECT COUNT(*) as count FROM issues WHERE severity = ?",
                    (severity.value,)
                ).fetchone()["count"]
                if count > 0:
                    severity_counts[severity.value] = count
            
            # Recent 24h
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            recent_24h = conn.execute(
                "SELECT COUNT(*) as count FROM issues WHERE created_at >= ?",
                (cutoff,)
            ).fetchone()["count"]
            
            resolved_24h = conn.execute("""
                SELECT COUNT(*) as count FROM issues 
                WHERE resolved_at >= ? AND status IN ('fixed', 'closed')
            """, (cutoff,)).fetchone()["count"]
        
        return {
            "total": total,
            "by_status": status_counts,
            "by_severity": severity_counts,
            "detected_24h": recent_24h,
            "resolved_24h": resolved_24h,
            "pending_approval": len(self.get_pending_approval()),
        }
    
    def _row_to_issue(self, row: sqlite3.Row) -> Issue:
        """Convert database row to Issue object."""
        return Issue(
            id=row["id"],
            type=IssueType(row["type"]),
            severity=IssueSeverity(row["severity"]),
            status=IssueStatus(row["status"]),
            title=row["title"],
            description=row["description"] or "",
            namespace=row["namespace"],
            resource=row["resource"],
            root_cause=row["root_cause"] or "",
            symptoms=json.loads(row["symptoms"]) if row["symptoms"] else [],
            suggested_fix=row["suggested_fix"] or "",
            auto_fixable=bool(row["auto_fixable"]),
            fix_actions=json.loads(row["fix_actions"]) if row["fix_actions"] else [],
            created_at=ensure_aware(row["created_at"]),
            updated_at=ensure_aware(row["updated_at"]),
            resolved_at=ensure_aware(row["resolved_at"]) if row["resolved_at"] else None,
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
    
    def clear_all(self):
        """Clear all issues (for testing)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM issues")
        logger.warning("All issues cleared from database")
