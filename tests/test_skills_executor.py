"""Tests for src/skills/_executor.py — ShellExecutor & KubectlExec."""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src.skills._executor import (
    ExecResult,
    ShellExecutor,
    KubectlExec,
    MAX_OUTPUT_BYTES,
)


# ── ExecResult ──────────────────────────────────────────────────────

class TestExecResult:
    def test_ok_when_zero_return_code(self):
        r = ExecResult(return_code=0)
        assert r.ok is True

    def test_not_ok_when_nonzero_return_code(self):
        r = ExecResult(return_code=1)
        assert r.ok is False

    def test_not_ok_when_timed_out(self):
        r = ExecResult(return_code=0, timed_out=True)
        assert r.ok is False

    def test_defaults(self):
        r = ExecResult()
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.return_code == 0
        assert r.duration_ms == 0
        assert r.timed_out is False


# ── ShellExecutor ───────────────────────────────────────────────────

class TestShellExecutor:
    def test_simple_echo(self):
        ex = ShellExecutor(timeout=10)
        r = ex.execute("echo hello")
        assert r.ok
        assert "hello" in r.stdout

    def test_failure_return_code(self):
        ex = ShellExecutor()
        r = ex.execute("exit 42")
        assert not r.ok
        assert r.return_code == 42

    def test_stderr_captured(self):
        ex = ShellExecutor()
        r = ex.execute("echo err >&2")
        assert "err" in r.stderr

    def test_timeout_handling(self):
        ex = ShellExecutor(timeout=1)
        r = ex.execute("sleep 30", timeout=1)
        assert r.timed_out
        assert not r.ok
        assert r.return_code == -1
        assert "timed out" in r.stderr.lower()

    def test_custom_timeout_overrides_default(self):
        ex = ShellExecutor(timeout=1)
        r = ex.execute("echo fast", timeout=10)
        assert r.ok

    def test_duration_measured(self):
        ex = ShellExecutor()
        r = ex.execute("echo hi")
        assert r.duration_ms >= 0

    def test_output_truncated(self):
        # generate more than MAX_OUTPUT_BYTES
        ex = ShellExecutor(timeout=10)
        r = ex.execute(f"python3 -c \"print('A' * {MAX_OUTPUT_BYTES + 1024})\"")
        assert len(r.stdout) <= MAX_OUTPUT_BYTES

    @patch("src.skills._executor.subprocess.run", side_effect=OSError("no bash"))
    def test_generic_exception(self, _mock):
        ex = ShellExecutor()
        r = ex.execute("anything")
        assert not r.ok
        assert r.return_code == -1
        assert "no bash" in r.stderr


# ── KubectlExec ─────────────────────────────────────────────────────

class TestKubectlExec:
    """Test KubectlExec with mocked subprocess to avoid needing kubectl."""

    def _mock_run(self, stdout="", stderr="", rc=0):
        m = MagicMock()
        m.stdout = stdout
        m.stderr = stderr
        m.returncode = rc
        return m

    @patch("src.skills._executor.subprocess.run")
    def test_basic_get(self, mock_run):
        mock_run.return_value = self._mock_run(stdout='{"items":[]}')
        kx = KubectlExec(timeout=30)
        r = kx.execute(["get", "pods"])
        assert r.ok
        assert '{"items":[]}' in r.stdout
        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["kubectl", "get"]
        assert "-o" in cmd and "json" in cmd

    @patch("src.skills._executor.subprocess.run")
    def test_namespace_injected(self, mock_run):
        mock_run.return_value = self._mock_run()
        kx = KubectlExec()
        kx.execute(["get", "pods"], namespace="kube-system")
        cmd = mock_run.call_args[0][0]
        assert "-n" in cmd
        idx = cmd.index("-n")
        assert cmd[idx + 1] == "kube-system"

    @patch("src.skills._executor.subprocess.run")
    def test_namespace_not_duplicated(self, mock_run):
        mock_run.return_value = self._mock_run()
        kx = KubectlExec()
        kx.execute(["get", "pods", "-n", "default"], namespace="kube-system")
        cmd = mock_run.call_args[0][0]
        # should NOT add another -n
        assert cmd.count("-n") == 1

    @patch("src.skills._executor.subprocess.run")
    def test_describe_no_extra_output_flag(self, mock_run):
        mock_run.return_value = self._mock_run(stdout="Name: foo")
        kx = KubectlExec()
        r = kx.execute(["describe", "pod", "foo"])
        cmd = mock_run.call_args[0][0]
        # describe should still get -o json by default
        assert "-o" in cmd

    @patch("src.skills._executor.subprocess.run")
    def test_explicit_output_format_not_overridden(self, mock_run):
        mock_run.return_value = self._mock_run()
        kx = KubectlExec()
        kx.execute(["get", "pods", "-o", "yaml"])
        cmd = mock_run.call_args[0][0]
        assert cmd.count("-o") == 1
        idx = cmd.index("-o")
        assert cmd[idx + 1] == "yaml"

    @patch("src.skills._executor.subprocess.run")
    def test_non_get_describe_no_output_flag(self, mock_run):
        mock_run.return_value = self._mock_run()
        kx = KubectlExec()
        kx.execute(["delete", "pod", "foo"])
        cmd = mock_run.call_args[0][0]
        assert "-o" not in cmd

    @patch("src.skills._executor.subprocess.run")
    def test_custom_timeout(self, mock_run):
        mock_run.return_value = self._mock_run()
        kx = KubectlExec(timeout=60)
        kx.execute(["get", "nodes"], timeout=15)
        assert mock_run.call_args[1]["timeout"] == 15

    @patch("src.skills._executor.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="kubectl", timeout=5))
    def test_timeout_expired(self, _mock):
        kx = KubectlExec(timeout=5)
        r = kx.execute(["get", "pods"])
        assert r.timed_out
        assert not r.ok
        assert "timed out" in r.stderr.lower()

    @patch("src.skills._executor.subprocess.run", side_effect=FileNotFoundError("kubectl not found"))
    def test_generic_exception(self, _mock):
        kx = KubectlExec()
        r = kx.execute(["get", "pods"])
        assert not r.ok
        assert r.return_code == -1
        assert "kubectl not found" in r.stderr

    @patch("src.skills._executor.subprocess.run")
    def test_output_truncated(self, mock_run):
        big = "X" * (MAX_OUTPUT_BYTES + 500)
        mock_run.return_value = self._mock_run(stdout=big, stderr=big)
        kx = KubectlExec()
        r = kx.execute(["get", "pods"])
        assert len(r.stdout) <= MAX_OUTPUT_BYTES
        assert len(r.stderr) <= MAX_OUTPUT_BYTES

    @patch("src.skills._executor.subprocess.run")
    def test_empty_args(self, mock_run):
        mock_run.return_value = self._mock_run()
        kx = KubectlExec()
        r = kx.execute([])
        cmd = mock_run.call_args[0][0]
        assert cmd == ["kubectl"]
        # empty operation means no -o flag added
        assert "-o" not in cmd

    @patch("src.skills._executor.subprocess.run")
    def test_duration_measured(self, mock_run):
        mock_run.return_value = self._mock_run()
        kx = KubectlExec()
        r = kx.execute(["version"])
        assert r.duration_ms >= 0
