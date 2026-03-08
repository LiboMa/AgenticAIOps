"""
Kubernetes Skill — Security policy (Layer 3).

Per-skill allow/deny rules for kubectl commands.
Migrated from src/aci/operations/kubectl.py + src/aci/security/filters.py.
"""

from typing import Any, Dict, Tuple

# Allowed operations by category
ALLOWED_READ_OPS = frozenset([
    "get", "describe", "logs", "top", "explain",
    "api-resources", "api-versions", "cluster-info",
    "config", "version", "auth",
])

ALLOWED_WRITE_OPS = frozenset([
    "apply", "patch", "scale", "rollout", "label",
    "annotate", "set", "create",
])

DANGEROUS_OPS = frozenset([
    "delete", "drain", "cordon", "uncordon", "taint",
    "exec", "replace", "edit",
])

PROTECTED_NAMESPACES = frozenset([
    "kube-system", "kube-public", "kube-node-lease",
])


def check(tool_name: str, kwargs: Dict[str, Any]) -> Tuple[bool, str]:
    """Skill-level security check for kubernetes tools.

    Called by @secure_tool decorator as Layer 3.
    """
    command = kwargs.get("command", "")
    args = kwargs.get("args", [])
    namespace = kwargs.get("namespace", "")

    # If we have a command string, extract the operation
    if command and isinstance(command, str):
        parts = command.strip().split()
        if parts and parts[0] == "kubectl":
            parts = parts[1:]
        if parts:
            op = parts[0].lower()
            args = parts[1:] if not args else args
        else:
            return False, "Empty kubectl command"
    elif args:
        op = args[0].lower() if args else ""
    else:
        # No command info — tool handles its own args
        return True, "OK"

    # Check protected namespaces
    ns = namespace
    if not ns:
        for i, a in enumerate(args):
            if a in ("-n", "--namespace") and i + 1 < len(args):
                ns = args[i + 1]
                break

    if ns in PROTECTED_NAMESPACES and op not in ALLOWED_READ_OPS:
        return False, f"Cannot modify protected namespace: {ns}"

    # Check operation classification
    if op in ALLOWED_READ_OPS:
        return True, "Read operation"

    if op in ALLOWED_WRITE_OPS:
        return True, "Write operation (tier-gated by @secure_tool)"

    if op in DANGEROUS_OPS:
        # Allowed only if tier gate passes (handled by @secure_tool Layer 4)
        return True, f"Dangerous operation '{op}' (requires approval)"

    return False, f"Unknown kubectl operation: {op}"
