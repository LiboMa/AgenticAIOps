"""
ACI Kubectl Executor

Safe kubectl command execution with security filtering.
"""

import json
import logging
import subprocess
import time
from typing import List, Optional

from ..models import OperationResult, ResultStatus

logger = logging.getLogger(__name__)


# Allowed kubectl operations
ALLOWED_READ_OPS = ["get", "describe", "logs", "top", "explain", "api-resources", "api-versions"]
ALLOWED_WRITE_OPS = ["apply", "patch", "scale", "rollout", "label", "annotate"]
DANGEROUS_OPS = ["delete", "drain", "cordon", "taint"]

# Protected namespaces
PROTECTED_NAMESPACES = ["kube-system", "kube-public", "kube-node-lease"]


class KubectlExecutor:
    """
    Safe kubectl command executor.
    
    Implements security checks and audit logging for kubectl operations.
    """
    
    def __init__(self, cluster_name: str, region: str):
        self.cluster_name = cluster_name
        self.region = region
    
    def execute(
        self,
        args: List[str],
        namespace: Optional[str] = None,
        output_format: str = "json",
        timeout: int = 60,
    ) -> OperationResult:
        """
        Execute kubectl command.
        
        Args:
            args: kubectl arguments (without 'kubectl' prefix)
            namespace: Target namespace
            output_format: Output format (json, yaml, wide)
            timeout: Command timeout in seconds
        
        Returns:
            OperationResult
        """
        start_time = time.time()
        
        # Build command
        cmd = ["kubectl"] + args
        
        # Add namespace if specified and not already in args
        if namespace and "-n" not in args and "--namespace" not in args:
            cmd.extend(["-n", namespace])
        
        # Add output format for get/describe
        operation = args[0] if args else ""
        if operation in ["get", "describe"] and "-o" not in args and "--output" not in args:
            cmd.extend(["-o", output_format])
        
        command_str = " ".join(cmd)
        
        try:
            # Execute command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            status = ResultStatus.SUCCESS if result.returncode == 0 else ResultStatus.ERROR
            
            return OperationResult(
                status=status,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                duration_ms=duration_ms,
                command=command_str,
                error=result.stderr if result.returncode != 0 else None,
            )
            
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            return OperationResult(
                status=ResultStatus.TIMEOUT,
                command=command_str,
                duration_ms=duration_ms,
                error=f"Command timeout after {timeout}s",
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"kubectl execution error: {e}")
            return OperationResult(
                status=ResultStatus.ERROR,
                command=command_str,
                duration_ms=duration_ms,
                error=str(e),
            )
    
    def is_safe_operation(self, args: List[str], namespace: Optional[str] = None) -> tuple[bool, str]:
        """
        Check if kubectl operation is safe.
        
        Returns:
            (is_safe, reason)
        """
        if not args:
            return False, "Empty command"
        
        operation = args[0]
        
        # Allow read operations
        if operation in ALLOWED_READ_OPS:
            return True, "Read operation"
        
        # Write operations need more scrutiny
        if operation in ALLOWED_WRITE_OPS:
            # Check for protected namespaces
            target_ns = namespace
            for i, arg in enumerate(args):
                if arg in ["-n", "--namespace"] and i + 1 < len(args):
                    target_ns = args[i + 1]
                    break
            
            if target_ns in PROTECTED_NAMESPACES:
                return False, f"Cannot modify protected namespace: {target_ns}"
            
            return True, "Write operation allowed"
        
        # Dangerous operations
        if operation in DANGEROUS_OPS:
            return False, f"Dangerous operation: {operation}"
        
        return False, f"Unknown operation: {operation}"
