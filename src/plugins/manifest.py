# Plugin Manifest Configuration System
"""
YAML-based plugin configuration for declarative plugin management.
"""

import os
import yaml
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    """Plugin manifest structure"""
    name: str
    type: str
    version: str = "1.0.0"
    description: str = ""
    icon: str = "🔌"
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    
    # Optional fields
    author: str = ""
    homepage: str = ""
    dependencies: List[str] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PluginManifest':
        """Create manifest from dictionary"""
        return cls(
            name=data.get('name', 'Unknown'),
            type=data.get('type', 'unknown'),
            version=data.get('version', '1.0.0'),
            description=data.get('description', ''),
            icon=data.get('icon', '🔌'),
            enabled=data.get('enabled', True),
            config=data.get('config', {}),
            author=data.get('author', ''),
            homepage=data.get('homepage', ''),
            dependencies=data.get('dependencies', []),
        )
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'name': self.name,
            'type': self.type,
            'version': self.version,
            'description': self.description,
            'icon': self.icon,
            'enabled': self.enabled,
            'config': self.config,
            'author': self.author,
            'homepage': self.homepage,
            'dependencies': self.dependencies,
        }


class ManifestLoader:
    """Load and manage plugin manifests"""
    
    def __init__(self, config_dir: str = None):
        self.config_dir = Path(config_dir or os.path.join(
            os.path.dirname(__file__), '..', '..', 'config', 'plugins'
        ))
        self.manifests: Dict[str, PluginManifest] = {}
    
    def load_all(self) -> List[PluginManifest]:
        """Load all plugin manifests from config directory"""
        self.manifests = {}
        
        if not self.config_dir.exists():
            logger.warning(f"Plugin config directory not found: {self.config_dir}")
            return []
        
        for yaml_file in self.config_dir.glob('*.yaml'):
            try:
                manifest = self.load_file(yaml_file)
                if manifest:
                    self.manifests[manifest.name] = manifest
                    logger.info(f"Loaded manifest: {manifest.name}")
            except Exception as e:
                logger.error(f"Failed to load {yaml_file}: {e}")
        
        return list(self.manifests.values())
    
    def load_file(self, file_path: Path) -> Optional[PluginManifest]:
        """Load a single manifest file"""
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        
        if not data:
            return None
        
        return PluginManifest.from_dict(data)
    
    def save_manifest(self, manifest: PluginManifest, filename: str = None) -> bool:
        """Save a manifest to file"""
        if not filename:
            filename = f"{manifest.type}-{manifest.name.lower().replace(' ', '-')}.yaml"
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.config_dir / filename
        
        try:
            with open(file_path, 'w') as f:
                yaml.dump(manifest.to_dict(), f, default_flow_style=False, allow_unicode=True)
            logger.info(f"Saved manifest: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")
            return False
    
    def get_manifest(self, name: str) -> Optional[PluginManifest]:
        """Get manifest by name"""
        return self.manifests.get(name)
    
    def get_enabled_manifests(self) -> List[PluginManifest]:
        """Get all enabled manifests"""
        return [m for m in self.manifests.values() if m.enabled]


def create_default_manifests(config_dir: str = None):
    """Create default plugin manifests"""
    loader = ManifestLoader(config_dir)
    
    defaults = [
        PluginManifest(
            name="EKS Default",
            type="eks",
            version="1.0.0",
            description="Amazon EKS multi-cluster management",
            icon="☸️",
            enabled=True,
            config={
                "regions": ["ap-southeast-1"],
                "auto_discover": True,
            }
        ),
        PluginManifest(
            name="EC2 Monitor",
            type="ec2",
            version="1.0.0",
            description="Amazon EC2 instance monitoring",
            icon="🖥️",
            enabled=True,
            config={
                "regions": ["ap-southeast-1"],
                "include_stopped": True,
            }
        ),
        PluginManifest(
            name="Lambda Functions",
            type="lambda",
            version="1.0.0",
            description="AWS Lambda function management",
            icon="λ",
            enabled=False,
            config={
                "regions": ["ap-southeast-1"],
            }
        ),
        PluginManifest(
            name="HPC Clusters",
            type="hpc",
            version="1.0.0",
            description="AWS ParallelCluster HPC management",
            icon="🖧",
            enabled=False,
            config={
                "regions": ["ap-southeast-1"],
                "head_node_ssh": {},
            }
        ),
    ]
    
    for manifest in defaults:
        loader.save_manifest(manifest)
    
    return defaults


# Example YAML format
MANIFEST_EXAMPLE = """
# Plugin Manifest Example
# Save as: config/plugins/eks-production.yaml

name: EKS Production
type: eks
version: 1.0.0
description: Production EKS clusters
icon: ☸️
enabled: true

config:
  regions:
    - us-east-1
    - eu-west-1
  auto_discover: true
  default_namespace: default

author: DevOps Team
homepage: https://github.com/example/agentic-aiops
dependencies: []
"""
