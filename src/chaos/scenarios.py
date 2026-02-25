"""Chaos scenario implementations — translates bash chaos scripts to Python subprocess calls.

Each scenario class implements execute() and rollback() methods that invoke
kubectl via subprocess.run with proper timeouts and error handling.
"""

from __future__ import annotations

import json
import logging
import subprocess
from abc import ABC, abstractmethod
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Default subprocess timeout (seconds)
KUBECTL_TIMEOUT = 120


def _run_kubectl(
    args: List[str],
    timeout: int = KUBECTL_TIMEOUT,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Run a kubectl command via subprocess with timeout."""
    cmd = ["kubectl"] + args
    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
    )
    if result.stdout:
        logger.debug("stdout: %s", result.stdout.strip())
    if result.stderr:
        logger.debug("stderr: %s", result.stderr.strip())
    return result


class BaseScenario(ABC):
    """Abstract base for chaos scenarios."""

    @abstractmethod
    def execute(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        """Execute the chaos scenario. Returns a list of observation strings."""

    @abstractmethod
    def rollback(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        """Rollback the chaos scenario. Returns a list of observation strings."""


class ResourceStressScenario(BaseScenario):
    """Deploy a stress-ng pod to consume CPU and memory on the node.

    Params:
        cpu (int): Number of CPU stress workers (default: 2)
        vm_bytes (str): Memory to allocate per VM worker (default: "768M")
        timeout_seconds (int): stress-ng duration in seconds (default: 600)
    """

    STRESS_POD_MANIFEST = """{
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "stress-test",
            "labels": {"app": "stress-test", "chaos": "resource-stress"}
        },
        "spec": {
            "containers": [{
                "name": "stress",
                "image": "alexeiled/stress-ng:latest",
                "args": [
                    "--cpu", "%(cpu)s",
                    "--vm", "1",
                    "--vm-bytes", "%(vm_bytes)s",
                    "--timeout", "%(timeout_seconds)s",
                    "--metrics-brief"
                ],
                "resources": {
                    "requests": {"cpu": "1500m", "memory": "768Mi"},
                    "limits": {"cpu": "2000m", "memory": "1Gi"}
                }
            }],
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 5
        }
    }"""

    def execute(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        cpu = params.get("cpu", 2)
        vm_bytes = params.get("vm_bytes", "768M")
        timeout_seconds = params.get("timeout_seconds", 600)

        manifest = self.STRESS_POD_MANIFEST % {
            "cpu": cpu,
            "vm_bytes": vm_bytes,
            "timeout_seconds": timeout_seconds,
        }

        # Apply the stress pod manifest via stdin
        result = subprocess.run(
            ["kubectl", "apply", "-n", namespace, "-f", "-"],
            input=manifest,
            capture_output=True,
            text=True,
            timeout=KUBECTL_TIMEOUT,
            check=True,
        )
        observations.append(f"Deployed stress-ng pod (cpu={cpu}, vm_bytes={vm_bytes}, timeout={timeout_seconds}s)")
        observations.append(f"kubectl output: {result.stdout.strip()}")
        return observations

    def rollback(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        result = _run_kubectl(
            ["delete", "pod", "stress-test", "-n", namespace, "--force", "--grace-period=0"],
            check=False,
        )
        if result.returncode == 0:
            observations.append("Deleted stress-test pod")
        else:
            observations.append(f"Stress pod deletion: {result.stderr.strip() or 'not found'}")
        return observations


class NetworkBlockScenario(BaseScenario):
    """Block network traffic to backend using a NetworkPolicy.

    Params:
        target_app (str): Label selector for pods to block (default: "backend")
        policy_name (str): Name of the NetworkPolicy (default: "chaos-block-backend")
    """

    def _build_policy_manifest(self, namespace: str, params: Dict[str, Any]) -> str:
        target_app = params.get("target_app", "backend")
        policy_name = params.get("policy_name", "chaos-block-backend")
        return json.dumps({
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": policy_name,
                "labels": {"chaos": "network-block"},
            },
            "spec": {
                "podSelector": {
                    "matchLabels": {"app": target_app},
                },
                "policyTypes": ["Ingress"],
                "ingress": [],
            },
        })

    def execute(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        target_app = params.get("target_app", "backend")
        policy_name = params.get("policy_name", "chaos-block-backend")
        manifest = self._build_policy_manifest(namespace, params)

        result = subprocess.run(
            ["kubectl", "apply", "-n", namespace, "-f", "-"],
            input=manifest,
            capture_output=True,
            text=True,
            timeout=KUBECTL_TIMEOUT,
            check=True,
        )
        observations.append(
            f"Applied NetworkPolicy '{policy_name}' blocking all ingress to app={target_app}"
        )
        observations.append(f"kubectl output: {result.stdout.strip()}")
        return observations

    def rollback(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        policy_name = params.get("policy_name", "chaos-block-backend")
        result = _run_kubectl(
            ["delete", "networkpolicy", policy_name, "-n", namespace],
            check=False,
        )
        if result.returncode == 0:
            observations.append(f"Deleted NetworkPolicy '{policy_name}'")
        else:
            observations.append(f"NetworkPolicy deletion: {result.stderr.strip() or 'not found'}")
        return observations


class PodKillScenario(BaseScenario):
    """Kill pods or scale deployments to zero.

    Params:
        action (str): "kill" to force-delete pods, "scale-zero" to scale to 0 (default: "kill")
        target_label (str): Label selector for pod kill (default: "app=frontend")
        deployments (list): Deployments to scale for scale-zero (default: ["frontend", "backend"])
        original_replicas (dict): Original replica counts for rollback
            (default: {"frontend": 3, "backend": 2})
    """

    def execute(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        action = params.get("action", "kill")

        if action == "kill":
            target_label = params.get("target_label", "app=frontend")
            result = _run_kubectl(
                ["delete", "pods", "-n", namespace, "-l", target_label,
                 "--force", "--grace-period=0"],
                check=True,
            )
            observations.append(f"Force-deleted pods with label {target_label}")
            observations.append(f"kubectl output: {result.stdout.strip()}")

        elif action == "scale-zero":
            deployments = params.get("deployments", ["frontend", "backend"])
            for deploy in deployments:
                result = _run_kubectl(
                    ["scale", "deployment", deploy, "-n", namespace, "--replicas=0"],
                    check=True,
                )
                observations.append(f"Scaled deployment/{deploy} to 0 replicas")

        return observations

    def rollback(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        original_replicas = params.get("original_replicas", {"frontend": 3, "backend": 2})

        for deploy, replicas in original_replicas.items():
            result = _run_kubectl(
                ["scale", "deployment", deploy, "-n", namespace, f"--replicas={replicas}"],
                check=False,
            )
            if result.returncode == 0:
                observations.append(f"Restored deployment/{deploy} to {replicas} replicas")
            else:
                observations.append(f"Failed to restore {deploy}: {result.stderr.strip()}")

        return observations


class ConfigBreakScenario(BaseScenario):
    """Break deployment via bad image or invalid config.

    Params:
        action (str): "bad-image" or "bad-config" (default: "bad-image")
        deployment (str): Target deployment (default: "frontend")
        container (str): Container name (default: "nginx")
        bad_image (str): Non-existent image tag (default: "nginx:99.99-nonexistent")
        good_image (str): Correct image for rollback (default: "nginx:1.25-alpine")
    """

    def execute(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        action = params.get("action", "bad-image")
        deployment = params.get("deployment", "frontend")
        container = params.get("container", "nginx")

        if action == "bad-image":
            bad_image = params.get("bad_image", "nginx:99.99-nonexistent")
            result = _run_kubectl(
                ["set", "image", f"deployment/{deployment}",
                 "-n", namespace, f"{container}={bad_image}"],
                check=True,
            )
            observations.append(
                f"Set {deployment} image to {bad_image} — pods will enter ImagePullBackOff"
            )

        elif action == "bad-config":
            # Create invalid ConfigMap via kubectl
            result = subprocess.run(
                ["kubectl", "create", "configmap", "nginx-config",
                 "-n", namespace,
                 "--from-literal=default.conf=invalid { config syntax !!!;",
                 "--dry-run=client", "-o", "yaml"],
                capture_output=True,
                text=True,
                timeout=KUBECTL_TIMEOUT,
                check=True,
            )
            apply_result = subprocess.run(
                ["kubectl", "apply", "-n", namespace, "-f", "-"],
                input=result.stdout,
                capture_output=True,
                text=True,
                timeout=KUBECTL_TIMEOUT,
                check=True,
            )
            observations.append("Applied invalid nginx config to ConfigMap")

            # Restart deployment to pick up broken config
            _run_kubectl(
                ["rollout", "restart", f"deployment/{deployment}", "-n", namespace],
                check=True,
            )
            observations.append(f"Restarted {deployment} — pods will CrashLoopBackOff")

        return observations

    def rollback(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        deployment = params.get("deployment", "frontend")
        container = params.get("container", "nginx")
        good_image = params.get("good_image", "nginx:1.25-alpine")

        # Restore image
        result = _run_kubectl(
            ["set", "image", f"deployment/{deployment}",
             "-n", namespace, f"{container}={good_image}"],
            check=False,
        )
        if result.returncode == 0:
            observations.append(f"Restored {deployment} image to {good_image}")
        else:
            observations.append(f"Image restore failed: {result.stderr.strip()}")

        # Restart deployment
        _run_kubectl(
            ["rollout", "restart", f"deployment/{deployment}", "-n", namespace],
            check=False,
        )
        observations.append(f"Restarted deployment/{deployment}")

        return observations


class NodeDrainScenario(BaseScenario):
    """Cordon and drain a node to simulate node failure.

    Params:
        node_name (str): Specific node to drain. If not provided, uses first node.
    """

    def _get_first_node(self) -> str:
        """Get the name of the first Kubernetes node."""
        result = _run_kubectl(
            ["get", "nodes", "-o", "jsonpath={.items[0].metadata.name}"],
            check=True,
        )
        return result.stdout.strip()

    def _get_all_nodes(self) -> List[str]:
        """Get names of all Kubernetes nodes."""
        result = _run_kubectl(
            ["get", "nodes", "-o", "jsonpath={.items[*].metadata.name}"],
            check=True,
        )
        return result.stdout.strip().split()

    def execute(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        node_name = params.get("node_name")

        if not node_name:
            node_name = self._get_first_node()
            observations.append(f"Auto-selected node: {node_name}")

        # Cordon the node
        _run_kubectl(["cordon", node_name], check=True)
        observations.append(f"Cordoned node {node_name}")

        # Drain the node
        result = _run_kubectl(
            ["drain", node_name,
             "--ignore-daemonsets",
             "--delete-emptydir-data",
             "--force",
             "--grace-period=60",
             "--timeout=120s"],
            check=True,
        )
        observations.append(f"Drained node {node_name}")

        return observations

    def rollback(self, namespace: str, params: Dict[str, Any]) -> List[str]:
        observations = []
        node_name = params.get("node_name")

        if node_name:
            # Uncordon specific node
            result = _run_kubectl(["uncordon", node_name], check=False)
            if result.returncode == 0:
                observations.append(f"Uncordoned node {node_name}")
            else:
                observations.append(f"Uncordon failed: {result.stderr.strip()}")
        else:
            # Uncordon all nodes
            try:
                nodes = self._get_all_nodes()
                for node in nodes:
                    _run_kubectl(["uncordon", node], check=False)
                    observations.append(f"Uncordoned node {node}")
            except Exception as e:
                observations.append(f"Failed to list/uncordon nodes: {e}")

        return observations


# Registry mapping ChaosType to scenario implementation
SCENARIO_REGISTRY: Dict[str, BaseScenario] = {
    "resource_stress": ResourceStressScenario(),
    "network_block": NetworkBlockScenario(),
    "pod_kill": PodKillScenario(),
    "config_break": ConfigBreakScenario(),
    "node_drain": NodeDrainScenario(),
}
