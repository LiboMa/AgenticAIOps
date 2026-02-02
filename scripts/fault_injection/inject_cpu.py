#!/usr/bin/env python3
"""
Fault Injection: CPU Throttling

Injects CPU stress to trigger throttling events.
Based on AIOpsLab P=⟨T,C,S⟩ framework.

Problem Definition:
- T (Task): Detection + Analysis
- C (Context): Pod CPU usage exceeds limit, gets throttled
- S (Solution): Identify throttling, recommend CPU limit increase
"""

import argparse
import logging
import subprocess
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_NAMESPACE = "stress-test"
DEFAULT_TIMEOUT = 120
CPU_LIMIT = "100m"  # 0.1 CPU
STRESS_CPU = "2"    # 2 CPU workers (much more than limit)


def create_namespace(namespace: str) -> bool:
    """Create isolated namespace."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "namespace", namespace],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            subprocess.run(["kubectl", "create", "namespace", namespace], check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def inject_cpu_throttling(namespace: str = DEFAULT_NAMESPACE, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Inject CPU throttling by deploying high-CPU pod with low limit.
    """
    pod_name = f"cpu-test-{int(time.time())}"
    
    pod_manifest = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {pod_name}
  namespace: {namespace}
  labels:
    app: fault-injection
    fault-type: cpu-throttle
spec:
  containers:
  - name: stress
    image: polinux/stress
    resources:
      limits:
        cpu: "{CPU_LIMIT}"
      requests:
        cpu: "50m"
    command: ["stress"]
    args: ["--cpu", "{STRESS_CPU}", "--timeout", "300"]
  restartPolicy: Never
"""
    
    result = {
        "status": "unknown",
        "pod_name": pod_name,
        "namespace": namespace,
        "fault_type": "cpu_throttle",
        "start_time": datetime.now().isoformat(),
        "cpu_limit": CPU_LIMIT,
        "stress_cpu": STRESS_CPU,
    }
    
    try:
        if not create_namespace(namespace):
            result["status"] = "failed"
            return result
        
        logger.info(f"Injecting CPU throttling: {pod_name}")
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
        
        # Wait for pod to be running and throttled
        logger.info(f"Waiting for CPU throttling (max {timeout}s)...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if pod is running
            status_result = subprocess.run(
                ["kubectl", "get", "pod", pod_name, "-n", namespace,
                 "-o", "jsonpath={.status.phase}"],
                capture_output=True, text=True
            )
            
            if status_result.stdout.strip() == "Running":
                # Check CPU usage via kubectl top
                top_result = subprocess.run(
                    ["kubectl", "top", "pod", pod_name, "-n", namespace, "--no-headers"],
                    capture_output=True, text=True
                )
                
                if top_result.returncode == 0 and top_result.stdout.strip():
                    # Pod is running with CPU stress
                    result["status"] = "triggered"
                    result["detection_time"] = time.time() - start_time
                    result["cpu_usage"] = top_result.stdout.strip()
                    logger.info(f"CPU throttling detected in {result['detection_time']:.1f}s")
                    logger.info(f"CPU usage: {result['cpu_usage']}")
                    break
            
            time.sleep(5)
        
        if result["status"] != "triggered":
            result["status"] = "timeout"
        
        return result
        
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def cleanup(namespace: str = DEFAULT_NAMESPACE, pod_name: str = None):
    """Clean up resources."""
    try:
        if pod_name:
            subprocess.run(
                ["kubectl", "delete", "pod", pod_name, "-n", namespace, "--ignore-not-found"],
                capture_output=True
            )
        else:
            subprocess.run(
                ["kubectl", "delete", "pods", "-n", namespace, "-l", "app=fault-injection"],
                capture_output=True
            )
    except Exception as e:
        logger.error(f"Cleanup error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Inject CPU throttling fault")
    parser.add_argument("--namespace", "-n", default=DEFAULT_NAMESPACE)
    parser.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--cleanup", "-c", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    
    args = parser.parse_args()
    
    if args.cleanup:
        cleanup(args.namespace)
        return
    
    try:
        result = inject_cpu_throttling(args.namespace, args.timeout)
        print(f"\n{'='*60}")
        print("CPU Throttling Fault Injection Result:")
        print(f"{'='*60}")
        for key, value in result.items():
            print(f"  {key}: {value}")
        print(f"{'='*60}\n")
        
        if not args.no_cleanup:
            time.sleep(10)
            cleanup(args.namespace, result.get("pod_name"))
        
    except KeyboardInterrupt:
        cleanup(args.namespace)


if __name__ == "__main__":
    main()
