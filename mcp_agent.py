#!/usr/bin/env python3
"""
AgenticAIOps - MCP Server Integration

Strands Agent using AWS MCP Servers for EKS operations.
"""

import os
import sys
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

# Configuration
REGION = "ap-southeast-1"
CLUSTER_NAME = "testing-cluster"


def create_mcp_agent():
    """
    Create Strands Agent with AWS MCP Server integration.
    
    Uses the official AWS EKS MCP Server for cluster operations.
    """
    
    # Configure Bedrock model
    model = BedrockModel(
        model_id="apac.anthropic.claude-3-haiku-20240307-v1:0",
        region_name=REGION
    )
    
    # System prompt for EKS operations
    system_prompt = f"""You are an expert SRE AI assistant for Amazon EKS clusters.

Current cluster: {CLUSTER_NAME}
Region: {REGION}

Your capabilities:
- Check cluster health and status
- List and describe pods, deployments, nodes
- View logs and events
- Diagnose issues and recommend fixes

Guidelines:
1. Be thorough but concise
2. Always check events when troubleshooting
3. Provide actionable recommendations
4. Cite specific evidence for diagnoses
"""
    
    # Initialize MCP client for AWS EKS
    # Note: This requires uvx and the AWS MCP server package
    try:
        from mcp import StdioServerParameters, stdio_client
        
        eks_mcp = MCPClient(
            lambda: stdio_client(
                StdioServerParameters(
                    command="uvx",
                    args=["awslabs.eks-mcp-server@latest"],
                    env={
                        "AWS_REGION": REGION,
                        "EKS_CLUSTER_NAME": CLUSTER_NAME,
                        **os.environ
                    }
                )
            )
        )
        
        with eks_mcp:
            tools = eks_mcp.list_tools_sync()
            print(f"Loaded {len(tools)} tools from AWS EKS MCP Server")
            
            agent = Agent(
                model=model,
                tools=tools,
                system_prompt=system_prompt
            )
            
            return agent, eks_mcp
            
    except ImportError as e:
        print(f"MCP import error: {e}")
        print("Install with: pip install mcp")
        return None, None
    except Exception as e:
        print(f"MCP initialization error: {e}")
        return None, None


def run_with_mcp():
    """Run agent with MCP server."""
    
    print("=" * 70)
    print("  AgenticAIOps - MCP Server Edition")
    print("=" * 70)
    print(f"Cluster: {CLUSTER_NAME}")
    print(f"Region: {REGION}")
    print("Initializing AWS EKS MCP Server...")
    print()
    
    agent, mcp_client = create_mcp_agent()
    
    if agent is None:
        print("Failed to initialize MCP agent. Falling back to custom tools.")
        return
    
    print("Type 'quit' to exit\n")
    
    try:
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            print("\nAgent: ", end="", flush=True)
            response = agent(user_input)
            print(f"{response}\n")
            
    except KeyboardInterrupt:
        print("\nGoodbye!")
    finally:
        if mcp_client:
            # Cleanup MCP connection
            pass


def list_mcp_tools():
    """List available tools from MCP server."""
    
    print("Listing AWS EKS MCP Server tools...\n")
    
    try:
        from mcp import StdioServerParameters, stdio_client
        
        eks_mcp = MCPClient(
            lambda: stdio_client(
                StdioServerParameters(
                    command="uvx",
                    args=["awslabs.eks-mcp-server@latest"],
                    env={
                        "AWS_REGION": REGION,
                        **os.environ
                    }
                )
            )
        )
        
        with eks_mcp:
            tools = eks_mcp.list_tools_sync()
            
            print(f"Found {len(tools)} tools:\n")
            for tool in tools:
                # MCPAgentTool has .tool attribute with actual tool info
                if hasattr(tool, 'tool'):
                    name = tool.tool.name
                    desc = tool.tool.description[:80] if tool.tool.description else ''
                else:
                    name = getattr(tool, 'name', str(tool))
                    desc = getattr(tool, 'description', '')[:80]
                print(f"  - {name}: {desc}...")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list-tools":
        list_mcp_tools()
    else:
        run_with_mcp()
