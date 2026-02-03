#!/usr/bin/env python3
"""
AgenticAIOps - Backend API Server

FastAPI server providing REST endpoints for the React dashboard.
"""

import os
import json
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Import our modules (handle import errors gracefully)
K8S_TOOLS_AVAILABLE = False

try:
    from src.kubectl_wrapper import (
        get_pods, get_deployments, get_nodes, get_events,
        get_pod_logs, describe_pod, get_cluster_info, get_cluster_health
    )
    K8S_TOOLS_AVAILABLE = True
    print("kubectl wrapper loaded successfully")
except Exception as e:
    print(f"Warning: kubectl wrapper not available: {e}")
    # Define mock functions
    def get_pods(ns=None): return {"pods": []}
    def get_deployments(ns=None): return {"deployments": []}
    def get_nodes(): return {"nodes": []}
    def get_events(ns=None): return {"events": []}
    def get_pod_logs(ns, name, lines=100): return {"logs": ""}
    def describe_pod(ns, name): return {}
    def get_cluster_health(): return {"status": "unknown"}
    def get_cluster_info(): return {"name": "testing-cluster", "version": "1.32", "status": "ACTIVE", "region": "ap-southeast-1"}

def get_hpa(ns=None): return {"hpas": []}

from src.intent_classifier import analyze_query
from src.multi_agent_voting import extract_diagnosis, simple_vote

# Import plugin system
from src.plugins import PluginRegistry, PluginConfig
from src.plugins.eks_plugin import EKSPlugin
from src.plugins.ec2_plugin import EC2Plugin
from src.plugins.lambda_plugin import LambdaPlugin
from src.plugins.hpc_plugin import HPCPlugin

# Import ACI for real telemetry data
try:
    from src.aci import AgentCloudInterface
    ACI_AVAILABLE = True
    print("ACI (Agent-Cloud Interface) loaded successfully")
except Exception as e:
    print(f"Warning: ACI not available: {e}")
    ACI_AVAILABLE = False

# Import Voting for diagnosis
try:
    from src.voting import MultiAgentVoting, TaskType
    VOTING_AVAILABLE = True
    print("Multi-Agent Voting loaded successfully")
except Exception as e:
    print(f"Warning: Voting not available: {e}")
    VOTING_AVAILABLE = False

# Import Issue Manager
try:
    from src.issues import IssueManager
    ISSUES_AVAILABLE = True
    _issue_manager = None
    print("Issue Manager loaded successfully")
except Exception as e:
    print(f"Warning: Issue Manager not available: {e}")
    ISSUES_AVAILABLE = False

# Import Runbook Executor
try:
    from src.runbook import RunbookExecutor, RunbookLoader
    RUNBOOK_AVAILABLE = True
    _runbook_executor = None
    print("Runbook Executor loaded successfully")
except Exception as e:
    print(f"Warning: Runbook Executor not available: {e}")
    RUNBOOK_AVAILABLE = False

# Import Health Checker
try:
    from src.health import HealthChecker, HealthCheckScheduler, HealthCheckConfig
    HEALTH_AVAILABLE = True
    _health_scheduler = None
    print("Health Checker loaded successfully")
except Exception as e:
    print(f"Warning: Health Checker not available: {e}")
    HEALTH_AVAILABLE = False

app = FastAPI(
    title="AgenticAIOps API",
    description="Backend API for EKS AIOps Dashboard",
    version="1.0.0"
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response models
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    intent: Optional[str] = None
    confidence: Optional[float] = None


# =============================================================================
# Strands Agent Integration
# =============================================================================

_agent = None

def get_agent():
    """Get or create the Strands Agent instance."""
    global _agent
    if _agent is None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
            from src.config import get_model_id, AWS_REGION
            from strands_agent_full import (
                get_cluster_health as eks_health,
                get_cluster_info as eks_info,
                get_nodes as eks_nodes,
                get_pods as eks_pods,
                get_deployments as eks_deployments,
                get_events as eks_events,
                get_pod_logs as eks_logs,
                scale_deployment
            )
            
            # Get model from environment or default
            import os
            model_name = os.environ.get("AGENT_MODEL", "haiku")
            model_id = get_model_id(model_name)
            
            print(f"Initializing Strands Agent with model: {model_id}")
            
            model = BedrockModel(
                model_id=model_id,
                region_name=AWS_REGION
            )
            
            system_prompt = """You are an expert SRE AI assistant for Amazon EKS clusters.
            
You help diagnose issues, check cluster health, and provide recommendations.
Be concise but thorough. Always check relevant data before making conclusions."""
            
            _agent = Agent(
                model=model,
                tools=[eks_health, eks_info, eks_nodes, eks_pods, 
                       eks_deployments, eks_events, eks_logs, scale_deployment],
                system_prompt=system_prompt
            )
            print("Strands Agent initialized successfully")
        except Exception as e:
            print(f"Failed to initialize Strands Agent: {e}")
            _agent = None
    return _agent


# =============================================================================
# Chat Endpoint (integrates with Strands Agent)
# =============================================================================

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat with the AIOps agent."""
    try:
        # Classify intent
        analysis = analyze_query(request.message)
        
        # Try to use real Strands Agent
        agent = get_agent()
        
        if agent:
            # Call real agent
            result = agent(request.message)
            response_text = str(result)
        else:
            # Fallback to intent-based response
            response_text = f"""Intent: {analysis['intent']} (confidence: {analysis['confidence']:.0%})

Recommended tools: {', '.join(analysis['recommended_tools'][:3])}

[Agent not available - showing intent analysis only]"""
        
        return ChatResponse(
            response=response_text,
            intent=analysis['intent'],
            confidence=analysis['confidence']
        )
    except Exception as e:
        import traceback
        return ChatResponse(response=f"Error: {str(e)}\n{traceback.format_exc()}")


# =============================================================================
# Cluster Endpoints
# =============================================================================

@app.get("/api/cluster/info")
async def cluster_info():
    """Get cluster information."""
    try:
        return get_cluster_info()
    except Exception as e:
        # Return mock data on error
        return {
            "name": "testing-cluster",
            "version": "1.32",
            "status": "ACTIVE",
            "region": "ap-southeast-1"
        }


@app.get("/api/cluster/health")
async def cluster_health():
    """Get cluster health status."""
    try:
        return get_cluster_health()
    except Exception as e:
        return {"status": "unknown", "error": str(e)}


# =============================================================================
# Pod Endpoints
# =============================================================================

@app.get("/api/pods")
async def list_pods(namespace: Optional[str] = None):
    """List all pods, optionally filtered by namespace."""
    try:
        return get_pods(namespace)
    except Exception as e:
        return {"pods": [], "error": str(e)}


@app.get("/api/pods/{namespace}/{name}")
async def pod_details(namespace: str, name: str):
    """Get detailed information about a specific pod."""
    try:
        return describe_pod(namespace, name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/pods/{namespace}/{name}/logs")
async def pod_logs(namespace: str, name: str, lines: int = 100):
    """Get logs from a specific pod."""
    try:
        return get_pod_logs(namespace, name, lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Node Endpoints
# =============================================================================

@app.get("/api/nodes")
async def list_nodes():
    """List all nodes in the cluster."""
    try:
        return get_nodes()
    except Exception as e:
        return {"nodes": [], "error": str(e)}


# =============================================================================
# Deployment Endpoints
# =============================================================================

@app.get("/api/deployments")
async def list_deployments(namespace: Optional[str] = None):
    """List all deployments."""
    try:
        return get_deployments(namespace)
    except Exception as e:
        return {"deployments": [], "error": str(e)}


# =============================================================================
# Events Endpoint
# =============================================================================

@app.get("/api/events")
async def list_events(namespace: Optional[str] = None):
    """Get recent cluster events."""
    try:
        return get_events(namespace)
    except Exception as e:
        return {"events": [], "error": str(e)}


# =============================================================================
# Anomaly Detection Endpoint
# =============================================================================

@app.get("/api/anomalies")
async def detect_anomalies():
    """Detect anomalies in the cluster."""
    anomalies = []
    
    try:
        # Get pods and check for issues
        pods_data = get_pods()
        
        for pod in pods_data.get('pods', []):
            status = pod.get('status', '')
            restarts = pod.get('restarts', 0)
            
            if 'CrashLoop' in status:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "critical",
                    "type": "CrashLoopBackOff",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": f"Pod has restarted {restarts} times",
                    "timestamp": datetime.utcnow().isoformat(),
                    "aiSuggestion": "Check application logs and configuration."
                })
            elif 'OOM' in status:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "critical", 
                    "type": "OOMKilled",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": "Container killed due to out of memory",
                    "timestamp": datetime.utcnow().isoformat(),
                    "aiSuggestion": "Increase memory limits in deployment spec."
                })
            elif restarts > 5:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "warning",
                    "type": "HighRestarts",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": f"Pod restart count ({restarts}) exceeds threshold",
                    "timestamp": datetime.utcnow().isoformat(),
                    "aiSuggestion": "Review application health and probe configurations."
                })
                
    except Exception as e:
        pass  # Return empty list on error
    
    return {"anomalies": anomalies}


# =============================================================================
# RCA Reports Endpoints
# =============================================================================

class RCAReport(BaseModel):
    id: str
    title: str
    status: str
    severity: str
    createdAt: str
    resolvedAt: Optional[str]
    rootCause: str
    symptoms: List[str]
    diagnosis: dict
    solution: str
    commands: List[str]


@app.get("/api/rca/reports")
async def list_rca_reports():
    """List all RCA reports."""
    return {"reports": rca_reports}


@app.post("/api/rca/reports")
async def create_rca_report(report: RCAReport):
    """Create a new RCA report."""
    rca_reports.append(report.dict())
    return {"status": "created", "id": report.id}


@app.get("/api/rca/reports/{report_id}")
async def get_rca_report(report_id: str):
    """Get a specific RCA report."""
    for report in rca_reports:
        if report["id"] == report_id:
            return report
    raise HTTPException(status_code=404, detail="Report not found")


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# =============================================================================
# Plugin System Endpoints
# =============================================================================

class PluginCreateRequest(BaseModel):
    plugin_type: str
    name: str
    config: dict = {}


class ClusterAddRequest(BaseModel):
    cluster_id: str
    name: str
    region: str
    plugin_type: str
    config: dict = {}


# Initialize default plugins on startup
@app.on_event("startup")
async def startup_event():
    """Initialize plugins from manifests on startup."""
    try:
        # Try loading from manifests first
        import os
        config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
        loaded = PluginRegistry.load_from_manifests(config_dir)
        
        if loaded == 0:
            # Fallback to default EKS plugin if no manifests
            eks_config = PluginConfig(
                plugin_id="eks-default",
                plugin_type="eks",
                name="EKS Default",
                enabled=True,
                config={"regions": ["ap-southeast-1"]}
            )
            PluginRegistry.create_plugin(eks_config)
        
        # Set active cluster if available
        clusters = PluginRegistry.get_clusters_by_type("eks")
        if clusters:
            PluginRegistry.set_active_cluster(clusters[0].cluster_id)
        
        print(f"Plugins initialized: {len(PluginRegistry.get_all_plugins())} plugins")
        print(f"Clusters discovered: {len(PluginRegistry.get_all_clusters())} clusters")
    except Exception as e:
        print(f"Warning: Failed to initialize plugins: {e}")


@app.get("/api/plugins")
async def list_plugins():
    """List all registered plugins."""
    return {
        "plugins": [p.get_info() for p in PluginRegistry.get_all_plugins()],
        "available_types": PluginRegistry.get_available_plugins()
    }


@app.post("/api/plugins")
async def create_plugin(request: PluginCreateRequest):
    """Create and register a new plugin."""
    import uuid
    
    config = PluginConfig(
        plugin_id=str(uuid.uuid4())[:8],
        plugin_type=request.plugin_type,
        name=request.name,
        enabled=True,
        config=request.config
    )
    
    plugin = PluginRegistry.create_plugin(config)
    if plugin:
        return {"status": "created", "plugin": plugin.get_info()}
    raise HTTPException(status_code=400, detail=f"Unknown plugin type: {request.plugin_type}")


@app.delete("/api/plugins/{plugin_id}")
async def remove_plugin(plugin_id: str):
    """Remove a plugin."""
    if PluginRegistry.remove_plugin(plugin_id):
        return {"status": "removed", "plugin_id": plugin_id}
    raise HTTPException(status_code=404, detail="Plugin not found")


@app.post("/api/plugins/{plugin_id}/enable")
async def enable_plugin(plugin_id: str):
    """Enable a plugin."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        plugin.enable()
        return {"status": "enabled", "plugin": plugin.get_info()}
    raise HTTPException(status_code=404, detail="Plugin not found")


@app.post("/api/plugins/{plugin_id}/disable")
async def disable_plugin(plugin_id: str):
    """Disable a plugin."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        plugin.disable()
        return {"status": "disabled", "plugin": plugin.get_info()}
    raise HTTPException(status_code=404, detail="Plugin not found")


@app.get("/api/plugins/{plugin_id}/status")
async def plugin_status(plugin_id: str):
    """Get plugin status and summary."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        return plugin.get_status_summary()
    raise HTTPException(status_code=404, detail="Plugin not found")


# =============================================================================
# Cluster Management Endpoints
# =============================================================================

@app.get("/api/clusters")
async def list_clusters(plugin_type: Optional[str] = None):
    """List all clusters/resources."""
    if plugin_type:
        clusters = PluginRegistry.get_clusters_by_type(plugin_type)
    else:
        clusters = PluginRegistry.get_all_clusters()
    
    active = PluginRegistry.get_active_cluster()
    
    return {
        "clusters": [c.to_dict() for c in clusters],
        "active_cluster": active.to_dict() if active else None
    }


@app.post("/api/clusters")
async def add_cluster(request: ClusterAddRequest):
    """Add a cluster manually."""
    from src.plugins.base import ClusterConfig
    
    cluster = ClusterConfig(
        cluster_id=request.cluster_id,
        name=request.name,
        region=request.region,
        plugin_type=request.plugin_type,
        config=request.config
    )
    PluginRegistry.add_cluster(cluster)
    return {"status": "added", "cluster": cluster.to_dict()}


@app.post("/api/clusters/{cluster_id}/activate")
async def activate_cluster(cluster_id: str):
    """Set a cluster as active."""
    if PluginRegistry.set_active_cluster(cluster_id):
        cluster = PluginRegistry.get_cluster(cluster_id)
        return {"status": "activated", "cluster": cluster.to_dict()}
    raise HTTPException(status_code=404, detail="Cluster not found")


@app.get("/api/clusters/active")
async def get_active_cluster():
    """Get the currently active cluster."""
    cluster = PluginRegistry.get_active_cluster()
    if cluster:
        return cluster.to_dict()
    return None


# =============================================================================
# Plugin Registry Status
# =============================================================================

@app.get("/api/registry/status")
async def registry_status():
    """Get overall plugin registry status."""
    return PluginRegistry.get_status()


# =============================================================================
# Manifest Management Endpoints
# =============================================================================

class ManifestRequest(BaseModel):
    name: str
    type: str
    description: str = ""
    icon: str = "🔌"
    enabled: bool = True
    config: dict = {}


@app.get("/api/manifests")
async def list_manifests():
    """List all plugin manifests."""
    from src.plugins.manifest import ManifestLoader
    import os
    
    config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
    loader = ManifestLoader(config_dir)
    manifests = loader.load_all()
    
    return {
        "manifests": [m.to_dict() for m in manifests],
        "config_dir": str(config_dir)
    }


@app.post("/api/manifests")
async def create_manifest(request: ManifestRequest):
    """Create a new plugin manifest."""
    from src.plugins.manifest import ManifestLoader, PluginManifest
    import os
    
    config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
    
    manifest = PluginManifest(
        name=request.name,
        type=request.type,
        description=request.description,
        icon=request.icon,
        enabled=request.enabled,
        config=request.config
    )
    
    loader = ManifestLoader(config_dir)
    if loader.save_manifest(manifest):
        return {"status": "created", "manifest": manifest.to_dict()}
    raise HTTPException(status_code=500, detail="Failed to save manifest")


@app.post("/api/manifests/reload")
async def reload_manifests():
    """Reload all plugins from manifests."""
    import os
    
    # Clear existing plugins
    for plugin_id in list(PluginRegistry._plugins.keys()):
        PluginRegistry.remove_plugin(plugin_id)
    
    config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
    loaded = PluginRegistry.load_from_manifests(config_dir)
    
    # Re-activate first cluster
    clusters = PluginRegistry.get_all_clusters()
    if clusters:
        PluginRegistry.set_active_cluster(clusters[0].cluster_id)
    
    return {
        "status": "reloaded",
        "plugins_loaded": loaded,
        "registry": PluginRegistry.get_status()
    }


# =============================================================================
# ACI (Agent-Cloud Interface) Endpoints - REAL DATA
# =============================================================================

class ACILogsRequest(BaseModel):
    namespace: str = "default"
    pod_name: Optional[str] = None
    severity: str = "all"
    duration_minutes: int = 30
    limit: int = 100


class ACIMetricsRequest(BaseModel):
    namespace: str = "default"
    metric_names: List[str] = ["cpu_usage", "memory_usage"]


class ACIEventsRequest(BaseModel):
    namespace: str = "default"
    event_type: str = "all"
    duration_minutes: int = 60
    limit: int = 50


class DiagnosisRequest(BaseModel):
    namespace: str = "default"
    query: str = "What is wrong with this namespace?"


@app.get("/api/aci/status")
async def aci_status():
    """Get ACI availability status."""
    return {
        "aci_available": ACI_AVAILABLE,
        "voting_available": VOTING_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/aci/logs")
async def get_aci_logs(request: ACILogsRequest):
    """Get logs via ACI."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": []}
    
    try:
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_logs(
            namespace=request.namespace,
            pod_name=request.pod_name,
            severity=request.severity,
            duration_minutes=request.duration_minutes,
            limit=request.limit
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": []}


@app.post("/api/aci/metrics")
async def get_aci_metrics(request: ACIMetricsRequest):
    """Get metrics via ACI (from Prometheus/CloudWatch)."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": {}}
    
    try:
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_metrics(
            namespace=request.namespace,
            metric_names=request.metric_names
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": {}}


@app.post("/api/aci/events")
async def get_aci_events(request: ACIEventsRequest):
    """Get K8s events via ACI."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": []}
    
    try:
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_events(
            namespace=request.namespace,
            event_type=request.event_type if request.event_type != "all" else None,
            duration_minutes=request.duration_minutes,
            limit=request.limit
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/api/aci/telemetry/{namespace}")
async def get_aci_telemetry(namespace: str):
    """Get all telemetry data for a namespace (logs, metrics, events)."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available"}
    
    try:
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        
        # Collect all telemetry
        logs = aci.get_logs(namespace=namespace, severity="error", limit=20)
        metrics = aci.get_metrics(namespace=namespace)
        events = aci.get_events(namespace=namespace, event_type="Warning", limit=30)
        
        return {
            "namespace": namespace,
            "timestamp": datetime.utcnow().isoformat(),
            "logs": logs.to_dict(),
            "metrics": metrics.to_dict(),
            "events": events.to_dict()
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/aci/diagnosis")
async def run_diagnosis(request: DiagnosisRequest):
    """Run multi-agent diagnosis on a namespace."""
    if not ACI_AVAILABLE or not VOTING_AVAILABLE:
        return {"error": "ACI or Voting not available"}
    
    try:
        from scripts.diagnosis.run_diagnosis import DiagnosisRunner
        
        runner = DiagnosisRunner(namespace=request.namespace)
        report = runner.run_diagnosis()
        
        return {
            "status": "success",
            "report": report
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


# =============================================================================
# Issue Management API
# =============================================================================

def get_issue_manager():
    """Get or create IssueManager instance."""
    global _issue_manager
    if not ISSUES_AVAILABLE:
        return None
    if _issue_manager is None:
        _issue_manager = IssueManager()
    return _issue_manager


def get_runbook_executor():
    """Get or create RunbookExecutor instance."""
    global _runbook_executor
    if not RUNBOOK_AVAILABLE:
        return None
    if _runbook_executor is None:
        _runbook_executor = RunbookExecutor()
    return _runbook_executor


@app.get("/api/issues")
async def list_issues(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    namespace: Optional[str] = None,
    limit: int = 50
):
    """List issues with optional filters."""
    manager = get_issue_manager()
    if not manager:
        return {"error": "Issue Manager not available", "issues": []}
    
    try:
        issues = manager.list_issues(
            status=status,
            severity=severity,
            namespace=namespace,
            limit=limit
        )
        return {"issues": [i.to_dict() for i in issues]}
    except Exception as e:
        return {"error": str(e), "issues": []}


@app.get("/api/issues/dashboard")
async def get_issues_dashboard():
    """Get dashboard summary data."""
    manager = get_issue_manager()
    if not manager:
        return {"error": "Issue Manager not available"}
    
    try:
        data = manager.get_dashboard_data()
        return data
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/issues/{issue_id}")
async def get_issue(issue_id: str):
    """Get issue by ID."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")
    
    issue = manager.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    return issue.to_dict()


class IssueCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str = "medium"
    namespace: str = "default"
    resource_type: str = "Pod"
    resource_name: str = ""
    root_cause: Optional[str] = None
    remediation: Optional[str] = None
    pattern_id: Optional[str] = None
    auto_fixable: bool = False


class IssueUpdateRequest(BaseModel):
    status: Optional[str] = None
    severity: Optional[str] = None
    root_cause: Optional[str] = None
    remediation: Optional[str] = None


@app.post("/api/issues")
async def create_issue(request: IssueCreateRequest):
    """Create a new issue."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")
    
    try:
        from src.issues import IssueType
        
        # Map pattern_id to IssueType
        type_map = {
            "oom_killed": IssueType.OOM_KILLED,
            "cpu_throttling": IssueType.CPU_THROTTLING,
            "crash_loop": IssueType.CRASH_LOOP,
            "image_pull_error": IssueType.IMAGE_PULL_ERROR,
            "memory_pressure": IssueType.MEMORY_PRESSURE,
        }
        issue_type = type_map.get(request.pattern_id, IssueType.UNKNOWN)
        
        issue = manager.create_issue(
            issue_type=issue_type,
            title=request.title,
            namespace=request.namespace,
            resource=request.resource_name,
            description=request.description or "",
            symptoms=[request.root_cause] if request.root_cause else [],
            metadata={
                "resource_type": request.resource_type,
                "root_cause": request.root_cause,
                "remediation": request.remediation,
                "auto_fixable": request.auto_fixable,
                "pattern_id": request.pattern_id
            }
        )
        return issue.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/issues/{issue_id}")
async def update_issue(issue_id: str, request: IssueUpdateRequest):
    """Update issue fields."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")
    
    try:
        from src.issues import IssueStatus, Severity
        
        status = IssueStatus(request.status) if request.status else None
        severity = Severity(request.severity) if request.severity else None
        
        issue = manager.update_issue(
            issue_id=issue_id,
            status=status,
            severity=severity,
            root_cause=request.root_cause,
            remediation=request.remediation
        )
        
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        return issue.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/issues/{issue_id}/fix")
async def fix_issue(issue_id: str):
    """Trigger auto-fix for an issue."""
    manager = get_issue_manager()
    executor = get_runbook_executor()
    
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")
    
    issue = manager.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    if not issue.auto_fixable:
        raise HTTPException(status_code=400, detail="Issue is not auto-fixable")
    
    # Find and execute runbook
    if executor:
        try:
            # Try to find runbook for this issue's type
            pattern_id = issue.metadata.get("pattern_id") or issue.type.value if hasattr(issue.type, 'value') else str(issue.type)
            
            context = {
                "namespace": issue.namespace,
                "resource_type": issue.metadata.get("resource_type", "Pod"),
                "resource_name": issue.resource,
                "container_name": "main",
            }
            
            execution = executor.execute_for_pattern(pattern_id, context, issue_id=issue_id)
            
            if execution:
                # Record fix attempt
                manager.record_fix_attempt(
                    issue_id=issue_id,
                    action=execution.runbook_id,
                    result=f"Execution {execution.execution_id}: {execution.status.value}",
                    success=execution.status.value == "success",
                )
                
                return {
                    "status": "initiated",
                    "execution_id": execution.execution_id,
                    "runbook_id": execution.runbook_id,
                }
            else:
                return {"status": "no_runbook", "message": "No runbook found for this issue"}
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    return {"status": "no_executor", "message": "Runbook executor not available"}


# =============================================================================
# Health Check API
# =============================================================================

def get_health_scheduler():
    """Get or create health scheduler."""
    global _health_scheduler
    if not HEALTH_AVAILABLE:
        return None
    if _health_scheduler is None:
        config = HealthCheckConfig(
            enabled=False,  # Don't auto-start
            interval_seconds=60,
        )
        _health_scheduler = HealthCheckScheduler(config=config)
    return _health_scheduler


@app.get("/api/health/check")
async def run_health_check(namespace: Optional[str] = None):
    """Run health check now."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available"}
    
    try:
        result = scheduler.run_now()
        return result.to_dict()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health/status")
async def get_health_status():
    """Get health check scheduler status."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available"}
    
    return scheduler.get_status()


@app.get("/api/health/history")
async def get_health_history(limit: int = 10):
    """Get health check history."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available", "history": []}
    
    return {"history": scheduler.get_history(limit=limit)}


# =============================================================================
# Runbook API
# =============================================================================

@app.get("/api/runbooks")
async def list_runbooks():
    """List available runbooks."""
    executor = get_runbook_executor()
    if not executor:
        return {"error": "Runbook Executor not available", "runbooks": []}
    
    return {"runbooks": executor.loader.list_runbooks()}


@app.get("/api/runbooks/executions")
async def list_runbook_executions(limit: int = 10):
    """List recent runbook executions."""
    executor = get_runbook_executor()
    if not executor:
        return {"error": "Runbook Executor not available", "executions": []}
    
    return {"executions": executor.list_executions(limit=limit)}


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
