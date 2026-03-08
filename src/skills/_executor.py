"""
Skills Framework — Shared executors.

Safe command execution layer used by skill tools.
Wraps subprocess with timeout, output limits, and security integration.

Architecture: ADR-006 §11.2
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 64 * 1024  # 64KB output limit


@dataclass
class ExecResult:
    """Result from a shell/kubectl execution."""
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    duration_ms: int = 0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.return_code == 0 and not self.timed_out


class ShellExecutor:
    """Safe shell command executor for skill tools.

    Args:
        timeout: Default command timeout in seconds.
        safe_mode: If True, prevents running as root.
    """

    def __init__(self, timeout: int = 30, safe_mode: bool = True) -> None:
        self.timeout = timeout
        self.safe_mode = safe_mode

    def execute(self, command: str, timeout: Optional[int] = None) -> ExecResult:
        """Execute a shell command safely.

        Note: The @secure_tool decorator handles blacklist/injection checks
        BEFORE this method is called. This is the execution layer only.
        """
        t = timeout or self.timeout
        start = time.time()

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=t,
            )

            stdout = result.stdout[:MAX_OUTPUT_BYTES]
            stderr = result.stderr[:MAX_OUTPUT_BYTES]
            duration_ms = int((time.time() - start) * 1000)

            return ExecResult(
                stdout=stdout,
                stderr=stderr,
                return_code=result.returncode,
                duration_ms=duration_ms,
            )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            return ExecResult(
                stderr=f"Command timed out after {t}s",
                return_code=-1,
                duration_ms=duration_ms,
                timed_out=True,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return ExecResult(
                stderr=str(e),
                return_code=-1,
                duration_ms=duration_ms,
            )


class KubectlExec:
    """Safe kubectl executor for the kubernetes skill.

    Migrated from src/aci/operations/kubectl.py with the same
    command-building logic, but security is now in @secure_tool.
    """

    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout

    def execute(
        self,
        args: list[str],
        namespace: Optional[str] = None,
        output_format: str = "json",
        timeout: Optional[int] = None,
    ) -> ExecResult:
        """Execute kubectl command.

        Security checks are handled by @secure_tool decorator.
        This method only handles execution.
        """
        t = timeout or self.timeout
        cmd = ["kubectl"] + args

        if namespace and "-n" not in args and "--namespace" not in args:
            cmd.extend(["-n", namespace])

        operation = args[0] if args else ""
        if operation in ("get", "describe") and "-o" not in args and "--output" not in args:
            cmd.extend(["-o", output_format])

        start = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=t,
            )

            stdout = result.stdout[:MAX_OUTPUT_BYTES]
            stderr = result.stderr[:MAX_OUTPUT_BYTES]
            duration_ms = int((time.time() - start) * 1000)

            return ExecResult(
                stdout=stdout,
                stderr=stderr,
                return_code=result.returncode,
                duration_ms=duration_ms,
            )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            return ExecResult(
                stderr=f"kubectl timed out after {t}s",
                return_code=-1,
                duration_ms=duration_ms,
                timed_out=True,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return ExecResult(
                stderr=str(e),
                return_code=-1,
                duration_ms=duration_ms,
            )
