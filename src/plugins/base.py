"""
Plugin Base Classes and Registry
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PluginStatus(Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    ERROR = "error"


@dataclass
class PluginConfig:
    """Configuration for a plugin instance"""
    plugin_id: str
    plugin_type: str
    name: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "plugin_id": self.plugin_id,
            "plugin_type": self.plugin_type,
            "name": self.name,
            "enabled": self.enabled,
            "config": self.config
        }


@dataclass
class ClusterConfig:
    """Configuration for a cluster/resource"""
    cluster_id: str
    name: str
    region: str
    plugin_type: str
    config: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "cluster_id": self.cluster_id,
            "name": self.name,
            "region": self.region,
            "plugin_type": self.plugin_type,
            "config": self.config
        }


class PluginBase(ABC):
    """Base class for all plugins"""
    
    PLUGIN_TYPE: str = "base"
    PLUGIN_NAME: str = "Base Plugin"
    PLUGIN_DESCRIPTION: str = "Base plugin class"
    PLUGIN_ICON: str = "🔌"
    
    def __init__(self, config: PluginConfig):
        self.config = config
        self.status = PluginStatus.DISABLED
        self._tools: List[Callable] = []
        
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the plugin. Return True if successful."""
        pass
    
    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Check plugin health and connectivity."""
        pass
    
    @abstractmethod
    def get_tools(self) -> List[Callable]:
        """Return list of tools provided by this plugin."""
        pass
    
    @abstractmethod
    def get_resources(self) -> List[Dict[str, Any]]:
        """Get list of managed resources (clusters, instances, etc.)"""
        pass
    
    @abstractmethod
    def get_status_summary(self) -> Dict[str, Any]:
        """Get status summary for dashboard display."""
        pass
    
    def enable(self) -> bool:
        """Enable the plugin"""
        try:
            if self.initialize():
                self.status = PluginStatus.ENABLED
                logger.info(f"Plugin {self.config.name} enabled")
                return True
        except Exception as e:
            logger.error(f"Failed to enable plugin {self.config.name}: {e}")
            self.status = PluginStatus.ERROR
        return False
    
    def disable(self) -> bool:
        """Disable the plugin"""
        self.status = PluginStatus.DISABLED
        logger.info(f"Plugin {self.config.name} disabled")
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """Get plugin info for UI display"""
        return {
            "plugin_id": self.config.plugin_id,
            "plugin_type": self.PLUGIN_TYPE,
            "name": self.config.name,
            "description": self.PLUGIN_DESCRIPTION,
            "icon": self.PLUGIN_ICON,
            "status": self.status.value,
            "enabled": self.config.enabled,
            "config": self.config.config,
            "tools_count": len(self.get_tools()),
        }


class PluginRegistry:
    """Registry for managing plugins"""
    
    _instance = None
    _plugin_classes: Dict[str, type] = {}
    _plugins: Dict[str, PluginBase] = {}
    _clusters: Dict[str, ClusterConfig] = {}
    _active_cluster: Optional[str] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def register_plugin_class(cls, plugin_class: type):
        """Register a plugin class"""
        cls._plugin_classes[plugin_class.PLUGIN_TYPE] = plugin_class
        logger.info(f"Registered plugin class: {plugin_class.PLUGIN_TYPE}")
    
    @classmethod
    def get_available_plugins(cls) -> List[Dict[str, Any]]:
        """Get list of available plugin types"""
        return [
            {
                "type": pt,
                "name": pc.PLUGIN_NAME,
                "description": pc.PLUGIN_DESCRIPTION,
                "icon": pc.PLUGIN_ICON,
            }
            for pt, pc in cls._plugin_classes.items()
        ]
    
    @classmethod
    def create_plugin(cls, config: PluginConfig) -> Optional[PluginBase]:
        """Create a plugin instance"""
        plugin_class = cls._plugin_classes.get(config.plugin_type)
        if not plugin_class:
            logger.error(f"Unknown plugin type: {config.plugin_type}")
            return None
        
        plugin = plugin_class(config)
        cls._plugins[config.plugin_id] = plugin
        
        if config.enabled:
            plugin.enable()
        
        return plugin
    
    @classmethod
    def get_plugin(cls, plugin_id: str) -> Optional[PluginBase]:
        """Get a plugin by ID"""
        return cls._plugins.get(plugin_id)
    
    @classmethod
    def get_all_plugins(cls) -> List[PluginBase]:
        """Get all registered plugins"""
        return list(cls._plugins.values())
    
    @classmethod
    def get_enabled_plugins(cls) -> List[PluginBase]:
        """Get all enabled plugins"""
        return [p for p in cls._plugins.values() if p.status == PluginStatus.ENABLED]
    
    @classmethod
    def remove_plugin(cls, plugin_id: str) -> bool:
        """Remove a plugin"""
        if plugin_id in cls._plugins:
            cls._plugins[plugin_id].disable()
            del cls._plugins[plugin_id]
            return True
        return False
    
    # Cluster management
    @classmethod
    def add_cluster(cls, cluster: ClusterConfig):
        """Add a cluster configuration"""
        cls._clusters[cluster.cluster_id] = cluster
        logger.info(f"Added cluster: {cluster.name} ({cluster.cluster_id})")
    
    @classmethod
    def get_cluster(cls, cluster_id: str) -> Optional[ClusterConfig]:
        """Get cluster by ID"""
        return cls._clusters.get(cluster_id)
    
    @classmethod
    def get_all_clusters(cls) -> List[ClusterConfig]:
        """Get all clusters"""
        return list(cls._clusters.values())
    
    @classmethod
    def get_clusters_by_type(cls, plugin_type: str) -> List[ClusterConfig]:
        """Get clusters by plugin type"""
        return [c for c in cls._clusters.values() if c.plugin_type == plugin_type]
    
    @classmethod
    def set_active_cluster(cls, cluster_id: str) -> bool:
        """Set the active cluster"""
        if cluster_id in cls._clusters:
            cls._active_cluster = cluster_id
            logger.info(f"Active cluster set to: {cluster_id}")
            return True
        return False
    
    @classmethod
    def get_active_cluster(cls) -> Optional[ClusterConfig]:
        """Get the active cluster"""
        if cls._active_cluster:
            return cls._clusters.get(cls._active_cluster)
        return None
    
    @classmethod
    def get_all_tools(cls) -> List[Callable]:
        """Get tools from all enabled plugins"""
        tools = []
        for plugin in cls.get_enabled_plugins():
            tools.extend(plugin.get_tools())
        return tools
    
    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Get overall registry status"""
        return {
            "available_plugin_types": len(cls._plugin_classes),
            "registered_plugins": len(cls._plugins),
            "enabled_plugins": len(cls.get_enabled_plugins()),
            "clusters": len(cls._clusters),
            "active_cluster": cls._active_cluster,
            "plugins": [p.get_info() for p in cls._plugins.values()],
            "cluster_list": [c.to_dict() for c in cls._clusters.values()],
        }
