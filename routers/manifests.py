"""Router: /api/manifests - Plugin manifest management."""

import os

from fastapi import APIRouter, HTTPException

from routers.schemas import ManifestRequest
from routers.deps import PluginRegistry

router = APIRouter(tags=["manifests"])


@router.get("/api/manifests")
async def list_manifests():
    """List all plugin manifests."""
    from src.plugins.manifest import ManifestLoader

    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'plugins')
    loader = ManifestLoader(config_dir)
    manifests = loader.load_all()

    return {
        "manifests": [m.to_dict() for m in manifests],
        "config_dir": str(config_dir)
    }


@router.post("/api/manifests")
async def create_manifest(request: ManifestRequest):
    """Create a new plugin manifest."""
    from src.plugins.manifest import ManifestLoader, PluginManifest

    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'plugins')

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


@router.post("/api/manifests/reload")
async def reload_manifests():
    """Reload all plugins from manifests."""
    for plugin_id in list(PluginRegistry._plugins.keys()):
        PluginRegistry.remove_plugin(plugin_id)

    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'plugins')
    loaded = PluginRegistry.load_from_manifests(config_dir)

    clusters = PluginRegistry.get_all_clusters()
    if clusters:
        PluginRegistry.set_active_cluster(clusters[0].cluster_id)

    return {
        "status": "reloaded",
        "plugins_loaded": loaded,
        "registry": PluginRegistry.get_status()
    }
