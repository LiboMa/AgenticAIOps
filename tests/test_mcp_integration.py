"""
ACI MCP Integration Tests

Tests for MCP bridge and integration layer.
These tests verify the integration between ACI and AWS EKS MCP Server.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os


class TestACIMCPBridge:
    """Tests for ACIMCPBridge class."""
    
    def test_bridge_init(self):
        """Test bridge initialization with default parameters."""
        from src.aci.mcp_bridge import ACIMCPBridge
        
        bridge = ACIMCPBridge()
        assert bridge.cluster_name == "testing-cluster"
        assert bridge.region == "ap-southeast-1"
        assert bridge._mcp_client is None
    
    def test_bridge_custom_cluster(self):
        """Test bridge with custom cluster configuration."""
        from src.aci.mcp_bridge import ACIMCPBridge
        
        bridge = ACIMCPBridge(
            cluster_name="custom-cluster",
            region="us-west-2"
        )
        assert bridge.cluster_name == "custom-cluster"
        assert bridge.region == "us-west-2"
    
    def test_list_available_tools_empty(self):
        """Test listing tools when MCP is not initialized."""
        from src.aci.mcp_bridge import ACIMCPBridge
        
        bridge = ACIMCPBridge()
        tools = bridge.list_available_tools()
        assert tools == []
    
    def test_call_tool_not_initialized(self):
        """Test calling tool when MCP is not initialized."""
        from src.aci.mcp_bridge import ACIMCPBridge
        
        bridge = ACIMCPBridge()
        result = bridge.call_tool("get_pod_logs", namespace="default")
        assert "error" in result
        assert result["error"] == "MCP not initialized"


class TestMCPToolMapping:
    """Tests for MCP tool mapping configuration."""
    
    def test_mapping_exists(self):
        """Test that MCP tool mapping is defined."""
        from src.aci.mcp_bridge import MCP_TOOL_MAPPING
        
        assert "get_logs" in MCP_TOOL_MAPPING
        assert "get_metrics" in MCP_TOOL_MAPPING
        assert "get_events" in MCP_TOOL_MAPPING
        assert "kubectl" in MCP_TOOL_MAPPING
    
    def test_get_logs_mapping(self):
        """Test get_logs maps to correct MCP tools."""
        from src.aci.mcp_bridge import MCP_TOOL_MAPPING
        
        assert "get_pod_logs" in MCP_TOOL_MAPPING["get_logs"]
        assert "get_cloudwatch_logs" in MCP_TOOL_MAPPING["get_logs"]
    
    def test_get_metrics_mapping(self):
        """Test get_metrics maps to CloudWatch."""
        from src.aci.mcp_bridge import MCP_TOOL_MAPPING
        
        assert "get_cloudwatch_metrics" in MCP_TOOL_MAPPING["get_metrics"]
    
    def test_kubectl_mapping(self):
        """Test kubectl maps to k8s resource management."""
        from src.aci.mcp_bridge import MCP_TOOL_MAPPING
        
        assert "list_k8s_resources" in MCP_TOOL_MAPPING["kubectl"]
        assert "manage_k8s_resource" in MCP_TOOL_MAPPING["kubectl"]


class TestCreateMCPEnhancedACI:
    """Tests for create_mcp_enhanced_aci factory function."""
    
    def test_create_enhanced_aci(self):
        """Test creating MCP-enhanced ACI instance."""
        from src.aci.mcp_bridge import create_mcp_enhanced_aci
        
        aci = create_mcp_enhanced_aci()
        
        assert aci is not None
        assert hasattr(aci, 'mcp_bridge')
        assert aci.cluster_name == "testing-cluster"
    
    def test_create_enhanced_aci_custom_cluster(self):
        """Test creating MCP-enhanced ACI with custom cluster."""
        from src.aci.mcp_bridge import create_mcp_enhanced_aci
        
        aci = create_mcp_enhanced_aci(
            cluster_name="production-cluster",
            region="eu-west-1"
        )
        
        assert aci.cluster_name == "production-cluster"
        assert aci.region == "eu-west-1"


class TestACIWithMCPBridge:
    """Integration tests for ACI with MCP bridge."""
    
    def test_aci_has_mcp_bridge(self):
        """Test that enhanced ACI has MCP bridge attached."""
        from src.aci.mcp_bridge import create_mcp_enhanced_aci
        
        aci = create_mcp_enhanced_aci()
        
        assert hasattr(aci, 'mcp_bridge')
        assert aci.mcp_bridge is not None
        assert aci.mcp_bridge.cluster_name == aci.cluster_name
    
    def test_aci_get_logs_with_bridge(self):
        """Test ACI get_logs works with bridge attached."""
        from src.aci.mcp_bridge import create_mcp_enhanced_aci
        
        aci = create_mcp_enhanced_aci()
        
        # Should work even without active MCP connection
        result = aci.get_logs(namespace="default")
        assert result is not None
        # TelemetryResult has 'status' not 'success'
        assert hasattr(result, 'status')
    
    def test_aci_kubectl_with_bridge(self):
        """Test ACI kubectl works with bridge attached."""
        from src.aci.mcp_bridge import create_mcp_enhanced_aci
        
        aci = create_mcp_enhanced_aci()
        
        result = aci.kubectl(["get", "pods"])
        assert result is not None


class TestMCPBridgeInitialize:
    """Tests for MCP bridge initialization."""
    
    def test_initialize_without_mcp_packages(self):
        """Test initialization when MCP packages not installed."""
        from src.aci.mcp_bridge import ACIMCPBridge
        
        bridge = ACIMCPBridge()
        
        # Mock ImportError for missing packages
        with patch.dict('sys.modules', {'strands.tools.mcp': None}):
            # Should handle gracefully
            bridge = ACIMCPBridge()
            # list_available_tools should return empty list
            assert bridge.list_available_tools() == []


class TestMCPBridgeToolIntegration:
    """Tests for actual MCP tool integration (requires MCP runtime)."""
    
    @pytest.mark.skipif(
        os.environ.get('SKIP_MCP_TESTS', 'true').lower() == 'true',
        reason="MCP integration tests skipped - set SKIP_MCP_TESTS=false to run"
    )
    def test_mcp_tools_available(self):
        """Test that MCP tools are available when initialized."""
        from src.aci.mcp_bridge import ACIMCPBridge
        
        bridge = ACIMCPBridge()
        if bridge.initialize():
            tools = bridge.list_available_tools()
            assert len(tools) > 0
            # Should have EKS MCP tools
            assert any('log' in t.lower() for t in tools)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
