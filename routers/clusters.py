"""Router: /api/clusters, /api/registry - Cluster management."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from routers.schemas import ClusterAddRequest
from routers.deps import PluginRegistry

router = APIRouter(tags=["clusters"])


@router.get("/api/clusters")
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


@router.post("/api/clusters")
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


@router.post("/api/clusters/{cluster_id}/activate")
async def activate_cluster(cluster_id: str):
    """Set a cluster as active."""
    if PluginRegistry.set_active_cluster(cluster_id):
        cluster = PluginRegistry.get_cluster(cluster_id)
        return {"status": "activated", "cluster": cluster.to_dict()}
    raise HTTPException(status_code=404, detail="Cluster not found")


@router.get("/api/clusters/active")
async def get_active_cluster():
    """Get the currently active cluster."""
    cluster = PluginRegistry.get_active_cluster()
    if cluster:
        return cluster.to_dict()
    return None


@router.get("/api/registry/status")
async def registry_status():
    """Get overall plugin registry status."""
    return PluginRegistry.get_status()
