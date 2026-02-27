"""Kubernetes diagnostic and management tools for Strands Agent.

Read-tier tools for observation and diagnosis, plus write-tier tools
for remediation.  All commands route through KubectlExecutor which
enforces SecurityFilter checks.

Each function is decorated with @tool for automatic registration
via SkillLoader.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from strands import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Lazily resolve KubectlExecutor so this module can be imported even when
# the full ACI stack isn't on sys.path (e.g. unit tests with mocks).
_executor = None


def _get_executor():
    """Return a shared KubectlExecutor (lazy init)."""
    global _executor
    if _executor is None:
        from src.aci.operations.kubectl import KubectlExecutor

        # Default cluster — overridden at runtime by skill registry
        _executor = KubectlExecutor(
            cluster_name="default",
            region="ap-southeast-1",
        )
    return _executor


def _kubectl(args: list[str], namespace: Optional[str] = None,
             output_format: str = "wide", timeout: int = 30,
             approval_token: Optional[str] = None) -> str:
    """Run kubectl via KubectlExecutor, return stdout or error string."""
    result = _get_executor().execute(
        args=args,
        namespace=namespace,
        output_format=output_format,
        timeout=timeout,
        approval_token=approval_token,
    )
    if result.error:
        return f"[ERROR] {result.error}"
    return result.stdout or "(no output)"


# ---------------------------------------------------------------------------
# READ tier — safe observation tools
# ---------------------------------------------------------------------------

@tool
def get_pods(namespace: str = "default", all_namespaces: bool = False,
             field_selector: Optional[str] = None) -> str:
    """List pods with status, restarts, node, and IP.

    Args:
        namespace: Target namespace (default: 'default').
        all_namespaces: If True, list across all namespaces.
        field_selector: Optional field selector (e.g. 'status.phase!=Running').

    Returns:
        Pod listing in wide format.
    """
    args = ["get", "pods"]
    if all_namespaces:
        args.append("-A")
        namespace = None
    if field_selector:
        args.extend(["--field-selector", field_selector])
    return _kubectl(args, namespace=namespace)


@tool
def describe_resource(resource_type: str, name: str,
                      namespace: str = "default") -> str:
    """Describe a Kubernetes resource in detail.

    Args:
        resource_type: Resource kind (pod, deploy, svc, node, etc.).
        name: Resource name.
        namespace: Target namespace.

    Returns:
        Full describe output including events.
    """
    args = ["describe", resource_type, name]
    ns = None if resource_type == "node" else namespace
    return _kubectl(args, namespace=ns, output_format="")


@tool
def get_events(namespace: str = "default", all_namespaces: bool = False,
               involved_object: Optional[str] = None) -> str:
    """Get recent Kubernetes events sorted by timestamp.

    Args:
        namespace: Target namespace.
        all_namespaces: If True, show events across all namespaces.
        involved_object: Filter events by involved object name.

    Returns:
        Recent events.
    """
    args = ["get", "events", "--sort-by=.lastTimestamp"]
    if all_namespaces:
        args.append("-A")
        namespace = None
    if involved_object:
        args.extend(["--field-selector", f"involvedObject.name={involved_object}"])
    return _kubectl(args, namespace=namespace)


@tool
def kubectl_logs(pod_name: str, namespace: str = "default",
                 container: Optional[str] = None,
                 previous: bool = False, tail: int = 100) -> str:
    """Get logs from a pod (or its previous crashed instance).

    Args:
        pod_name: Pod name.
        namespace: Target namespace.
        container: Specific container in multi-container pod.
        previous: If True, get logs from the previous (crashed) container.
        tail: Number of lines to return.

    Returns:
        Log output.
    """
    args = ["logs", pod_name, f"--tail={tail}"]
    if container:
        args.extend(["-c", container])
    if previous:
        args.append("--previous")
    return _kubectl(args, namespace=namespace, output_format="")


@tool
def get_nodes(wide: bool = True) -> str:
    """List cluster nodes with status, roles, version, and IPs.

    Args:
        wide: If True, include extra columns (IPs, OS, kernel).

    Returns:
        Node listing.
    """
    args = ["get", "nodes"]
    fmt = "wide" if wide else ""
    return _kubectl(args, output_format=fmt)


@tool
def top_pods(namespace: str = "default", all_namespaces: bool = False,
             sort_by: str = "memory") -> str:
    """Show resource usage (CPU/memory) for pods.

    Args:
        namespace: Target namespace.
        all_namespaces: If True, show all namespaces.
        sort_by: Sort by 'cpu' or 'memory'.

    Returns:
        Resource usage table.
    """
    args = ["top", "pods", f"--sort-by={sort_by}"]
    if all_namespaces:
        args.append("-A")
        namespace = None
    return _kubectl(args, namespace=namespace, output_format="")


@tool
def top_nodes() -> str:
    """Show resource usage (CPU/memory) for nodes.

    Returns:
        Node resource usage table.
    """
    return _kubectl(["top", "nodes"], output_format="")


@tool
def rollout_status(resource: str, namespace: str = "default") -> str:
    """Check rollout status of a deployment/daemonset/statefulset.

    Args:
        resource: Resource spec (e.g. 'deploy/my-app', 'daemonset/fluentd').
        namespace: Target namespace.

    Returns:
        Rollout status output.
    """
    return _kubectl(["rollout", "status", resource], namespace=namespace,
                     output_format="")


@tool
def get_resource_yaml(resource_type: str, name: str,
                      namespace: str = "default") -> str:
    """Get the full YAML spec of a resource.

    Args:
        resource_type: Resource kind (deploy, svc, configmap, etc.).
        name: Resource name.
        namespace: Target namespace.

    Returns:
        YAML output of the resource.
    """
    args = ["get", resource_type, name]
    ns = None if resource_type == "node" else namespace
    return _kubectl(args, namespace=ns, output_format="yaml")


@tool
def check_endpoints(service_name: str, namespace: str = "default") -> str:
    """Check endpoints behind a service (are backends healthy?).

    Args:
        service_name: Service name.
        namespace: Target namespace.

    Returns:
        Endpoint details showing ready/not-ready addresses.
    """
    parts = [
        f"=== Service ===\n{_kubectl(['get', 'svc', service_name], namespace=namespace)}",
        f"=== Endpoints ===\n{_kubectl(['get', 'endpoints', service_name], namespace=namespace)}",
        f"=== Describe ===\n{_kubectl(['describe', 'endpoints', service_name], namespace=namespace, output_format='')}",
    ]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# WRITE tier — mutation tools (SecurityFilter enforced)
# ---------------------------------------------------------------------------

@tool
def scale_resource(resource: str, replicas: int,
                   namespace: str = "default") -> str:
    """Scale a deployment/statefulset/replicaset.

    Args:
        resource: Resource spec (e.g. 'deploy/my-app').
        replicas: Desired replica count.
        namespace: Target namespace.

    Returns:
        Scale result.
    """
    args = ["scale", resource, f"--replicas={replicas}"]
    return _kubectl(args, namespace=namespace, output_format="")


@tool
def rollout_restart(resource: str, namespace: str = "default") -> str:
    """Restart a deployment/daemonset/statefulset with rolling update.

    Args:
        resource: Resource spec (e.g. 'deploy/my-app').
        namespace: Target namespace.

    Returns:
        Rollout restart result.
    """
    return _kubectl(["rollout", "restart", resource], namespace=namespace,
                     output_format="")


@tool
def rollout_undo(resource: str, namespace: str = "default",
                 revision: Optional[int] = None) -> str:
    """Rollback a deployment to previous or specified revision.

    Args:
        resource: Resource spec (e.g. 'deploy/my-app').
        namespace: Target namespace.
        revision: Specific revision to roll back to (optional).

    Returns:
        Rollback result.
    """
    args = ["rollout", "undo", resource]
    if revision is not None:
        args.extend([f"--to-revision={revision}"])
    return _kubectl(args, namespace=namespace, output_format="")


@tool
def label_resource(resource_type: str, name: str, labels: str,
                   namespace: str = "default") -> str:
    """Add or update labels on a resource.

    Args:
        resource_type: Resource kind (pod, node, deploy, etc.).
        name: Resource name.
        labels: Label key=value pairs (e.g. 'env=prod tier=frontend').
        namespace: Target namespace.

    Returns:
        Label result.
    """
    args = ["label", resource_type, name] + labels.split()
    ns = None if resource_type == "node" else namespace
    return _kubectl(args, namespace=ns, output_format="")


# ---------------------------------------------------------------------------
# DANGEROUS tier — require approval_token
# ---------------------------------------------------------------------------

@tool
def delete_resource(resource_type: str, name: str,
                    namespace: str = "default",
                    approval_token: str = "") -> str:
    """Delete a Kubernetes resource. REQUIRES approval_token.

    Args:
        resource_type: Resource kind (pod, deploy, svc, etc.).
        name: Resource name.
        namespace: Target namespace.
        approval_token: Required approval token for dangerous operation.

    Returns:
        Deletion result or security error.
    """
    if not approval_token:
        return "[ERROR] delete requires approval_token. Request approval first."
    args = ["delete", resource_type, name]
    return _kubectl(args, namespace=namespace, output_format="",
                     approval_token=approval_token)


@tool
def drain_node(node_name: str, approval_token: str = "",
               ignore_daemonsets: bool = True,
               delete_emptydir_data: bool = False) -> str:
    """Drain a node for maintenance. REQUIRES approval_token.

    Checks PodDisruptionBudgets before draining. Cordons the node first.

    Args:
        node_name: Node name to drain.
        approval_token: Required approval token for dangerous operation.
        ignore_daemonsets: Ignore DaemonSet-managed pods (default: True).
        delete_emptydir_data: Delete emptyDir data (default: False).

    Returns:
        Drain result or security error.
    """
    if not approval_token:
        return "[ERROR] drain requires approval_token. Request approval first."
    args = ["drain", node_name]
    if ignore_daemonsets:
        args.append("--ignore-daemonsets")
    if delete_emptydir_data:
        args.append("--delete-emptydir-data")
    return _kubectl(args, output_format="", approval_token=approval_token)


@tool
def cordon_node(node_name: str, approval_token: str = "") -> str:
    """Cordon a node (mark unschedulable). REQUIRES approval_token.

    Args:
        node_name: Node name to cordon.
        approval_token: Required approval token for dangerous operation.

    Returns:
        Cordon result or security error.
    """
    if not approval_token:
        return "[ERROR] cordon requires approval_token. Request approval first."
    return _kubectl(["cordon", node_name], output_format="",
                     approval_token=approval_token)


@tool
def uncordon_node(node_name: str, approval_token: str = "") -> str:
    """Uncordon a node (mark schedulable again). REQUIRES approval_token.

    Args:
        node_name: Node name to uncordon.
        approval_token: Required approval token for dangerous operation.

    Returns:
        Uncordon result or security error.
    """
    if not approval_token:
        return "[ERROR] uncordon requires approval_token. Request approval first."
    return _kubectl(["uncordon", node_name], output_format="",
                     approval_token=approval_token)
