"""
ACI Shell Executor

Safe shell command execution with security filtering.
"""

import logging
import subprocess
import time
from typing import Optional

from ..models import OperationResult, ResultStatus
from ..security.filters import SecurityFilter

logger = logging.getLogger(__name__)


class ShellExecutor:
    """
    Safe shell command executor.
    
    Implements security checks and timeout handling.
    """
    
    def __init__(self, safe_mode: bool = True):
        self.safe_mode = safe_mode
        self.security = SecurityFilter()
    
    def execute(
        self,
        command: str,
        timeout: int = 30,
        capture_stderr: bool = True,
        cwd: Optional[str] = None,
    ) -> OperationResult:
        """
        Execute shell command.
        
        Args:
            command: Shell command to execute
            timeout: Command timeout in seconds
            capture_stderr: Capture stderr output
            cwd: Working directory
        
        Returns:
            OperationResult
        """
        start_time = time.time()
        
        # Security check
        if self.safe_mode:
            is_safe, reason = self.security.check_shell(command)
            if not is_safe:
                return OperationResult(
                    status=ResultStatus.ERROR,
                    command=command,
                    error=f"Security blocked: {reason}",
                )
        
        try:
            # Execute command
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            status = ResultStatus.SUCCESS if result.returncode == 0 else ResultStatus.ERROR
            
            return OperationResult(
                status=status,
                stdout=result.stdout,
                stderr=result.stderr if capture_stderr else "",
                return_code=result.returncode,
                duration_ms=duration_ms,
                command=command,
                error=result.stderr if result.returncode != 0 else None,
            )
            
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            return OperationResult(
                status=ResultStatus.TIMEOUT,
                command=command,
                duration_ms=duration_ms,
                error=f"Command timeout after {timeout}s",
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Shell execution error: {e}")
            return OperationResult(
                status=ResultStatus.ERROR,
                command=command,
                duration_ms=duration_ms,
                error=str(e),
            )
