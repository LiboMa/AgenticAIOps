#!/usr/bin/env python3
"""
Plugin System Tests
Tests for the AgenticAIOps plugin architecture.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.plugins import PluginRegistry, PluginConfig, PluginStatus
from src.plugins.eks_plugin import EKSPlugin
from src.plugins.ec2_plugin import EC2Plugin
from src.plugins.lambda_plugin import LambdaPlugin
from src.plugins.hpc_plugin import HPCPlugin


class TestPluginRegistry:
    """Test cases for PluginRegistry"""
    
    def setup_method(self):
        """Reset registry before each test"""
        PluginRegistry._plugins = {}
        PluginRegistry._clusters = {}
        PluginRegistry._active_cluster = None
    
    def test_register_plugin_class(self):
        """Test plugin class registration"""
        # EKS should be pre-registered
        available = PluginRegistry.get_available_plugins()
        types = [p['type'] for p in available]
        
        assert 'eks' in types
        assert 'ec2' in types
        assert 'lambda' in types
        assert 'hpc' in types
    
    def test_create_plugin(self):
        """Test plugin creation"""
        config = PluginConfig(
            plugin_id="test-eks",
            plugin_type="eks",
            name="Test EKS Plugin",
            enabled=True,
            config={"regions": ["ap-southeast-1"]}
        )
        
        plugin = PluginRegistry.create_plugin(config)
        
        assert plugin is not None
        assert plugin.config.plugin_id == "test-eks"
        assert plugin.PLUGIN_TYPE == "eks"
    
    def test_get_plugin(self):
        """Test getting plugin by ID"""
        config = PluginConfig(
            plugin_id="test-get",
            plugin_type="ec2",
            name="Test EC2 Plugin",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        PluginRegistry.create_plugin(config)
        plugin = PluginRegistry.get_plugin("test-get")
        
        assert plugin is not None
        assert plugin.config.name == "Test EC2 Plugin"
    
    def test_remove_plugin(self):
        """Test plugin removal"""
        config = PluginConfig(
            plugin_id="test-remove",
            plugin_type="lambda",
            name="Test Lambda Plugin",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        PluginRegistry.create_plugin(config)
        assert PluginRegistry.get_plugin("test-remove") is not None
        
        result = PluginRegistry.remove_plugin("test-remove")
        assert result is True
        assert PluginRegistry.get_plugin("test-remove") is None
    
    def test_get_all_plugins(self):
        """Test getting all plugins"""
        config1 = PluginConfig(
            plugin_id="all-1",
            plugin_type="eks",
            name="EKS 1",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        config2 = PluginConfig(
            plugin_id="all-2",
            plugin_type="ec2",
            name="EC2 1",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        PluginRegistry.create_plugin(config1)
        PluginRegistry.create_plugin(config2)
        
        plugins = PluginRegistry.get_all_plugins()
        assert len(plugins) == 2
    
    def test_unknown_plugin_type(self):
        """Test creating plugin with unknown type"""
        config = PluginConfig(
            plugin_id="unknown",
            plugin_type="unknown_type",
            name="Unknown",
            enabled=True,
            config={}
        )
        
        plugin = PluginRegistry.create_plugin(config)
        assert plugin is None


class TestClusterManagement:
    """Test cases for cluster management"""
    
    def setup_method(self):
        """Reset registry before each test"""
        PluginRegistry._plugins = {}
        PluginRegistry._clusters = {}
        PluginRegistry._active_cluster = None
    
    def test_add_cluster(self):
        """Test adding a cluster"""
        from src.plugins.base import ClusterConfig
        
        cluster = ClusterConfig(
            cluster_id="test-cluster-1",
            name="Test Cluster",
            region="ap-southeast-1",
            plugin_type="eks",
            config={}
        )
        
        PluginRegistry.add_cluster(cluster)
        
        result = PluginRegistry.get_cluster("test-cluster-1")
        assert result is not None
        assert result.name == "Test Cluster"
    
    def test_set_active_cluster(self):
        """Test setting active cluster"""
        from src.plugins.base import ClusterConfig
        
        cluster = ClusterConfig(
            cluster_id="active-test",
            name="Active Test",
            region="us-east-1",
            plugin_type="eks",
            config={}
        )
        
        PluginRegistry.add_cluster(cluster)
        result = PluginRegistry.set_active_cluster("active-test")
        
        assert result is True
        
        active = PluginRegistry.get_active_cluster()
        assert active is not None
        assert active.cluster_id == "active-test"
    
    def test_get_clusters_by_type(self):
        """Test filtering clusters by type"""
        from src.plugins.base import ClusterConfig
        
        PluginRegistry.add_cluster(ClusterConfig(
            cluster_id="eks-1", name="EKS 1", region="ap-southeast-1",
            plugin_type="eks", config={}
        ))
        PluginRegistry.add_cluster(ClusterConfig(
            cluster_id="eks-2", name="EKS 2", region="us-east-1",
            plugin_type="eks", config={}
        ))
        PluginRegistry.add_cluster(ClusterConfig(
            cluster_id="ec2-1", name="EC2 1", region="ap-southeast-1",
            plugin_type="ec2", config={}
        ))
        
        eks_clusters = PluginRegistry.get_clusters_by_type("eks")
        assert len(eks_clusters) == 2
        
        ec2_clusters = PluginRegistry.get_clusters_by_type("ec2")
        assert len(ec2_clusters) == 1


class TestEKSPlugin:
    """Test cases for EKS Plugin"""
    
    def test_plugin_info(self):
        """Test EKS plugin info"""
        config = PluginConfig(
            plugin_id="eks-info-test",
            plugin_type="eks",
            name="EKS Info Test",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        plugin = EKSPlugin(config)
        info = plugin.get_info()
        
        assert info['plugin_type'] == 'eks'
        assert info['icon'] == '☸️'
        assert 'Kubernetes' in info['description']
    
    def test_get_tools(self):
        """Test EKS plugin returns tools"""
        config = PluginConfig(
            plugin_id="eks-tools-test",
            plugin_type="eks",
            name="EKS Tools Test",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        plugin = EKSPlugin(config)
        tools = plugin.get_tools()
        
        assert len(tools) > 0
        tool_names = [t.__name__ for t in tools]
        assert 'eks_get_pods' in tool_names
        assert 'eks_get_nodes' in tool_names


class TestEC2Plugin:
    """Test cases for EC2 Plugin"""
    
    def test_plugin_info(self):
        """Test EC2 plugin info"""
        config = PluginConfig(
            plugin_id="ec2-info-test",
            plugin_type="ec2",
            name="EC2 Info Test",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        plugin = EC2Plugin(config)
        info = plugin.get_info()
        
        assert info['plugin_type'] == 'ec2'
        assert info['icon'] == '🖥️'
    
    def test_get_tools(self):
        """Test EC2 plugin returns tools"""
        config = PluginConfig(
            plugin_id="ec2-tools-test",
            plugin_type="ec2",
            name="EC2 Tools Test",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        plugin = EC2Plugin(config)
        tools = plugin.get_tools()
        
        assert len(tools) > 0
        tool_names = [t.__name__ for t in tools]
        assert 'ec2_list_instances' in tool_names


class TestLambdaPlugin:
    """Test cases for Lambda Plugin"""
    
    def test_plugin_info(self):
        """Test Lambda plugin info"""
        config = PluginConfig(
            plugin_id="lambda-info-test",
            plugin_type="lambda",
            name="Lambda Info Test",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        plugin = LambdaPlugin(config)
        info = plugin.get_info()
        
        assert info['plugin_type'] == 'lambda'
        assert info['icon'] == 'λ'


class TestHPCPlugin:
    """Test cases for HPC Plugin"""
    
    def test_plugin_info(self):
        """Test HPC plugin info"""
        config = PluginConfig(
            plugin_id="hpc-info-test",
            plugin_type="hpc",
            name="HPC Info Test",
            enabled=False,
            config={"regions": ["ap-southeast-1"]}
        )
        
        plugin = HPCPlugin(config)
        info = plugin.get_info()
        
        assert info['plugin_type'] == 'hpc'
        assert 'ParallelCluster' in info['description']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
