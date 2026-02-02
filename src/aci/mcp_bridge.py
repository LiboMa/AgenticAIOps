"""
ACI MCP Integration Layer

Provides integration between ACI and AWS EKS MCP Server.
This is a thin wrapper that bridges ACI interface to MCP tools.
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# MCP Tool mappings to ACI methods
MCP_TOOL_MAPPING = {
    # Telemetry
    "get_logs": ["get_pod_logs", "get_cloudwatch_logs"],
    "get_metrics": ["get_cloudwatch_metrics"],
    "get_events": ["get_k8s_events"],
    
    # Operations
    "kubectl": ["list_k8s_resources", "manage_k8s_resource"],
    "apply_yaml": ["apply_yaml"],
    "manage_stacks": ["manage_eks_stacks"],
    
    # Context
    "get_insights": ["get_eks_insights"],
    "troubleshoot": ["search_eks_troubleshoot_guide"],
    "get_vpc_config": ["get_eks_vpc_config"],
    "get_policies": ["get_policies_for_role"],
}


class ACIMCPBridge:
    """
    Bridge between ACI and MCP tools.
    
    Provides unified interface while leveraging MCP backend.
    """
    
    def __init__(
        self,
        cluster_name: str = "testing-cluster",
        region: str = "ap-southeast-1",
    ):
        self.cluster_name = cluster_name
        self.region = region
        self._mcp_client = None
        self._tools = {}
    
    def initialize(self) -> bool:
        """
        Initialize MCP connection.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            from strands.tools.mcp import MCPClient
            from mcp import StdioServerParameters, stdio_client
            
            self._mcp_client = MCPClient(
                lambda: stdio_client(
                    StdioServerParameters(
                        command="uvx",
                        args=["awslabs.eks-mcp-server@latest"],
                        env={
                            "AWS_REGION": self.region,
                            "EKS_CLUSTER_NAME": self.cluster_name,
                            **os.environ
                        }
                    )
                )
            )
            
            logger.info(f"MCP Bridge initialized for cluster={self.cluster_name}")
            return True
            
        except ImportError as e:
            logger.warning(f"MCP not available: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize MCP: {e}")
            return False
    
    def get_tools(self) -> List[Any]:
        """
        Get available MCP tools.
        
        Returns:
            List of MCP tools
        """
        if not self._mcp_client:
            return []
        
        try:
            with self._mcp_client:
                tools = self._mcp_client.list_tools_sync()
                return tools
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            return []
    
    def list_available_tools(self) -> List[str]:
        """
        List available tool names.
        
        Returns:
            List of tool names
        """
        tools = self.get_tools()
        names = []
        
        for tool in tools:
            if hasattr(tool, 'tool'):
                names.append(tool.tool.name)
            elif hasattr(tool, 'name'):
                names.append(tool.name)
        
        return names
    
    def call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Call an MCP tool by name.
        
        Args:
            tool_name: Name of the MCP tool
            **kwargs: Tool arguments
        
        Returns:
            Tool result
        """
        if not self._mcp_client:
            return {"error": "MCP not initialized"}
        
        try:
            # This would require the actual MCP tool invocation
            # For now, return a placeholder
            return {
                "status": "not_implemented",
                "message": f"Direct MCP tool invocation for {tool_name} requires runtime context",
            }
        except Exception as e:
            logger.error(f"Failed to call MCP tool {tool_name}: {e}")
            return {"error": str(e)}


def create_mcp_enhanced_aci(
    cluster_name: str = "testing-cluster",
    region: str = "ap-southeast-1",
):
    """
    Create ACI instance with MCP backend.
    
    This combines the ACI interface with MCP tools for enhanced capabilities.
    
    Usage:
        aci = create_mcp_enhanced_aci()
        
        # Use ACI methods (backed by kubectl)
        logs = aci.get_logs(namespace="default")
        
        # Access MCP tools directly
        mcp_tools = aci.mcp_bridge.get_tools()
    """
    from .interface import AgentCloudInterface
    
    aci = AgentCloudInterface(
        cluster_name=cluster_name,
        region=region,
    )
    
    # Attach MCP bridge
    aci.mcp_bridge = ACIMCPBridge(cluster_name, region)
    aci.mcp_bridge.initialize()
    
    return aci
