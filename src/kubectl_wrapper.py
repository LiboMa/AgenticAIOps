"""
AgenticAIOps - kubectl wrapper for fast K8s API access.

Uses subprocess to call kubectl directly, which is faster than the Python kubernetes client.
"""

import subprocess
import json
import time
from typing import Optional, Dict, Any, List
from functools import lru_cache

# Simple in-memory cache
_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 30  # seconds


def _get_cached(key: str, fetch_func, ttl: int = CACHE_TTL):
    """Get data from cache or fetch it."""
    now = time.time()
    if key in _cache and now - _cache[key]['time'] < ttl:
        return _cache[key]['data']
    data = fetch_func()
    _cache[key] = {'data': data, 'time': now}
    return data


def kubectl_run(args: List[str], timeout: int = 10) -> Optional[str]:
    """Run kubectl command and return stdout."""
    try:
        result = subprocess.run(
            ['kubectl'] + args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0:
            return result.stdout
        print(f"kubectl error: {result.stderr}")
        return None
    except subprocess.TimeoutExpired:
        print(f"kubectl timeout: {args}")
        return None
    except Exception as e:
        print(f"kubectl exception: {e}")
        return None


def kubectl_json(args: List[str], timeout: int = 10) -> Optional[Dict]:
    """Run kubectl command and return JSON output."""
    output = kubectl_run(args + ['-o', 'json'], timeout)
    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return None
    return None


def get_pods(namespace: Optional[str] = None) -> Dict[str, Any]:
    """Get all pods, optionally filtered by namespace."""
    def fetch():
        if namespace and namespace != 'all':
            data = kubectl_json(['get', 'pods', '-n', namespace])
        else:
            data = kubectl_json(['get', 'pods', '-A'])
        
        if not data:
            return {"pods": []}
        
        pods = []
        for item in data.get('items', []):
            status = item.get('status', {})
            container_statuses = status.get('containerStatuses', [{}])
            
            # Determine pod status
            phase = status.get('phase', 'Unknown')
            if container_statuses:
                cs = container_statuses[0]
                if cs.get('state', {}).get('waiting', {}).get('reason'):
                    phase = cs['state']['waiting']['reason']
                elif cs.get('lastState', {}).get('terminated', {}).get('reason'):
                    last_reason = cs['lastState']['terminated']['reason']
                    if last_reason == 'OOMKilled':
                        phase = 'OOMKilled'
            
            pods.append({
                "name": item.get('metadata', {}).get('name', ''),
                "namespace": item.get('metadata', {}).get('namespace', ''),
                "status": phase,
                "restarts": container_statuses[0].get('restartCount', 0) if container_statuses else 0,
                "ready": f"{sum(1 for cs in container_statuses if cs.get('ready'))}/{len(container_statuses)}"
            })
        
        return {"pods": pods}
    
    cache_key = f"pods_{namespace or 'all'}"
    return _get_cached(cache_key, fetch)


def get_nodes() -> Dict[str, Any]:
    """Get all nodes."""
    def fetch():
        data = kubectl_json(['get', 'nodes'])
        
        if not data:
            return {"nodes": []}
        
        nodes = []
        for item in data.get('items', []):
            conditions = item.get('status', {}).get('conditions', [])
            ready = next((c for c in conditions if c.get('type') == 'Ready'), {})
            
            nodes.append({
                "name": item.get('metadata', {}).get('name', ''),
                "status": "Ready" if ready.get('status') == 'True' else "NotReady",
                "version": item.get('status', {}).get('nodeInfo', {}).get('kubeletVersion', ''),
                "cpu": "N/A",
                "memory": "N/A"
            })
        
        return {"nodes": nodes}
    
    return _get_cached("nodes", fetch)


def get_deployments(namespace: Optional[str] = None) -> Dict[str, Any]:
    """Get all deployments."""
    def fetch():
        if namespace and namespace != 'all':
            data = kubectl_json(['get', 'deployments', '-n', namespace])
        else:
            data = kubectl_json(['get', 'deployments', '-A'])
        
        if not data:
            return {"deployments": []}
        
        deployments = []
        for item in data.get('items', []):
            status = item.get('status', {})
            deployments.append({
                "name": item.get('metadata', {}).get('name', ''),
                "namespace": item.get('metadata', {}).get('namespace', ''),
                "replicas": status.get('replicas', 0),
                "ready": status.get('readyReplicas', 0),
                "available": status.get('availableReplicas', 0)
            })
        
        return {"deployments": deployments}
    
    cache_key = f"deployments_{namespace or 'all'}"
    return _get_cached(cache_key, fetch)


def get_events(namespace: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Get recent events."""
    def fetch():
        if namespace and namespace != 'all':
            data = kubectl_json(['get', 'events', '-n', namespace, '--sort-by=.lastTimestamp'])
        else:
            data = kubectl_json(['get', 'events', '-A', '--sort-by=.lastTimestamp'])
        
        if not data:
            return {"events": []}
        
        events = []
        for item in data.get('items', [])[-limit:]:
            events.append({
                "type": item.get('type', ''),
                "reason": item.get('reason', ''),
                "message": item.get('message', '')[:200],
                "namespace": item.get('metadata', {}).get('namespace', ''),
                "object": item.get('involvedObject', {}).get('name', ''),
                "count": item.get('count', 1)
            })
        
        return {"events": list(reversed(events))}
    
    cache_key = f"events_{namespace or 'all'}"
    return _get_cached(cache_key, fetch, ttl=10)  # Shorter TTL for events


def get_pod_logs(namespace: str, pod_name: str, lines: int = 100) -> Dict[str, Any]:
    """Get logs from a pod."""
    output = kubectl_run(['logs', pod_name, '-n', namespace, f'--tail={lines}'])
    return {"logs": output or "No logs available"}


def describe_pod(namespace: str, pod_name: str) -> Dict[str, Any]:
    """Describe a pod."""
    output = kubectl_run(['describe', 'pod', pod_name, '-n', namespace])
    return {"description": output or "Pod not found"}


def get_cluster_info() -> Dict[str, Any]:
    """Get cluster info."""
    def fetch():
        # Get version
        version_output = kubectl_run(['version', '--short'], timeout=5)
        version = "unknown"
        if version_output:
            for line in version_output.split('\n'):
                if 'Server' in line:
                    version = line.split(':')[-1].strip()
                    break
        
        # Get cluster context
        context_output = kubectl_run(['config', 'current-context'], timeout=5)
        cluster_name = context_output.strip() if context_output else "unknown"
        
        return {
            "name": cluster_name,
            "version": version,
            "status": "ACTIVE",
            "region": "ap-southeast-1"
        }
    
    return _get_cached("cluster_info", fetch, ttl=60)


def get_cluster_health() -> Dict[str, Any]:
    """Get cluster health summary."""
    nodes = get_nodes()
    pods = get_pods()
    
    ready_nodes = sum(1 for n in nodes.get('nodes', []) if n.get('status') == 'Ready')
    total_nodes = len(nodes.get('nodes', []))
    
    running_pods = sum(1 for p in pods.get('pods', []) if p.get('status') == 'Running')
    total_pods = len(pods.get('pods', []))
    
    # Determine health status
    if ready_nodes == total_nodes and running_pods >= total_pods * 0.8:
        status = "healthy"
    elif ready_nodes < total_nodes or running_pods < total_pods * 0.5:
        status = "critical"
    else:
        status = "degraded"
    
    return {
        "status": status,
        "nodes": {"ready": ready_nodes, "total": total_nodes},
        "pods": {"running": running_pods, "total": total_pods}
    }


# Test
if __name__ == "__main__":
    print("Testing kubectl wrapper...")
    
    print("\n1. Cluster Info:")
    print(json.dumps(get_cluster_info(), indent=2))
    
    print("\n2. Nodes:")
    nodes = get_nodes()
    print(f"Found {len(nodes.get('nodes', []))} nodes")
    
    print("\n3. Pods:")
    pods = get_pods()
    print(f"Found {len(pods.get('pods', []))} pods")
    for p in pods.get('pods', [])[:5]:
        print(f"  - {p['namespace']}/{p['name']}: {p['status']}")
    
    print("\n4. Cluster Health:")
    print(json.dumps(get_cluster_health(), indent=2))
