# AgenticAIOps Plugin System
"""
Plugin architecture for multi-service support.
Each plugin provides tools and capabilities for a specific service type.
"""

from .base import PluginBase, PluginRegistry, PluginConfig, ClusterConfig, PluginStatus
from .eks_plugin import EKSPlugin
from .ec2_plugin import EC2Plugin
from .lambda_plugin import LambdaPlugin
from .hpc_plugin import HPCPlugin

__all__ = [
    'PluginBase',
    'PluginRegistry', 
    'PluginConfig',
    'ClusterConfig',
    'PluginStatus',
    'EKSPlugin',
    'EC2Plugin',
    'LambdaPlugin',
    'HPCPlugin',
]
