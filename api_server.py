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
    ui_action: Optional[dict] = None  # A2UI action if applicable

# A2UI Widget Request/Response
class A2UIWidgetConfig(BaseModel):
    id: Optional[str] = None
    type: str
    config: dict
    span: Optional[int] = 8

class A2UIGenerateRequest(BaseModel):
    prompt: str
    
class A2UIGenerateResponse(BaseModel):
    success: bool
    widget: Optional[A2UIWidgetConfig] = None
    message: str


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
        
        # Check for A2UI intent (add/create widget requests)
        ui_action = detect_ui_action(request.message)
        
        return ChatResponse(
            response=response_text,
            intent=analysis['intent'],
            confidence=analysis['confidence'],
            ui_action=ui_action
        )
    except Exception as e:
        import traceback
        return ChatResponse(response=f"Error: {str(e)}\n{traceback.format_exc()}")


def detect_ui_action(message: str) -> Optional[dict]:
    """Detect if the message is requesting a UI action (A2UI)."""
    message_lower = message.lower()
    
    # Widget creation patterns
    add_patterns = ['添加', 'add', '创建', 'create', '显示', 'show', '生成', 'generate']
    widget_types = {
        'ec2': 'stat-card',
        'lambda': 'table',
        'cpu': 'stat-card',
        'memory': 'stat-card',
        'alert': 'alert-list',
        '告警': 'alert-list',
        'service': 'service-status',
        '服务': 'service-status',
        'table': 'table',
        '表格': 'table',
        'card': 'stat-card',
        '卡片': 'stat-card',
    }
    
    # Check if this is an add/create request
    is_add_request = any(pattern in message_lower for pattern in add_patterns)
    
    if not is_add_request:
        return None
    
    # Detect widget type
    detected_type = None
    detected_title = "New Widget"
    
    for keyword, wtype in widget_types.items():
        if keyword in message_lower:
            detected_type = wtype
            detected_title = f"{keyword.upper()} Monitor"
            break
    
    if detected_type:
        return {
            "action": "add_widget",
            "widget": {
                "type": detected_type,
                "config": {
                    "title": detected_title,
                    "value": 0 if detected_type == 'stat-card' else None,
                    "icon": "cloud",
                    "color": "#06AC38"
                },
                "span": 24 if detected_type == 'table' else 8
            }
        }
    
    return None


# =============================================================================
# A2UI Endpoints (Agent-to-UI)
# =============================================================================

@app.post("/api/a2ui/generate", response_model=A2UIGenerateResponse)
async def a2ui_generate(request: A2UIGenerateRequest):
    """Generate a UI widget configuration from natural language prompt."""
    try:
        ui_action = detect_ui_action(request.prompt)
        
        if ui_action and ui_action.get("widget"):
            widget = ui_action["widget"]
            widget["id"] = f"widget-{int(datetime.now().timestamp() * 1000)}"
            
            return A2UIGenerateResponse(
                success=True,
                widget=A2UIWidgetConfig(**widget),
                message=f"Created {widget['type']} widget: {widget['config'].get('title', 'Untitled')}"
            )
        else:
            return A2UIGenerateResponse(
                success=False,
                widget=None,
                message="Could not understand the widget request. Try: 'Add an EC2 monitoring card' or 'Create a Lambda table'"
            )
    except Exception as e:
        return A2UIGenerateResponse(
            success=False,
            widget=None,
            message=f"Error: {str(e)}"
        )


@app.get("/api/a2ui/widget-types")
async def a2ui_widget_types():
    """Get available widget types for A2UI."""
    return {
        "types": [
            {"key": "stat-card", "name": "Stat Card", "description": "KPI/metric display", "icon": "📊"},
            {"key": "table", "name": "Table", "description": "Data table with columns", "icon": "📋"},
            {"key": "alert-list", "name": "Alert List", "description": "List of alerts/issues", "icon": "⚠️"},
            {"key": "service-status", "name": "Service Status", "description": "Service health indicators", "icon": "🟢"},
            {"key": "progress-bar", "name": "Progress Bar", "description": "Progress/utilization meter", "icon": "📈"},
            {"key": "resource-list", "name": "Resource List", "description": "Cloud resource listing", "icon": "☁️"},
        ]
    }


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
# AWS Resource APIs (with mock fallback)
# =============================================================================

def get_aws_client(service_name: str):
    """Get AWS client, returns None if not configured."""
    try:
        import boto3
        return boto3.client(service_name)
    except Exception:
        return None


@app.get("/api/aws/ec2")
async def list_ec2_instances():
    """List EC2 instances."""
    client = get_aws_client('ec2')
    
    if client:
        try:
            response = client.describe_instances()
            instances = []
            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    name = next((t['Value'] for t in instance.get('Tags', []) if t['Key'] == 'Name'), 'Unnamed')
                    instances.append({
                        'id': instance['InstanceId'],
                        'name': name,
                        'type': instance['InstanceType'],
                        'state': instance['State']['Name'],
                        'az': instance.get('Placement', {}).get('AvailabilityZone', 'N/A'),
                        'cpu': 0,  # Would need CloudWatch for real metrics
                    })
            running = sum(1 for i in instances if i['state'] == 'running')
            stopped = sum(1 for i in instances if i['state'] == 'stopped')
            return {
                'instances': instances,
                'stats': {'total': len(instances), 'running': running, 'stopped': stopped}
            }
        except Exception as e:
            pass  # Fall through to mock data
    
    # Mock data for demo
    return {
        'instances': [
            {'id': 'i-0abc123def456', 'name': 'web-server-1', 'type': 't3.medium', 'state': 'running', 'az': 'us-east-1a', 'cpu': 45},
            {'id': 'i-0def456abc789', 'name': 'api-server-1', 'type': 't3.large', 'state': 'running', 'az': 'us-east-1b', 'cpu': 62},
            {'id': 'i-0ghi789jkl012', 'name': 'db-server-1', 'type': 'r5.xlarge', 'state': 'running', 'az': 'us-east-1a', 'cpu': 78},
            {'id': 'i-0mno345pqr678', 'name': 'worker-1', 'type': 't3.small', 'state': 'stopped', 'az': 'us-east-1c', 'cpu': 0},
            {'id': 'i-0stu901vwx234', 'name': 'batch-processor', 'type': 'm5.large', 'state': 'running', 'az': 'us-east-1b', 'cpu': 33},
        ],
        'stats': {'total': 5, 'running': 4, 'stopped': 1}
    }


@app.get("/api/aws/lambda")
async def list_lambda_functions():
    """List Lambda functions."""
    client = get_aws_client('lambda')
    
    if client:
        try:
            response = client.list_functions()
            functions = []
            for fn in response.get('Functions', []):
                functions.append({
                    'name': fn['FunctionName'],
                    'runtime': fn.get('Runtime', 'N/A'),
                    'memory': fn.get('MemorySize', 0),
                    'timeout': fn.get('Timeout', 0),
                    'invocations': 0,  # Would need CloudWatch
                })
            return {'functions': functions}
        except Exception:
            pass
    
    # Mock data
    return {
        'functions': [
            {'name': 'api-handler', 'runtime': 'python3.11', 'memory': 256, 'timeout': 30, 'invocations': 1250},
            {'name': 'image-processor', 'runtime': 'nodejs18.x', 'memory': 512, 'timeout': 60, 'invocations': 340},
            {'name': 'notification-sender', 'runtime': 'python3.11', 'memory': 128, 'timeout': 15, 'invocations': 890},
            {'name': 'data-transformer', 'runtime': 'python3.12', 'memory': 1024, 'timeout': 120, 'invocations': 456},
            {'name': 'auth-validator', 'runtime': 'nodejs20.x', 'memory': 256, 'timeout': 10, 'invocations': 2100},
        ]
    }


@app.get("/api/aws/s3")
async def list_s3_buckets():
    """List S3 buckets."""
    client = get_aws_client('s3')
    
    if client:
        try:
            response = client.list_buckets()
            buckets = []
            for bucket in response.get('Buckets', []):
                buckets.append({
                    'name': bucket['Name'],
                    'region': 'us-east-1',  # Would need additional call
                    'objects': 0,
                    'size': 'N/A',
                    'public': False,
                })
            return {'buckets': buckets}
        except Exception:
            pass
    
    # Mock data
    return {
        'buckets': [
            {'name': 'prod-assets-bucket', 'region': 'us-east-1', 'objects': 12450, 'size': '45.2 GB', 'public': False},
            {'name': 'logs-archive-bucket', 'region': 'us-east-1', 'objects': 89230, 'size': '128.5 GB', 'public': False},
            {'name': 'static-website-bucket', 'region': 'us-east-1', 'objects': 234, 'size': '1.2 GB', 'public': True},
            {'name': 'backup-daily-bucket', 'region': 'us-west-2', 'objects': 567, 'size': '89.7 GB', 'public': False},
        ]
    }


@app.get("/api/aws/rds")
async def list_rds_instances():
    """List RDS database instances."""
    client = get_aws_client('rds')
    
    if client:
        try:
            response = client.describe_db_instances()
            instances = []
            for db in response.get('DBInstances', []):
                instances.append({
                    'id': db['DBInstanceIdentifier'],
                    'engine': db['Engine'],
                    'status': db['DBInstanceStatus'],
                    'class': db['DBInstanceClass'],
                    'storage': db.get('AllocatedStorage', 0),
                })
            return {'instances': instances}
        except Exception:
            pass
    
    # Mock data
    return {
        'instances': [
            {'id': 'prod-mysql-primary', 'engine': 'mysql', 'status': 'available', 'class': 'db.r5.large', 'storage': 500},
            {'id': 'prod-postgres-main', 'engine': 'postgres', 'status': 'available', 'class': 'db.r5.xlarge', 'storage': 1000},
            {'id': 'analytics-redshift', 'engine': 'redshift', 'status': 'available', 'class': 'dc2.large', 'storage': 2000},
        ]
    }


@app.get("/api/aws/scan")
async def scan_aws_resources():
    """Scan all AWS resources and return summary with potential issues."""
    ec2_data = await list_ec2_instances()
    lambda_data = await list_lambda_functions()
    s3_data = await list_s3_buckets()
    rds_data = await list_rds_instances()
    
    # Detect potential issues
    issues = []
    
    # Check EC2 - high CPU
    for instance in ec2_data.get('instances', []):
        if instance.get('cpu', 0) > 70:
            issues.append({
                'resource': f"EC2: {instance['name']}",
                'severity': 'high' if instance['cpu'] > 85 else 'medium',
                'issue': f"High CPU utilization: {instance['cpu']}%",
                'recommendation': 'Consider scaling up or investigating workload'
            })
    
    # Check S3 - public buckets
    for bucket in s3_data.get('buckets', []):
        if bucket.get('public'):
            issues.append({
                'resource': f"S3: {bucket['name']}",
                'severity': 'high',
                'issue': 'Bucket has public access enabled',
                'recommendation': 'Review bucket policy and disable public access if not needed'
            })
    
    return {
        'summary': {
            'ec2': {'count': len(ec2_data.get('instances', [])), 'running': ec2_data.get('stats', {}).get('running', 0)},
            'lambda': {'count': len(lambda_data.get('functions', []))},
            's3': {'count': len(s3_data.get('buckets', []))},
            'rds': {'count': len(rds_data.get('instances', []))},
        },
        'issues': issues,
        'scanned_at': datetime.now().isoformat()
    }


# =============================================================================
# Proactive Agent System (OpenClaw-inspired)
# =============================================================================

from src.proactive_agent import get_proactive_system, ProactiveResult

# Initialize proactive system
proactive_system = get_proactive_system()

@app.on_event("startup")
async def startup_proactive_system():
    """Start proactive agent system on server startup."""
    await proactive_system.start()
    print("🚀 Proactive Agent System started")

@app.on_event("shutdown")
async def shutdown_proactive_system():
    """Stop proactive agent system on server shutdown."""
    await proactive_system.stop()
    print("🛑 Proactive Agent System stopped")

@app.get("/api/proactive/status")
async def get_proactive_status():
    """Get proactive system status."""
    return proactive_system.get_status()

class ProactiveToggleRequest(BaseModel):
    task_name: str
    enabled: bool

@app.post("/api/proactive/toggle")
async def toggle_proactive_task(request: ProactiveToggleRequest):
    """Enable or disable a proactive task."""
    proactive_system.enable_task(request.task_name, request.enabled)
    return {"status": "ok", "task": request.task_name, "enabled": request.enabled}

class ProactiveIntervalRequest(BaseModel):
    task_name: str
    interval_seconds: int

@app.post("/api/proactive/interval")
async def update_proactive_interval(request: ProactiveIntervalRequest):
    """Update proactive task interval."""
    proactive_system.update_task_interval(request.task_name, request.interval_seconds)
    return {"status": "ok", "task": request.task_name, "interval": request.interval_seconds}

class EventTriggerRequest(BaseModel):
    event_type: str
    event_data: dict = {}

@app.post("/api/proactive/trigger")
async def trigger_proactive_event(request: EventTriggerRequest):
    """Trigger an event-driven proactive task (e.g., CloudWatch alert)."""
    result = await proactive_system.trigger_event(request.event_type, request.event_data)
    return {
        "task_name": result.task_name,
        "status": result.status,
        "summary": result.summary,
        "findings": result.findings,
        "timestamp": result.timestamp.isoformat()
    }

@app.get("/api/proactive/results")
async def get_proactive_results():
    """Get pending proactive results (alerts)."""
    results = []
    while not proactive_system.results_queue.empty():
        try:
            result: ProactiveResult = proactive_system.results_queue.get_nowait()
            results.append({
                "task_name": result.task_name,
                "status": result.status,
                "summary": result.summary,
                "findings": result.findings,
                "timestamp": result.timestamp.isoformat()
            })
        except:
            break
    return {"results": results, "count": len(results)}


# =============================================================================
# S3 Knowledge Base (Pattern Storage + RCA)
# =============================================================================

from src.s3_knowledge_base import get_knowledge_base, AnomalyPattern

@app.get("/api/kb/stats")
async def get_kb_stats():
    """Get knowledge base statistics."""
    kb = await get_knowledge_base()
    return kb.get_stats()

@app.get("/api/kb/patterns")
async def list_patterns(
    resource_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50
):
    """List patterns in the knowledge base."""
    kb = await get_knowledge_base()
    patterns = await kb.search_patterns(
        resource_type=resource_type,
        severity=severity,
        limit=limit
    )
    return {
        "patterns": [p.to_dict() for p in patterns],
        "count": len(patterns)
    }

@app.get("/api/kb/patterns/{pattern_id}")
async def get_pattern(pattern_id: str):
    """Get a specific pattern by ID."""
    kb = await get_knowledge_base()
    pattern = await kb.get_pattern(pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return pattern.to_dict()

class PatternAddRequest(BaseModel):
    title: str
    description: str
    resource_type: str
    severity: str = "medium"
    symptoms: List[str] = []
    root_cause: str = ""
    remediation: str = ""
    tags: List[str] = []
    quality_score: float = 0.8

@app.post("/api/kb/patterns")
async def add_pattern(request: PatternAddRequest):
    """Add a new pattern to the knowledge base."""
    kb = await get_knowledge_base()
    pattern = AnomalyPattern(
        pattern_id="",  # Will be generated
        title=request.title,
        description=request.description,
        resource_type=request.resource_type,
        severity=request.severity,
        symptoms=request.symptoms,
        root_cause=request.root_cause,
        remediation=request.remediation,
        tags=request.tags,
    )
    success = await kb.add_pattern(pattern, quality_score=request.quality_score)
    if not success:
        raise HTTPException(status_code=400, detail="Pattern rejected: quality score too low (< 0.7)")
    return {"status": "ok", "pattern_id": pattern.pattern_id}

class RCARequest(BaseModel):
    id: str = ""
    title: str
    description: str = ""
    resource_type: str

@app.post("/api/kb/rca")
async def perform_rca(request: RCARequest):
    """Perform Root Cause Analysis using pattern matching."""
    kb = await get_knowledge_base()
    issue = {
        "id": request.id or "unknown",
        "title": request.title,
        "description": request.description,
        "resource_type": request.resource_type,
    }
    result = await kb.match_pattern(issue)
    return {
        "issue_id": result.issue_id,
        "matched_pattern": result.matched_pattern.to_dict() if result.matched_pattern else None,
        "confidence": result.confidence,
        "analysis": result.analysis,
        "recommendations": result.recommendations,
        "timestamp": result.timestamp
    }


# =============================================================================
# AWS Cloud Scanner (Full Resource Discovery)
# =============================================================================

from src.aws_scanner import get_scanner, AWSCloudScanner

# Current scanner state
_current_region = "ap-southeast-1"
_monitored_resources: List[Dict[str, Any]] = []

@app.get("/api/scanner/account")
async def get_account_info():
    """Get current AWS account information."""
    scanner = get_scanner(_current_region)
    return scanner.get_account_info()

@app.get("/api/scanner/regions")
async def list_regions():
    """List available AWS regions."""
    scanner = get_scanner(_current_region)
    regions = scanner.list_regions()
    # Add common regions at top
    common = ["ap-southeast-1", "us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1"]
    return {
        "current": _current_region,
        "common": common,
        "all": regions,
    }

class SetRegionRequest(BaseModel):
    region: str

@app.post("/api/scanner/region")
async def set_region(request: SetRegionRequest):
    """Set the current region for scanning."""
    global _current_region
    _current_region = request.region
    return {"status": "ok", "region": _current_region}

@app.get("/api/scanner/scan")
async def scan_all_resources(region: Optional[str] = None):
    """Perform full cloud scan of all AWS resources."""
    scan_region = region or _current_region
    scanner = get_scanner(scan_region)
    return scanner.scan_all_resources()

@app.get("/api/scanner/service/{service}")
async def scan_service(service: str, region: Optional[str] = None):
    """Scan a specific AWS service."""
    scan_region = region or _current_region
    scanner = get_scanner(scan_region)
    
    service_scanners = {
        "ec2": scanner._scan_ec2,
        "lambda": scanner._scan_lambda,
        "s3": scanner._scan_s3,
        "rds": scanner._scan_rds,
        "iam": scanner._scan_iam,
        "eks": scanner._scan_eks,
        "cloudwatch": scanner._scan_cloudwatch_alarms,
    }
    
    if service not in service_scanners:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")
    
    return {
        "service": service,
        "region": scan_region,
        "data": service_scanners[service](),
    }

# Monitoring endpoints

class MonitorResourceRequest(BaseModel):
    resource_id: str
    resource_type: str
    name: str = ""
    service: str

@app.post("/api/scanner/monitor")
async def add_to_monitoring(request: MonitorResourceRequest):
    """Add a resource to the monitoring list."""
    global _monitored_resources
    
    # Check if already monitored
    for r in _monitored_resources:
        if r["resource_id"] == request.resource_id:
            return {"status": "already_monitored", "resource_id": request.resource_id}
    
    _monitored_resources.append({
        "resource_id": request.resource_id,
        "resource_type": request.resource_type,
        "name": request.name,
        "service": request.service,
        "added_at": datetime.now().isoformat(),
    })
    
    return {"status": "ok", "resource_id": request.resource_id, "total_monitored": len(_monitored_resources)}

@app.delete("/api/scanner/monitor/{resource_id}")
async def remove_from_monitoring(resource_id: str):
    """Remove a resource from monitoring."""
    global _monitored_resources
    _monitored_resources = [r for r in _monitored_resources if r["resource_id"] != resource_id]
    return {"status": "ok", "resource_id": resource_id, "total_monitored": len(_monitored_resources)}

@app.get("/api/scanner/monitored")
async def list_monitored_resources():
    """List all monitored resources."""
    return {"resources": _monitored_resources, "count": len(_monitored_resources)}

# CloudWatch Metrics/Logs endpoints

@app.get("/api/cloudwatch/metrics/ec2/{instance_id}")
async def get_ec2_metrics(instance_id: str, metric: str = "CPUUtilization", hours: int = 1):
    """Get CloudWatch metrics for an EC2 instance."""
    scanner = get_scanner(_current_region)
    return scanner.get_ec2_metrics(instance_id, metric, hours)

@app.get("/api/cloudwatch/metrics/rds/{db_id}")
async def get_rds_metrics(db_id: str, metric: str = "CPUUtilization", hours: int = 1):
    """Get CloudWatch metrics for an RDS instance."""
    scanner = get_scanner(_current_region)
    return scanner.get_rds_metrics(db_id, metric, hours)

@app.get("/api/cloudwatch/metrics/lambda/{function_name}")
async def get_lambda_metrics(function_name: str, metric: str = "Duration", hours: int = 1):
    """Get CloudWatch metrics for a Lambda function."""
    scanner = get_scanner(_current_region)
    return scanner.get_lambda_metrics(function_name, metric, hours)

class CloudWatchLogsRequest(BaseModel):
    log_group: str
    filter_pattern: str = ""
    limit: int = 100
    hours: int = 1

@app.post("/api/cloudwatch/logs")
async def get_cloudwatch_logs(request: CloudWatchLogsRequest):
    """Get CloudWatch logs."""
    scanner = get_scanner(_current_region)
    return scanner.get_cloudwatch_logs(
        request.log_group,
        request.filter_pattern,
        request.limit,
        request.hours,
    )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
