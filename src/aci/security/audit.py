"""
ACI Audit Logger

Logs all ACI operations for compliance and debugging.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Audit logger for ACI operations.
    
    Records all operations with timestamps, agent info, and results.
    """
    
    def __init__(self, log_dir: Optional[str] = None):
        """
        Initialize audit logger.
        
        Args:
            log_dir: Directory for audit logs (default: ~/.agentic-aiops/audit/)
        """
        if log_dir:
            self.log_dir = Path(log_dir)
        else:
            self.log_dir = Path.home() / ".agentic-aiops" / "audit"
        
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.current_log_file = self._get_log_file()
    
    def _get_log_file(self) -> Path:
        """Get log file for current date."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.log_dir / f"aci-audit-{date_str}.jsonl"
    
    def log(
        self,
        operation: str,
        details: str,
        result: str,
        cluster: str = "",
        agent_id: str = "unknown",
        duration_ms: int = 0,
    ):
        """
        Log an ACI operation.
        
        Args:
            operation: Operation name (get_logs, kubectl, etc.)
            details: Operation details
            result: Result status (success, error, blocked)
            cluster: Cluster name
            agent_id: Agent identifier
            duration_ms: Operation duration
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "details": details,
            "result": result,
            "cluster": cluster,
            "agent_id": agent_id,
            "duration_ms": duration_ms,
        }
        
        try:
            # Check if date changed (rotate log file)
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if f"-{current_date}.jsonl" not in str(self.current_log_file):
                self.current_log_file = self._get_log_file()
            
            # Append to log file
            with open(self.current_log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
            
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def get_recent_logs(self, count: int = 100) -> list:
        """
        Get recent audit log entries.
        
        Args:
            count: Number of entries to return
        
        Returns:
            List of audit entries (newest first)
        """
        entries = []
        
        try:
            # Read from current log file
            if self.current_log_file.exists():
                with open(self.current_log_file, "r") as f:
                    for line in f:
                        if line.strip():
                            entries.append(json.loads(line))
            
            # Return newest first
            entries.reverse()
            return entries[:count]
            
        except Exception as e:
            logger.error(f"Failed to read audit logs: {e}")
            return []
    
    def get_operation_stats(self) -> dict:
        """
        Get operation statistics from audit logs.
        
        Returns:
            Dict with operation counts and success rates
        """
        stats = {
            "total": 0,
            "by_operation": {},
            "by_result": {},
        }
        
        try:
            if self.current_log_file.exists():
                with open(self.current_log_file, "r") as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            stats["total"] += 1
                            
                            op = entry.get("operation", "unknown")
                            result = entry.get("result", "unknown")
                            
                            stats["by_operation"][op] = stats["by_operation"].get(op, 0) + 1
                            stats["by_result"][result] = stats["by_result"].get(result, 0) + 1
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to compute audit stats: {e}")
            return stats
