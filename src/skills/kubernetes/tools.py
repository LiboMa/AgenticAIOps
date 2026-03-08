"""
Kubernetes Skill — Tools.

15 tools covering CKA-level K8s administration.
All tools use @secure_tool decorator for mandatory security enforcement.

Architecture: ADR-006 §7 + §11.2
"""

from __future__ import annotations

import json
from typing import Optional

from .._security import secure_tool
from .._models import SecurityTier, ToolResult
from .._executor import KubectlExec

_kubectl = KubectlExec(timeout=60)


# ─── T0: Read-Only Tools ──────────────────────────────────────

@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_get_pods(namespace: str = "default", label_selector: str = "") -> str:
    """Get pods in a namespace, optionally filtered by label.

    Args:
        namespace: Target namespace (default: "default")
        label_selector: Label selector (e.g. "app=nginx")

    Returns:
        JSON pod list with status summary.
    """
    args = ["get", "pods"]
    if label_selector:
        args.extend(["-l", label_selector])
    result = _kubectl.execute(args, namespace=namespace)
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout, namespace=namespace).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_describe_resource(resource_type: str, name: str, namespace: str = "default") -> str:
    """Describe a Kubernetes resource in detail.

    Args:
        resource_type: Resource type (pod, deployment, service, node, etc.)
        name: Resource name
        namespace: Target namespace

    Returns:
        Detailed resource description.
    """
    args = ["describe", resource_type, name]
    result = _kubectl.execute(args, namespace=namespace, output_format="")
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_get_logs(pod_name: str, namespace: str = "default", container: str = "",
                 tail_lines: int = 100, previous: bool = False) -> str:
    """Get pod logs.

    Args:
        pod_name: Pod name
        namespace: Target namespace
        container: Container name (optional, for multi-container pods)
        tail_lines: Number of lines from the end (max 500)
        previous: If True, get logs from previous container instance

    Returns:
        Pod log output.
    """
    tail_lines = min(tail_lines, 500)
    args = ["logs", pod_name, f"--tail={tail_lines}"]
    if container:
        args.extend(["-c", container])
    if previous:
        args.append("--previous")
    result = _kubectl.execute(args, namespace=namespace, output_format="")
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_get_events(namespace: str = "default", field_selector: str = "") -> str:
    """Get events in a namespace, sorted by time.

    Args:
        namespace: Target namespace
        field_selector: Field selector (e.g. "involvedObject.name=my-pod")

    Returns:
        Events sorted by last timestamp.
    """
    args = ["get", "events", "--sort-by=.lastTimestamp"]
    if field_selector:
        args.extend(["--field-selector", field_selector])
    result = _kubectl.execute(args, namespace=namespace)
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_get_nodes() -> str:
    """Get all cluster nodes with status and resource usage.

    Returns:
        Node list with conditions and allocatable resources.
    """
    result = _kubectl.execute(["get", "nodes", "-o", "wide"])
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    # Also get node resource usage
    top_result = _kubectl.execute(["top", "nodes"], output_format="")
    data = {
        "nodes": result.stdout,
        "resource_usage": top_result.stdout if top_result.ok else "unavailable",
    }
    return ToolResult.success(data).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_get_deployments(namespace: str = "default") -> str:
    """Get deployments with replica status.

    Args:
        namespace: Target namespace

    Returns:
        Deployment list with ready/desired replica counts.
    """
    result = _kubectl.execute(["get", "deployments"], namespace=namespace)
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout, namespace=namespace).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_get_services(namespace: str = "default") -> str:
    """Get services with endpoints.

    Args:
        namespace: Target namespace

    Returns:
        Service list with type, cluster IP, and ports.
    """
    result = _kubectl.execute(["get", "services"], namespace=namespace)
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout, namespace=namespace).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_cluster_info() -> str:
    """Get cluster info — API server, DNS, and component health.

    Returns:
        Cluster info and component status.
    """
    info = _kubectl.execute(["cluster-info"], output_format="")
    cs = _kubectl.execute(["get", "componentstatuses"], output_format="")
    data = {
        "cluster_info": info.stdout if info.ok else info.stderr,
        "component_status": cs.stdout if cs.ok else "unavailable",
    }
    return ToolResult.success(data).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_get_resource(resource_type: str, namespace: str = "default",
                     name: str = "", label_selector: str = "") -> str:
    """Get any Kubernetes resource type (generic).

    Args:
        resource_type: Resource type (configmap, secret, ingress, pvc, etc.)
        namespace: Target namespace
        name: Specific resource name (optional)
        label_selector: Label selector (optional)

    Returns:
        Resource data in JSON format.
    """
    args = ["get", resource_type]
    if name:
        args.append(name)
    if label_selector:
        args.extend(["-l", label_selector])
    result = _kubectl.execute(args, namespace=namespace)
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout).to_json()


@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def k8s_top_pods(namespace: str = "default", sort_by: str = "cpu") -> str:
    """Get pod resource usage (CPU/memory).

    Args:
        namespace: Target namespace
        sort_by: Sort key — "cpu" or "memory"

    Returns:
        Pod resource usage table.
    """
    args = ["top", "pods"]
    if sort_by == "memory":
        args.append("--sort-by=memory")
    else:
        args.append("--sort-by=cpu")
    result = _kubectl.execute(args, namespace=namespace, output_format="")
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout, namespace=namespace, sort_by=sort_by).to_json()


# ─── T1: Low-Risk Write Tools ─────────────────────────────────

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="kubernetes", command_param=None)
def k8s_scale_deployment(name: str, replicas: int, namespace: str = "default") -> str:
    """Scale a deployment to a target replica count.

    Args:
        name: Deployment name
        replicas: Target replica count (0-50)
        namespace: Target namespace

    Returns:
        Scale result.
    """
    replicas = max(0, min(replicas, 50))
    result = _kubectl.execute(
        ["scale", f"deployment/{name}", f"--replicas={replicas}"],
        namespace=namespace,
        output_format="",
    )
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(
        {"deployment": name, "replicas": replicas, "output": result.stdout.strip()},
        namespace=namespace,
    ).to_json()


@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="kubernetes", command_param=None)
def k8s_rollout_status(name: str, namespace: str = "default") -> str:
    """Check rollout status of a deployment.

    Args:
        name: Deployment name
        namespace: Target namespace

    Returns:
        Rollout status details.
    """
    result = _kubectl.execute(
        ["rollout", "status", f"deployment/{name}", "--timeout=30s"],
        namespace=namespace,
        output_format="",
    )
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(result.stdout.strip()).to_json()


@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="kubernetes", command_param=None)
def k8s_rollout_restart(name: str, namespace: str = "default") -> str:
    """Rolling restart a deployment (zero-downtime).

    Args:
        name: Deployment name
        namespace: Target namespace

    Returns:
        Restart result.
    """
    result = _kubectl.execute(
        ["rollout", "restart", f"deployment/{name}"],
        namespace=namespace,
        output_format="",
    )
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(
        {"deployment": name, "action": "restart", "output": result.stdout.strip()},
    ).to_json()


# ─── T2: High-Risk Tools (approval_token required) ────────────

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="kubernetes", command_param=None, dry_run_support=True)
def k8s_delete_resource(resource_type: str, name: str, namespace: str = "default",
                        dry_run: bool = False) -> str:
    """Delete a Kubernetes resource. Requires approval_token.

    ⚠️ Tier T2 — this is irreversible for some resource types.

    Args:
        resource_type: Resource type (pod, deployment, service, etc.)
        name: Resource name
        namespace: Target namespace
        dry_run: If True, validate but don't execute

    Returns:
        Delete result or dry-run plan.
    """
    args = ["delete", resource_type, name]
    if dry_run:
        args.append("--dry-run=server")
    result = _kubectl.execute(args, namespace=namespace, output_format="")
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(
        {"action": "delete", "resource": f"{resource_type}/{name}",
         "namespace": namespace, "output": result.stdout.strip()},
    ).to_json()


# ─── T3: Destructive Tools (dual approval required) ───────────

@secure_tool(tier=SecurityTier.T3_DESTRUCTIVE, skill="kubernetes", command_param=None, dry_run_support=True)
def k8s_drain_node(node_name: str, dry_run: bool = False) -> str:
    """Drain a node — evicts all pods. Requires dual approval.

    🔴 Tier T3 — system-wide impact. Use with extreme caution.

    Args:
        node_name: Node name to drain
        dry_run: If True, validate but don't execute

    Returns:
        Drain result or dry-run plan.
    """
    args = ["drain", node_name, "--ignore-daemonsets", "--delete-emptydir-data"]
    if dry_run:
        args.append("--dry-run=server")
    result = _kubectl.execute(args, output_format="")
    if not result.ok:
        return ToolResult.fail(result.stderr).to_json()
    return ToolResult.success(
        {"action": "drain", "node": node_name, "output": result.stdout.strip()},
    ).to_json()
