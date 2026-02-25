"""Router: /api/plugins - Plugin management."""

import uuid

from fastapi import APIRouter, HTTPException

from routers.schemas import PluginCreateRequest
from routers.deps import PluginRegistry

router = APIRouter(tags=["plugins"])


@router.get("/api/plugins")
async def list_plugins():
    """List all registered plugins."""
    return {
        "plugins": [p.get_info() for p in PluginRegistry.get_all_plugins()],
        "available_types": PluginRegistry.get_available_plugins()
    }


@router.post("/api/plugins")
async def create_plugin(request: PluginCreateRequest):
    """Create and register a new plugin."""
    from src.plugins import PluginConfig

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


@router.delete("/api/plugins/{plugin_id}")
async def remove_plugin(plugin_id: str):
    """Remove a plugin."""
    if PluginRegistry.remove_plugin(plugin_id):
        return {"status": "removed", "plugin_id": plugin_id}
    raise HTTPException(status_code=404, detail="Plugin not found")


@router.post("/api/plugins/{plugin_id}/enable")
async def enable_plugin(plugin_id: str):
    """Enable a plugin."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        plugin.enable()
        return {"status": "enabled", "plugin": plugin.get_info()}
    raise HTTPException(status_code=404, detail="Plugin not found")


@router.post("/api/plugins/{plugin_id}/disable")
async def disable_plugin(plugin_id: str):
    """Disable a plugin."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        plugin.disable()
        return {"status": "disabled", "plugin": plugin.get_info()}
    raise HTTPException(status_code=404, detail="Plugin not found")


@router.get("/api/plugins/{plugin_id}/status")
async def plugin_status(plugin_id: str):
    """Get plugin status and summary."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        return plugin.get_status_summary()
    raise HTTPException(status_code=404, detail="Plugin not found")
