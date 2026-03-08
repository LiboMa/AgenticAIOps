#!/usr/bin/env python3
"""
Fault Injection: Service Unreachable

Injects service connectivity error by creating service with no matching pods.
Based on AIOpsLab P=⟨T,C,S⟩ framework.

Problem Definition:
- T (Task): Detection + Localization
- C (Context): Service has no endpoints (selector mismatch)
- S (Solution): Identify empty endpoints, fix selector
"""

import argparse
import logging
import subprocess
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_NAMESPACE = "stress-test"
DEFAULT_TIMEOUT = 60


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


def inject_service_error(namespace: str = DEFAULT_NAMESPACE, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Inject service unreachable error.
    Creates a service with selector that matches no pods.
    """
    service_name = f"broken-svc-{int(time.time())}"
    
    # Service with selector that matches nothing
    service_manifest = f"""
apiVersion: v1
kind: Service
metadata:
  name: {service_name}
  namespace: {namespace}
  labels:
    app: fault-injection
    fault-type: service-unreachable
spec:
  selector:
    app: nonexistent-app-{int(time.time())}
  ports:
  - port: 80
    targetPort: 8080
"""
    
    result = {
        "status": "unknown",
        "service_name": service_name,
        "namespace": namespace,
        "fault_type": "service_unreachable",
        "start_time": datetime.now().isoformat(),
    }
    
    try:
        if not create_namespace(namespace):
            result["status"] = "failed"
            return result
        
        logger.info(f"Injecting Service Unreachable: {service_name}")
        process = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=service_manifest,
            capture_output=True,
            text=True
        )
        
        if process.returncode != 0:
            result["status"] = "failed"
            result["error"] = process.stderr
            return result
        
        result["status"] = "injected"
        
        # Verify empty endpoints
        logger.info("Verifying empty endpoints...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check endpoints
            ep_result = subprocess.run(
                ["kubectl", "get", "endpoints", service_name, "-n", namespace,
                 "-o", "jsonpath={.subsets}"],
                capture_output=True, text=True
            )
            
            # Empty subsets means no matching pods
            if ep_result.returncode == 0 and not ep_result.stdout.strip():
                result["status"] = "triggered"
                result["detection_time"] = time.time() - start_time
                result["endpoints"] = "empty"
                logger.info(f"Service unreachable confirmed in {result['detection_time']:.1f}s")
                break
            
            time.sleep(2)
        
        if result["status"] != "triggered":
            result["status"] = "timeout"
        
        return result
        
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def cleanup(namespace: str = DEFAULT_NAMESPACE, service_name: str = None):
    """Clean up resources."""
    try:
        if service_name:
            subprocess.run(
                ["kubectl", "delete", "service", service_name, "-n", namespace, "--ignore-not-found"],
                capture_output=True
            )
        else:
            subprocess.run(
                ["kubectl", "delete", "services", "-n", namespace, "-l", "app=fault-injection"],
                capture_output=True
            )
    except Exception as e:
        logger.error(f"Cleanup error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Inject Service Unreachable fault")
    parser.add_argument("--namespace", "-n", default=DEFAULT_NAMESPACE)
    parser.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--cleanup", "-c", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    
    args = parser.parse_args()
    
    if args.cleanup:
        cleanup(args.namespace)
        return
    
    try:
        result = inject_service_error(args.namespace, args.timeout)
        print(f"\n{'='*60}")
        print("Service Unreachable Fault Injection Result:")
        print(f"{'='*60}")
        for key, value in result.items():
            print(f"  {key}: {value}")
        print(f"{'='*60}\n")
        
        if not args.no_cleanup:
            time.sleep(5)
            cleanup(args.namespace, result.get("service_name"))
        
    except KeyboardInterrupt:
        cleanup(args.namespace)


if __name__ == "__main__":
    main()
