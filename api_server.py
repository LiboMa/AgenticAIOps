#!/usr/bin/env python3
"""
AgenticAIOps - Backend API Server

FastAPI server providing REST endpoints for the React dashboard.
Routers live in routers/ — this file handles app init, middleware, and lifecycle.
"""

import os
import sys
import signal
import atexit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ---------------------------------------------------------------------------
# PID lockfile — prevents multiple instances binding the same port
# ---------------------------------------------------------------------------
PID_FILE = "/tmp/aiops-api.pid"


def _acquire_pid_lock():
    """Acquire PID lockfile. Exit if another instance is running."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print(f"❌ Another API server is already running (PID {old_pid}). "
                  f"Remove {PID_FILE} if this is stale.")
            sys.exit(1)
        except (ValueError, ProcessLookupError, PermissionError):
            pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _release_pid_lock():
    """Remove PID lockfile on exit."""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE) as f:
                stored_pid = int(f.read().strip())
            if stored_pid == os.getpid():
                os.remove(PID_FILE)
    except Exception:
        pass


atexit.register(_release_pid_lock)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AgenticAIOps API",
    description="Backend API for EKS AIOps Dashboard",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register all routers
# ---------------------------------------------------------------------------
from routers.models import router as models_router
from routers.chat import router as chat_router
from routers.a2ui import router as a2ui_router
from routers.k8s import router as k8s_router
from routers.anomalies import router as anomalies_router
from routers.rca import router as rca_router
from routers.incident import router as incident_router
from routers.plugins import router as plugins_router
from routers.clusters import router as clusters_router
from routers.manifests import router as manifests_router
from routers.aci import router as aci_router
from routers.issues import router as issues_router
from routers.health import router as health_router
from routers.runbooks import router as runbooks_router
from routers.aws import router as aws_router
from routers.proactive import router as proactive_router
from routers.notifications import router as notifications_router
from routers.knowledge import router as knowledge_router
from src.aci.topology.api import router as topology_router

app.include_router(models_router)
app.include_router(chat_router)
app.include_router(a2ui_router)
app.include_router(k8s_router)
app.include_router(anomalies_router)
app.include_router(rca_router)
app.include_router(incident_router)
app.include_router(plugins_router)
app.include_router(clusters_router)
app.include_router(manifests_router)
app.include_router(aci_router)
app.include_router(issues_router)
app.include_router(health_router)
app.include_router(runbooks_router)
app.include_router(aws_router)
app.include_router(proactive_router)
app.include_router(notifications_router)
app.include_router(knowledge_router)
app.include_router(topology_router)

# ---------------------------------------------------------------------------
# Startup / shutdown events
# ---------------------------------------------------------------------------
from routers.deps import PluginRegistry, PluginConfig
from routers.proactive import proactive_system


@app.on_event("startup")
async def startup_event():
    """Initialize plugins from manifests on startup."""
    _acquire_pid_lock()
    try:
        config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
        loaded = PluginRegistry.load_from_manifests(config_dir)

        if loaded == 0:
            eks_config = PluginConfig(
                plugin_id="eks-default",
                plugin_type="eks",
                name="EKS Default",
                enabled=True,
                config={"regions": ["ap-southeast-1"]}
            )
            PluginRegistry.create_plugin(eks_config)

        clusters = PluginRegistry.get_clusters_by_type("eks")
        if clusters:
            PluginRegistry.set_active_cluster(clusters[0].cluster_id)

        print(f"Plugins initialized: {len(PluginRegistry.get_all_plugins())} plugins")
        print(f"Clusters discovered: {len(PluginRegistry.get_all_clusters())} clusters")
    except Exception as e:
        print(f"Warning: Failed to initialize plugins: {e}")

    # Start proactive agent system
    await proactive_system.start()
    print("🚀 Proactive Agent System started")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on shutdown."""
    await proactive_system.stop()
    _release_pid_lock()
    print("🛑 Proactive Agent System stopped")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _acquire_pid_lock()
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
