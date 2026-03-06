"""Tests for ACI Security Audit Logger - improve coverage from 44%."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from src.aci.security.audit import AuditLogger


class TestAuditLoggerInit:
    def test_default_log_dir(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            logger = AuditLogger()
            assert "audit" in str(logger.log_dir)
            assert logger.log_dir.exists()

    def test_custom_log_dir(self, tmp_path):
        log_dir = tmp_path / "custom_audit"
        logger = AuditLogger(log_dir=str(log_dir))
        assert logger.log_dir == log_dir
        assert log_dir.exists()


class TestAuditLoggerLog:
    def test_log_creates_entry(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path))
        logger.log(operation="kubectl", details="get pods", result="success",
                    cluster="test-cluster", agent_id="agent-1", duration_ms=150)
        assert logger.current_log_file.exists()
        with open(logger.current_log_file) as f:
            entry = json.loads(f.readline())
        assert entry["operation"] == "kubectl"
        assert entry["duration_ms"] == 150

    def test_log_handles_write_error(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path))
        with patch("builtins.open", side_effect=PermissionError("denied")):
            logger.log(operation="test", details="d", result="error")

    def test_log_rotates_on_date_change(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path))
        logger.current_log_file = tmp_path / "aci-audit-1999-01-01.jsonl"
        logger.log(operation="test", details="d", result="success")
        assert "1999-01-01" not in str(logger.current_log_file)


class TestAuditLoggerGetRecentLogs:
    def test_get_recent_logs_empty(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path))
        assert logger.get_recent_logs() == []

    def test_get_recent_logs_returns_newest_first(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path))
        for i in range(5):
            logger.log(operation=f"op-{i}", details="d", result="success")
        logs = logger.get_recent_logs(count=3)
        assert len(logs) == 3
        assert logs[0]["operation"] == "op-4"

    def test_get_recent_logs_handles_read_error(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path))
        logger.log(operation="test", details="d", result="success")
        with patch("builtins.open", side_effect=IOError("fail")):
            assert logger.get_recent_logs() == []


class TestAuditLoggerStats:
    def test_get_operation_stats(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path))
        logger.log(operation="kubectl", details="d", result="success")
        logger.log(operation="kubectl", details="d", result="error")
        logger.log(operation="get_logs", details="d", result="success")
        stats = logger.get_operation_stats()
        assert stats["total"] == 3
        assert stats["by_operation"]["kubectl"] == 2
        assert stats["by_result"]["error"] == 1

    def test_get_operation_stats_handles_error(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path))
        logger.log(operation="test", details="d", result="success")
        with patch("builtins.open", side_effect=IOError("fail")):
            stats = logger.get_operation_stats()
            assert stats["total"] == 0
