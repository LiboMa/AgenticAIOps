#!/usr/bin/env python3
"""
Fault Injection: ImagePullBackOff

Injects image pull error by deploying a pod with non-existent image.
Based on AIOpsLab P=⟨T,C,S⟩ framework.

Problem Definition:
- T (Task): Detection + Localization
- C (Context): Invalid/non-existent container image
- S (Solution): Identify ImagePullBackOff, recommend image fix
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_NAMESPACE = "stress-test"
DEFAULT_TIMEOUT = 60  # seconds
INVALID_IMAGE = "nonexistent-registry.io/fake-image:v999"


def create_namespace(namespace: str) -> bool:
    """Create isolated namespace for testing."""
    try:
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
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create namespace: {e}")
        return False


def inject_image_error(namespace: str = DEFAULT_NAMESPACE, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Inject ImagePullBackOff by deploying pod with invalid image.
    
    Args:
        namespace: Target namespace
        timeout: Maximum wait time
    
    Returns:
        Dict with injection status
    """
    pod_name = f"imagepull-test-{int(time.time())}"
    
    pod_manifest = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {pod_name}
  namespace: {namespace}
  labels:
    app: fault-injection
    fault-type: imagepull
spec:
  containers:
  - name: test
    image: {INVALID_IMAGE}
    command: ["sleep", "3600"]
  restartPolicy: Never
"""
    
    result = {
        "status": "unknown",
        "pod_name": pod_name,
        "namespace": namespace,
        "fault_type": "imagepull",
        "start_time": datetime.now().isoformat(),
        "invalid_image": INVALID_IMAGE,
    }
    
    try:
        if not create_namespace(namespace):
            result["status"] = "failed"
            result["error"] = "Failed to create namespace"
            return result
        
        logger.info(f"Injecting ImagePullBackOff: {pod_name}")
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
        logger.info(f"ImagePull fault injected: {pod_name}")
        
        # Wait for ImagePullBackOff
        logger.info(f"Waiting for ImagePullBackOff (max {timeout}s)...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check pod status
            status_result = subprocess.run(
                ["kubectl", "get", "pod", pod_name, "-n", namespace,
                 "-o", "jsonpath={.status.containerStatuses[0].state.waiting.reason}"],
                capture_output=True, text=True
            )
            
            reason = status_result.stdout.strip()
            if reason in ["ImagePullBackOff", "ErrImagePull"]:
                result["status"] = "triggered"
                result["detection_time"] = time.time() - start_time
                result["reason"] = reason
                logger.info(f"{reason} detected in {result['detection_time']:.1f}s")
                break
            
            # Check events
            events_result = subprocess.run(
                ["kubectl", "get", "events", "-n", namespace,
                 "--field-selector", f"involvedObject.name={pod_name}",
                 "-o", "jsonpath={.items[*].reason}"],
                capture_output=True, text=True
            )
            
            if "Failed" in events_result.stdout or "ErrImagePull" in events_result.stdout:
                result["status"] = "triggered"
                result["detection_time"] = time.time() - start_time
                logger.info(f"Image pull error detected in {result['detection_time']:.1f}s")
                break
            
            time.sleep(2)
        
        if result["status"] != "triggered":
            result["status"] = "timeout"
            logger.warning("ImagePullBackOff not triggered within timeout")
        
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
    parser = argparse.ArgumentParser(description="Inject ImagePullBackOff fault")
    parser.add_argument("--namespace", "-n", default=DEFAULT_NAMESPACE)
    parser.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--cleanup", "-c", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    
    args = parser.parse_args()
    
    if args.cleanup:
        cleanup(args.namespace)
        return
    
    try:
        result = inject_image_error(args.namespace, args.timeout)
        print(f"\n{'='*60}")
        print("ImagePullBackOff Fault Injection Result:")
        print(f"{'='*60}")
        for key, value in result.items():
            print(f"  {key}: {value}")
        print(f"{'='*60}\n")
        
        if not args.no_cleanup:
            time.sleep(5)
            cleanup(args.namespace, result.get("pod_name"))
        
    except KeyboardInterrupt:
        print("\nInterrupted, cleaning up...")
        cleanup(args.namespace)


if __name__ == "__main__":
    main()
