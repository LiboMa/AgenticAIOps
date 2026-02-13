"""
AgenticAIOps - Mock Mode

Mock implementations for demo/testing without a real EKS cluster.
Simulates realistic Kubernetes and AWS responses.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import random


class MockKubernetesTools:
    """Mock Kubernetes tools with realistic responses."""
    
    def __init__(self):
        # Simulated cluster state
        self.pods = [
            {
                "name": "payment-service-7d9f8b6c5-x2k4m",
                "namespace": "production",
                "phase": "Running",
                "node": "ip-10-0-1-45.ec2.internal",
                "containers": [
                    {
                        "name": "payment-api",
                        "ready": True,
                        "restart_count": 0,
                        "state": {"state": "running", "started_at": "2025-01-31T14:30:00Z"}
                    }
                ],
                "conditions": [{"type": "Ready", "status": "True"}],
                "created": "2025-01-31T14:30:00Z"
            },
            {
                "name": "inventory-api-5c8d7e6f4-crash",
                "namespace": "production",
                "phase": "Running",
                "node": "ip-10-0-1-46.ec2.internal",
                "containers": [
                    {
                        "name": "inventory",
                        "ready": False,
                        "restart_count": 8,
                        "state": {
                            "state": "waiting",
                            "reason": "CrashLoopBackOff",
                            "message": "Back-off restarting failed container"
                        }
                    }
                ],
                "conditions": [{"type": "Ready", "status": "False", "reason": "ContainersNotReady"}],
                "created": "2025-01-31T12:00:00Z"
            },
            {
                "name": "user-service-6e7f8g9h0-oom",
                "namespace": "production",
                "phase": "Running",
                "node": "ip-10-0-1-47.ec2.internal",
                "containers": [
                    {
                        "name": "user-api",
                        "ready": False,
                        "restart_count": 5,
                        "state": {
                            "state": "terminated",
                            "reason": "OOMKilled",
                            "exit_code": 137,
                            "message": "Container exceeded memory limit"
                        }
                    }
                ],
                "conditions": [{"type": "Ready", "status": "False"}],
                "created": "2025-01-31T10:00:00Z"
            }
        ]
        
        self.events = [
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "object": "Pod/inventory-api-5c8d7e6f4-crash",
                "namespace": "production",
                "count": 15,
                "first_seen": "2025-01-31T12:05:00Z",
                "last_seen": "2025-01-31T15:45:00Z"
            },
            {
                "type": "Warning",
                "reason": "OOMKilled",
                "message": "Container user-api exceeded memory limit (256Mi)",
                "object": "Pod/user-service-6e7f8g9h0-oom",
                "namespace": "production",
                "count": 5,
                "first_seen": "2025-01-31T14:00:00Z",
                "last_seen": "2025-01-31T15:40:00Z"
            }
        ]
        
        self.logs = {
            "inventory-api-5c8d7e6f4-crash": """
2025-01-31 15:44:32 INFO  Starting Inventory Service v2.3.1
2025-01-31 15:44:32 INFO  Connecting to database...
2025-01-31 15:44:33 ERROR Failed to connect to database: Connection refused
2025-01-31 15:44:33 ERROR Host: inventory-db.production.svc.cluster.local:5432
2025-01-31 15:44:33 FATAL Cannot start without database connection
2025-01-31 15:44:33 FATAL Exiting with code 1
""",
            "user-service-6e7f8g9h0-oom": """
2025-01-31 15:38:15 INFO  Starting User Service v1.8.0
2025-01-31 15:38:16 INFO  Loading user cache...
2025-01-31 15:38:45 WARN  Memory usage high: 240Mi / 256Mi
2025-01-31 15:38:52 WARN  Memory usage critical: 255Mi / 256Mi
2025-01-31 15:38:53 ERROR Out of memory, cannot allocate 10MB for cache
Killed
"""
        }
    
    def get_pods(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """Mock get_pods."""
        if namespace == "all":
            pods = self.pods
        else:
            pods = [p for p in self.pods if p["namespace"] == namespace]
        
        return {
            "success": True,
            "count": len(pods),
            "pods": pods
        }
    
    def get_pod_logs(
        self,
        pod_name: str,
        namespace: str = "default",
        container: Optional[str] = None,
        tail_lines: int = 100,
        previous: bool = False
    ) -> Dict[str, Any]:
        """Mock get_pod_logs."""
        logs = self.logs.get(pod_name, "No logs available")
        
        return {
            "success": True,
            "pod": pod_name,
            "namespace": namespace,
            "container": container,
            "lines": tail_lines,
            "logs": logs.strip()
        }
    
    def describe_pod(self, pod_name: str, namespace: str = "default") -> Dict[str, Any]:
        """Mock describe_pod."""
        for pod in self.pods:
            if pod["name"] == pod_name:
                # Add resource info for describe
                pod_detail = dict(pod)
                pod_detail["resources"] = {
                    "requests": {"memory": "128Mi", "cpu": "100m"},
                    "limits": {"memory": "256Mi", "cpu": "500m"}
                }
                return {
                    "success": True,
                    "pod": pod_detail
                }
        
        return {
            "success": False,
            "error": f"Pod {pod_name} not found"
        }
    
    def get_events(
        self,
        namespace: str = "default",
        field_selector: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Mock get_events."""
        events = self.events
        if namespace != "all":
            events = [e for e in events if e["namespace"] == namespace]
        
        return {
            "success": True,
            "count": len(events),
            "events": events
        }
    
    def get_deployments(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """Mock get_deployments."""
        deployments = [
            {
                "name": "payment-service",
                "namespace": "production",
                "replicas": {"desired": 3, "ready": 3, "available": 3, "updated": 3},
                "strategy": "RollingUpdate",
                "conditions": [{"type": "Available", "status": "True"}],
                "created": "2025-01-30T10:00:00Z"
            },
            {
                "name": "inventory-api",
                "namespace": "production",
                "replicas": {"desired": 2, "ready": 0, "available": 0, "updated": 2},
                "strategy": "RollingUpdate",
                "conditions": [
                    {"type": "Available", "status": "False", "message": "Deployment does not have minimum availability"}
                ],
                "created": "2025-01-30T10:00:00Z"
            },
            {
                "name": "user-service",
                "namespace": "production",
                "replicas": {"desired": 2, "ready": 1, "available": 1, "updated": 2},
                "strategy": "RollingUpdate",
                "conditions": [{"type": "Available", "status": "True"}],
                "created": "2025-01-30T10:00:00Z"
            }
        ]
        
        if namespace != "all":
            deployments = [d for d in deployments if d["namespace"] == namespace]
        
        return {
            "success": True,
            "count": len(deployments),
            "deployments": deployments
        }
    
    def scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """Mock scale_deployment."""
        return {
            "success": True,
            "deployment": deployment_name,
            "namespace": namespace,
            "old_replicas": 2,
            "new_replicas": replicas,
            "message": f"Scaled {deployment_name} from 2 to {replicas} replicas"
        }
    
    def restart_deployment(
        self,
        deployment_name: str,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """Mock restart_deployment."""
        return {
            "success": True,
            "deployment": deployment_name,
            "namespace": namespace,
            "message": f"Initiated rolling restart for {deployment_name}",
            "restarted_at": datetime.now(timezone.utc).isoformat()
        }


class MockAWSTools:
    """Mock AWS tools with realistic responses."""
    
    def __init__(self, cluster_name: str = "demo-cluster", region: str = "us-east-1"):
        self.cluster_name = cluster_name
        self.region = region
    
    def describe_cluster(self, cluster_name: str) -> Dict[str, Any]:
        """Mock describe_cluster."""
        return {
            "success": True,
            "cluster": {
                "name": cluster_name,
                "arn": f"arn:aws:eks:{self.region}:123456789:cluster/{cluster_name}",
                "version": "1.28",
                "status": "ACTIVE",
                "endpoint": f"https://{cluster_name}.eks.{self.region}.amazonaws.com",
                "role_arn": "arn:aws:iam::123456789:role/eks-cluster-role",
                "vpc_id": "vpc-0123456789abcdef",
                "subnets": ["subnet-1", "subnet-2", "subnet-3"],
                "security_groups": ["sg-123456"],
                "created_at": "2025-01-01T00:00:00Z",
                "platform_version": "eks.5",
                "tags": {"Environment": "production"}
            }
        }
    
    def list_nodegroups(self, cluster_name: str) -> Dict[str, Any]:
        """Mock list_nodegroups."""
        return {
            "success": True,
            "cluster": cluster_name,
            "count": 2,
            "nodegroups": [
                {
                    "name": "general-workers",
                    "status": "ACTIVE",
                    "instance_types": ["m5.large"],
                    "scaling": {"min": 2, "max": 10, "desired": 3},
                    "ami_type": "AL2_x86_64",
                    "disk_size": 100,
                    "health": []
                },
                {
                    "name": "spot-workers",
                    "status": "ACTIVE",
                    "instance_types": ["m5.large", "m5.xlarge"],
                    "scaling": {"min": 0, "max": 20, "desired": 5},
                    "ami_type": "AL2_x86_64",
                    "disk_size": 100,
                    "health": []
                }
            ]
        }
    
    def get_node_health(self, cluster_name: str) -> Dict[str, Any]:
        """Mock get_node_health."""
        return {
            "success": True,
            "cluster": cluster_name,
            "count": 3,
            "nodes": [
                {
                    "instance_id": "i-0123456789abcdef0",
                    "name": "ip-10-0-1-45.ec2.internal",
                    "type": "m5.large",
                    "state": "running",
                    "private_ip": "10.0.1.45",
                    "availability_zone": "us-east-1a",
                    "system_status": "ok",
                    "instance_status": "ok"
                },
                {
                    "instance_id": "i-0123456789abcdef1",
                    "name": "ip-10-0-1-46.ec2.internal",
                    "type": "m5.large",
                    "state": "running",
                    "private_ip": "10.0.1.46",
                    "availability_zone": "us-east-1b",
                    "system_status": "ok",
                    "instance_status": "ok"
                },
                {
                    "instance_id": "i-0123456789abcdef2",
                    "name": "ip-10-0-1-47.ec2.internal",
                    "type": "m5.large",
                    "state": "running",
                    "private_ip": "10.0.1.47",
                    "availability_zone": "us-east-1c",
                    "system_status": "ok",
                    "instance_status": "ok"
                }
            ]
        }


def create_mock_trace() -> str:
    """
    Generate a realistic trace of agent behavior.
    Shows the ReAct loop in action.
    """
    trace = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                    AgenticAIOps - Execution Trace                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Cluster: demo-eks-cluster | Region: us-east-1 | Model: claude-3-sonnet       ║
╚══════════════════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:01] USER INPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Check what's wrong with my production cluster"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:02] 🧠 REASON (LLM Decision)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LLM is analyzing the request and available tools...
Decision: Need to check pod status across all namespaces first.
Selected tool: get_pods

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:03] 🔧 ACT (Tool Call #1)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool: get_pods
Args: {"namespace": "production"}
Duration: 245ms

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:03] 👁 OBSERVE (Tool Result)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "success": true,
  "count": 3,
  "pods": [
    {"name": "payment-service-7d9f8b6c5-x2k4m", "phase": "Running", "ready": true},
    {"name": "inventory-api-5c8d7e6f4-crash", "phase": "Running", 
     "containers": [{"state": "CrashLoopBackOff", "restart_count": 8}]},  ⚠️
    {"name": "user-service-6e7f8g9h0-oom", "phase": "Running",
     "containers": [{"state": "OOMKilled", "restart_count": 5}]}  ⚠️
  ]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:04] 🧠 REASON (LLM Decision)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LLM analyzing results...
Found 2 problematic pods:
  - inventory-api: CrashLoopBackOff (8 restarts)
  - user-service: OOMKilled (5 restarts)
Decision: Get logs from the CrashLoopBackOff pod first (more critical).
Selected tool: get_pod_logs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:05] 🔧 ACT (Tool Call #2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool: get_pod_logs
Args: {"pod_name": "inventory-api-5c8d7e6f4-crash", "namespace": "production", "tail_lines": 50}
Duration: 312ms

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:05] 👁 OBSERVE (Tool Result)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "logs": "2025-01-31 15:44:32 INFO  Starting Inventory Service v2.3.1
           2025-01-31 15:44:33 ERROR Failed to connect to database: Connection refused
           2025-01-31 15:44:33 ERROR Host: inventory-db.production.svc.cluster.local:5432
           2025-01-31 15:44:33 FATAL Cannot start without database connection
           2025-01-31 15:44:33 FATAL Exiting with code 1"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:06] 🧠 REASON (LLM Decision)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LLM analyzing logs...
Root cause identified: Database connection refused (inventory-db service)
Decision: Also check the OOMKilled pod for completeness.
Selected tool: get_pod_logs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:07] 🔧 ACT (Tool Call #3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool: get_pod_logs
Args: {"pod_name": "user-service-6e7f8g9h0-oom", "namespace": "production", "tail_lines": 50}
Duration: 287ms

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:07] 👁 OBSERVE (Tool Result)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "logs": "2025-01-31 15:38:15 INFO  Starting User Service v1.8.0
           2025-01-31 15:38:45 WARN  Memory usage high: 240Mi / 256Mi
           2025-01-31 15:38:52 WARN  Memory usage critical: 255Mi / 256Mi
           2025-01-31 15:38:53 ERROR Out of memory, cannot allocate 10MB for cache
           Killed"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:08] 🧠 REASON (LLM Decision)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LLM analyzing all gathered information...
Root causes identified:
  1. inventory-api: Database connectivity issue
  2. user-service: Memory limit too low (256Mi insufficient)
Decision: Information is sufficient. Generate comprehensive response.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:09] 📝 RESPOND (Final Output)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 **Cluster Health Report**

I found **2 critical issues** in your production cluster:

---

### 🔴 Issue 1: inventory-api (CrashLoopBackOff)

**Pod**: `inventory-api-5c8d7e6f4-crash`
**Status**: CrashLoopBackOff (8 restarts)
**Root Cause**: Database connection refused

```
ERROR Failed to connect to database: Connection refused
Host: inventory-db.production.svc.cluster.local:5432
FATAL Cannot start without database connection
```

**Recommendations**:
1. Check if `inventory-db` service/pod is running
2. Verify database credentials
3. Check network policies between pods

---

### 🟠 Issue 2: user-service (OOMKilled)

**Pod**: `user-service-6e7f8g9h0-oom`
**Status**: OOMKilled (5 restarts)
**Root Cause**: Memory limit (256Mi) exceeded

```
WARN  Memory usage critical: 255Mi / 256Mi
ERROR Out of memory, cannot allocate 10MB for cache
```

**Recommendations**:
1. Increase memory limit to at least 512Mi
2. Review recent changes for memory leaks
3. Add memory profiling to identify hot spots

---

**Would you like me to:**
- [ ] Scale up user-service memory limit?
- [ ] Investigate the inventory-db service?
- [ ] Restart affected deployments after fixes?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15:45:09] ✅ COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Duration: 8.2s
Tool Calls: 3
Tokens: ~2,400 (input) + ~800 (output)

══════════════════════════════════════════════════════════════════════════════
"""
    return trace


if __name__ == "__main__":
    print(create_mock_trace())
