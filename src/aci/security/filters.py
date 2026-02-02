"""
ACI Security Filters

Command filtering to prevent dangerous operations.
"""

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


# Dangerous shell commands
DANGEROUS_COMMANDS = [
    # System-level dangerous commands
    "rm -rf /",
    "rm -rf /*",
    "rm -rf .",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "halt",
    "init 0",
    "init 6",
    "> /dev/sda",
    ":(){ :|:& };:",  # Fork bomb
    
    # Dangerous file operations
    "mv / ",
    "chmod -R 777 /",
    "chown -R ",
]

# Patterns that indicate dangerous operations
DANGEROUS_PATTERNS = [
    r"rm\s+-[rf]+\s+/",  # rm -rf /something
    r"rm\s+--no-preserve-root",
    r">\s*/dev/[sh]d[a-z]",  # Overwrite disk
    r"mkfs\s+",
    r"dd\s+if=.*of=/dev",
]

# Restricted paths
RESTRICTED_PATHS = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/boot",
    "/root",
    "/var/log/wtmp",
    "/var/log/btmp",
]

# Dangerous kubectl operations
DANGEROUS_KUBECTL = [
    "delete namespace kube-system",
    "delete namespace kube-public",
    "delete --all --all-namespaces",
    "delete nodes",
    "delete clusterrole",
    "delete clusterrolebinding",
]


class SecurityFilter:
    """
    Security filter for ACI operations.
    
    Prevents execution of dangerous commands.
    """
    
    def __init__(self):
        self.dangerous_commands = DANGEROUS_COMMANDS
        self.dangerous_patterns = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]
        self.restricted_paths = RESTRICTED_PATHS
        self.dangerous_kubectl = DANGEROUS_KUBECTL
    
    def check_shell(self, command: str) -> Tuple[bool, str]:
        """
        Check if shell command is safe.
        
        Args:
            command: Shell command to check
        
        Returns:
            (is_safe, reason)
        """
        command_lower = command.lower().strip()
        
        # Check against dangerous commands
        for dangerous in self.dangerous_commands:
            if dangerous.lower() in command_lower:
                return False, f"Blocked dangerous command: {dangerous}"
        
        # Check against dangerous patterns
        for pattern in self.dangerous_patterns:
            if pattern.search(command):
                return False, f"Blocked dangerous pattern: {pattern.pattern}"
        
        # Check for restricted paths with write operations
        for path in self.restricted_paths:
            if path in command:
                # Allow read operations
                if any(op in command_lower for op in ["cat", "ls", "head", "tail", "less", "more", "file"]):
                    continue
                # Block write operations
                if any(op in command_lower for op in ["rm", "mv", "cp", ">", ">>", "chmod", "chown", "nano", "vim", "vi", "echo"]):
                    return False, f"Cannot modify restricted path: {path}"
        
        # Check for network exfiltration attempts
        if self._check_network_exfiltration(command):
            return False, "Potential network exfiltration detected"
        
        return True, "OK"
    
    def check_kubectl(self, args: List[str]) -> Tuple[bool, str]:
        """
        Check if kubectl command is safe.
        
        Args:
            args: kubectl arguments
        
        Returns:
            (is_safe, reason)
        """
        if not args:
            return False, "Empty kubectl command"
        
        # Build full command for pattern matching
        full_command = " ".join(args).lower()
        
        # Check against dangerous kubectl commands
        for dangerous in self.dangerous_kubectl:
            if dangerous.lower() in full_command:
                return False, f"Blocked dangerous kubectl: {dangerous}"
        
        operation = args[0]
        
        # Delete operations need extra checks
        if operation == "delete":
            # Check for --all flag
            if "--all" in args or "-A" in args:
                return False, "Cannot use --all with delete"
            
            # Check for namespace deletion
            if len(args) > 1 and args[1] == "namespace":
                ns_name = args[2] if len(args) > 2 else ""
                if ns_name in ["kube-system", "kube-public", "kube-node-lease", "default"]:
                    return False, f"Cannot delete protected namespace: {ns_name}"
        
        return True, "OK"
    
    def _check_network_exfiltration(self, command: str) -> bool:
        """Check for potential network exfiltration attempts."""
        exfil_patterns = [
            r"curl.*\|.*sh",
            r"wget.*\|.*sh",
            r"curl.*-d.*@",  # Posting file contents
            r"nc\s+-[^l]",  # Netcat non-listen mode
        ]
        
        for pattern in exfil_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        
        return False
