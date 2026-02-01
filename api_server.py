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
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
