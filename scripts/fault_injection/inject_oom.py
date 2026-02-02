#!/usr/bin/env python3
"""
Fault Injection: Pod OOM (Out of Memory)

Injects memory stress to trigger OOMKilled events.
Based on AIOpsLab P=⟨T,C,S⟩ framework.

Problem Definition:
- T (Task): Detection + Localization
- C (Context): Pod exceeds memory limit
- S (Solution): Identify OOMKilled, recommend memory increase
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_NAMESPACE = "stress-test"
DEFAULT_TIMEOUT = 120  # seconds
MEMORY_LIMIT = "64Mi"
STRESS_MEMORY = "128M"  # More than limit to trigger OOM


def create_namespace(namespace: str) -> bool:
    """Create isolated namespace for testing."""
    try:
        # Check if namespace exists
        result = subprocess.run(
            ["kubectl", "get", "namespace", namespace],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            logger.info(f"Creating namespace: {namespace}")
            subprocess.run(
                ["kubectl", "create", "namespace", namespace],
                check=True
            )
        else:
            logger.info(f"Namespace {namespace} already exists")
        
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create namespace: {e}")
        return False


def inject_oom(namespace: str = DEFAULT_NAMESPACE, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Inject OOM fault by deploying a pod that exceeds memory limit.
    
    Args:
        namespace: Target namespace (isolated)
        timeout: Maximum time before cleanup
    
    Returns:
        Dict with injection status and details
    """
    pod_name = f"oom-test-{int(time.time())}"
    
    # Pod manifest with memory limit
    pod_manifest = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {pod_name}
  namespace: {namespace}
  labels:
    app: fault-injection
    fault-type: oom
spec:
  containers:
  - name: stress
    image: polinux/stress
    resources:
      limits:
        memory: "{MEMORY_LIMIT}"
      requests:
        memory: "32Mi"
    command: ["stress"]
    args: ["--vm", "1", "--vm-bytes", "{STRESS_MEMORY}", "--vm-hang", "0"]
  restartPolicy: Never
"""
    
    result = {
        "status": "unknown",
        "pod_name": pod_name,
        "namespace": namespace,
        "fault_type": "oom",
        "start_time": datetime.now().isoformat(),
        "memory_limit": MEMORY_LIMIT,
        "stress_memory": STRESS_MEMORY,
    }
    
    try:
        # Create namespace
        if not create_namespace(namespace):
            result["status"] = "failed"
            result["error"] = "Failed to create namespace"
            return result
        
        # Apply pod manifest
        logger.info(f"Injecting OOM fault: {pod_name}")
        process = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=pod_manifest,
            capture_output=True,
            text=True
        )
        
        if process.returncode != 0:
            result["status"] = "failed"
            result["error"] = process.stderr
            return result
        
        result["status"] = "injected"
        logger.info(f"OOM fault injected: {pod_name}")
        
        # Wait for OOM to occur
        logger.info(f"Waiting for OOMKilled (max {timeout}s)...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check pod status
            status_result = subprocess.run(
                ["kubectl", "get", "pod", pod_name, "-n", namespace, 
                 "-o", "jsonpath={.status.containerStatuses[0].state}"],
                capture_output=True, text=True
            )
            
            if "OOMKilled" in status_result.stdout:
                result["status"] = "triggered"
                result["detection_time"] = time.time() - start_time
                logger.info(f"OOMKilled detected in {result['detection_time']:.1f}s")
                break
            
            # Check events
            events_result = subprocess.run(
                ["kubectl", "get", "events", "-n", namespace,
                 "--field-selector", f"involvedObject.name={pod_name}",
                 "-o", "jsonpath={.items[*].reason}"],
                capture_output=True, text=True
            )
            
            if "OOMKilling" in events_result.stdout or "OOMKilled" in events_result.stdout:
                result["status"] = "triggered"
                result["detection_time"] = time.time() - start_time
                logger.info(f"OOMKilled event detected in {result['detection_time']:.1f}s")
                break
            
            time.sleep(2)
        
        if result["status"] != "triggered":
            result["status"] = "timeout"
            logger.warning("OOM not triggered within timeout")
        
        return result
        
    except Exception as e:
        logger.error(f"Injection error: {e}")
        result["status"] = "error"
        result["error"] = str(e)
        return result


def cleanup(namespace: str = DEFAULT_NAMESPACE, pod_name: str = None):
    """Clean up injected resources."""
    try:
        if pod_name:
            logger.info(f"Cleaning up pod: {pod_name}")
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "-n", namespace, "--ignore-not-found"],
                capture_output=True
            )
        else:
            logger.info(f"Cleaning up all fault-injection pods in {namespace}")
            subprocess.run(
                ["kubectl", "delete", "pods", "-n", namespace, "-l", "app=fault-injection"],
                capture_output=True
            )
    except Exception as e:
        logger.error(f"Cleanup error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Inject OOM fault for testing")
    parser.add_argument("--namespace", "-n", default=DEFAULT_NAMESPACE, help="Target namespace")
    parser.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT, help="Timeout in seconds")
    parser.add_argument("--cleanup", "-c", action="store_true", help="Only cleanup, no injection")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip cleanup after injection")
    
    args = parser.parse_args()
    
    if args.cleanup:
        cleanup(args.namespace)
        return
    
    try:
        result = inject_oom(args.namespace, args.timeout)
        print(f"\n{'='*60}")
        print("OOM Fault Injection Result:")
        print(f"{'='*60}")
        for key, value in result.items():
            print(f"  {key}: {value}")
        print(f"{'='*60}\n")
        
        # Cleanup unless --no-cleanup
        if not args.no_cleanup:
            time.sleep(5)  # Wait a bit for diagnosis
            cleanup(args.namespace, result.get("pod_name"))
        
    except KeyboardInterrupt:
        print("\nInterrupted, cleaning up...")
        cleanup(args.namespace)


if __name__ == "__main__":
    main()
