#!/usr/bin/env python3
"""
Tests for src/aci/operations/shell.py — ShellExecutor

Targets uncovered lines: 48-96 (execute method branches).
"""

import pytest
import sys
import os
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.aci.operations.shell import ShellExecutor
from src.aci.models import ResultStatus


class TestShellExecutorInit:
    """Test ShellExecutor initialization."""

    def test_default_safe_mode(self):
        exe = ShellExecutor()
        assert exe.safe_mode is True

    def test_unsafe_mode(self):
        exe = ShellExecutor(safe_mode=False)
        assert exe.safe_mode is False


class TestShellExecuteSuccess:
    """Test successful command execution."""

    def test_simple_echo(self):
        exe = ShellExecutor(safe_mode=False)
        result = exe.execute("echo hello")
        assert result.status == ResultStatus.SUCCESS
        assert "hello" in result.stdout
        assert result.return_code == 0
        assert result.duration_ms >= 0
        assert result.command == "echo hello"
        assert result.error is None

    def test_capture_stderr_true(self):
        exe = ShellExecutor(safe_mode=False)
        result = exe.execute("echo err >&2", capture_stderr=True)
        assert "err" in result.stderr

    def test_capture_stderr_false(self):
        exe = ShellExecutor(safe_mode=False)
        result = exe.execute("echo err >&2", capture_stderr=False)
        assert result.stderr == ""

    def test_cwd_parameter(self):
        exe = ShellExecutor(safe_mode=False)
        result = exe.execute("pwd", cwd="/tmp")
        assert result.status == ResultStatus.SUCCESS
        assert "/tmp" in result.stdout


class TestShellExecuteFailure:
    """Test command failure paths."""

    def test_nonzero_exit(self):
        exe = ShellExecutor(safe_mode=False)
        result = exe.execute("exit 1")
        assert result.status == ResultStatus.ERROR
        assert result.return_code == 1

    def test_nonzero_exit_has_error(self):
        exe = ShellExecutor(safe_mode=False)
        result = exe.execute("echo fail >&2; exit 2")
        assert result.status == ResultStatus.ERROR
        assert result.error is not None


class TestShellSecurityBlock:
    """Test security filter integration."""

    def test_blocked_dangerous_command(self):
        exe = ShellExecutor(safe_mode=True)
        result = exe.execute("rm -rf /")
        assert result.status == ResultStatus.ERROR
        assert "Security blocked" in result.error

    def test_safe_mode_allows_safe_command(self):
        exe = ShellExecutor(safe_mode=True)
        result = exe.execute("echo safe")
        assert result.status == ResultStatus.SUCCESS

    def test_unsafe_mode_skips_security(self):
        exe = ShellExecutor(safe_mode=False)
        # Even 'dangerous-looking' patterns won't be checked
        result = exe.execute("echo 'not actually rm -rf'")
        assert result.status == ResultStatus.SUCCESS


class TestShellTimeout:
    """Test timeout handling."""

    def test_timeout_returns_timeout_status(self):
        exe = ShellExecutor(safe_mode=False)
        result = exe.execute("sleep 10", timeout=1)
        assert result.status == ResultStatus.TIMEOUT
        assert "timeout" in result.error.lower()
        assert result.duration_ms > 0
        assert result.command == "sleep 10"


class TestShellGenericException:
    """Test generic exception handling."""

    @patch("src.aci.operations.shell.subprocess.run")
    def test_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("mock OS error")
        exe = ShellExecutor(safe_mode=False)
        result = exe.execute("anything")
        assert result.status == ResultStatus.ERROR
        assert "mock OS error" in result.error
        assert result.duration_ms >= 0
