"""Kubernetes remediation tools for Strands Agent.

Write and dangerous-tier tools that perform mutations.
Separated from diagnose.py for clarity — SkillLoader discovers
both modules.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from strands import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helper — duplicated from diagnose.py because SkillLoader uses
# importlib.util (file-level import), not package-relative imports.
# ---------------------------------------------------------------------------

_executor = None


def _get_executor():
    global _executor
    if _executor is None:
        from src.aci.operations.kubectl import KubectlExecutor
        _executor = KubectlExecutor(cluster_name="default", region="ap-southeast-1")
    return _executor


def _kubectl(args, namespace=None, output_format="wide",
             timeout=30, approval_token=None):
    result = _get_executor().execute(
        args=args, namespace=namespace, output_format=output_format,
        timeout=timeout, approval_token=approval_token,
    )
    if result.error:
        return f"[ERROR] {result.error}"
    return result.stdout or "(no output)"


@tool
def apply_manifest(manifest_yaml: str, namespace: str = "default",
                   dry_run: bool = True,
                   approval_token: str = "") -> str:
    """Apply a YAML manifest to the cluster.

    By default runs with --dry-run=client for safety preview.
    Set dry_run=False with approval_token for actual apply.

    Args:
        manifest_yaml: YAML manifest content (NOT a URL).
        namespace: Target namespace.
        dry_run: If True, preview only (default: True).
        approval_token: Required for actual apply (dry_run=False).

    Returns:
        Apply result or dry-run preview.
    """
    import subprocess
    import tempfile
    import os

    if not dry_run and not approval_token:
        return "[ERROR] apply (non-dry-run) requires approval_token."

    # Reject external URLs (P2 security: apply -f <url>)
    if manifest_yaml.strip().startswith("http://") or manifest_yaml.strip().startswith("https://"):
        return "[ERROR] Applying from external URLs is blocked. Provide inline YAML."

    # Write manifest to temp file
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(manifest_yaml)
            tmp_path = f.name

        args = ["apply", "-f", tmp_path]
        if dry_run:
            args.append("--dry-run=client")

        token = approval_token if not dry_run else None
        return _kubectl(args, namespace=namespace, output_format="",
                        approval_token=token)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@tool
def patch_resource(resource_type: str, name: str, patch_json: str,
                   namespace: str = "default",
                   patch_type: str = "strategic") -> str:
    """Patch a Kubernetes resource with a JSON patch.

    Args:
        resource_type: Resource kind (deploy, svc, configmap, etc.).
        name: Resource name.
        patch_json: JSON patch content.
        namespace: Target namespace.
        patch_type: Patch strategy ('strategic', 'merge', 'json').

    Returns:
        Patch result.
    """
    args = ["patch", resource_type, name,
            f"--type={patch_type}", "-p", patch_json]
    return _kubectl(args, namespace=namespace, output_format="")
