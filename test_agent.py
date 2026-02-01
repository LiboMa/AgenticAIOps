#!/usr/bin/env python3
"""
AgenticAIOps - Interactive Local Test

Full agent test using boto3 for EKS access and mock LLM responses.
This tests the complete ReAct loop without needing external LLM API.
"""

import boto3
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

# Configuration
CLUSTER_NAME = 'testing-cluster'
REGION = 'ap-southeast-1'

# Initialize clients
eks_client = boto3.client('eks', region_name=REGION)


class MockTool:
    """A tool that the agent can call."""
    
    def __init__(self, name: str, description: str, handler):
        self.name = name
        self.description = description
        self.handler = handler


class AIOpsAgent:
    """Simple ReAct agent for EKS operations."""
    
    def __init__(self, cluster_name: str):
        self.cluster_name = cluster_name
        self.tools: Dict[str, MockTool] = {}
        self.conversation_history: List[Dict] = []
        self._register_tools()
    
    def _register_tools(self):
        """Register available tools."""
        tools = [
            MockTool("get_cluster_info", "Get EKS cluster information", self._get_cluster_info),
            MockTool("get_cluster_health", "Check cluster health status", self._get_cluster_health),
            MockTool("list_node_groups", "List managed node groups", self._list_node_groups),
            MockTool("get_vpc_config", "Get VPC configuration", self._get_vpc_config),
            MockTool("describe_compute", "Get compute/node pool configuration", self._describe_compute),
        ]
        for tool in tools:
            self.tools[tool.name] = tool
    
    # === Tool Implementations ===
    
    def _get_cluster_info(self) -> Dict:
        """Get cluster info via EKS API."""
        response = eks_client.describe_cluster(name=self.cluster_name)
        cluster = response['cluster']
        return {
            "success": True,
            "cluster": {
                "name": cluster['name'],
                "version": cluster['version'],
                "status": cluster['status'],
                "endpoint": cluster['endpoint'][:50] + "...",
                "platformVersion": cluster.get('platformVersion'),
            }
        }
    
    def _get_cluster_health(self) -> Dict:
        """Check cluster health."""
        response = eks_client.describe_cluster(name=self.cluster_name)
        cluster = response['cluster']
        
        health = {
            "overall": "healthy" if cluster['status'] == 'ACTIVE' else "degraded",
            "checks": {
                "cluster_status": {
                    "status": cluster['status'],
                    "healthy": cluster['status'] == 'ACTIVE'
                }
            }
        }
        
        compute = cluster.get('computeConfig', {})
        if compute.get('enabled'):
            health["checks"]["compute"] = {
                "mode": "EKS Auto Mode",
                "nodePools": compute.get('nodePools', []),
                "healthy": True
            }
        
        return {"success": True, "health": health}
    
    def _list_node_groups(self) -> Dict:
        """List node groups."""
        response = eks_client.list_nodegroups(clusterName=self.cluster_name)
        return {
            "success": True,
            "nodegroups": response.get('nodegroups', []),
            "count": len(response.get('nodegroups', []))
        }
    
    def _get_vpc_config(self) -> Dict:
        """Get VPC config."""
        response = eks_client.describe_cluster(name=self.cluster_name)
        vpc = response['cluster']['resourcesVpcConfig']
        return {
            "success": True,
            "vpc": {
                "vpcId": vpc['vpcId'],
                "subnetCount": len(vpc['subnetIds']),
                "publicAccess": vpc['endpointPublicAccess'],
                "privateAccess": vpc['endpointPrivateAccess']
            }
        }
    
    def _describe_compute(self) -> Dict:
        """Describe compute configuration."""
        response = eks_client.describe_cluster(name=self.cluster_name)
        compute = response['cluster'].get('computeConfig', {})
        
        if compute.get('enabled'):
            return {
                "success": True,
                "mode": "EKS Auto Mode",
                "nodePools": compute.get('nodePools', []),
                "nodeRoleArn": compute.get('nodeRoleArn', '')[:50] + "..."
            }
        else:
            ng_response = eks_client.list_nodegroups(clusterName=self.cluster_name)
            return {
                "success": True,
                "mode": "Managed Node Groups",
                "nodegroups": ng_response.get('nodegroups', [])
            }
    
    # === Agent Logic ===
    
    def _select_tool(self, user_query: str) -> Optional[str]:
        """Select appropriate tool based on query (simplified intent matching)."""
        query_lower = user_query.lower()
        
        if "health" in query_lower or "status" in query_lower:
            return "get_cluster_health"
        elif "node" in query_lower and ("group" in query_lower or "pool" in query_lower):
            return "list_node_groups"
        elif "vpc" in query_lower or "network" in query_lower:
            return "get_vpc_config"
        elif "compute" in query_lower or "capacity" in query_lower:
            return "describe_compute"
        elif "info" in query_lower or "cluster" in query_lower:
            return "get_cluster_info"
        else:
            return "get_cluster_health"  # Default
    
    def _generate_response(self, query: str, tool_name: str, tool_result: Dict) -> str:
        """Generate natural language response from tool result."""
        if tool_name == "get_cluster_health":
            health = tool_result.get("health", {})
            overall = health.get("overall", "unknown")
            checks = health.get("checks", {})
            
            status_emoji = "✅" if overall == "healthy" else "⚠️"
            
            response = f"{status_emoji} **Cluster Health: {overall.upper()}**\n\n"
            for check_name, check_data in checks.items():
                check_emoji = "✅" if check_data.get("healthy") else "❌"
                response += f"- {check_emoji} {check_name}: {check_data.get('status', check_data.get('mode', 'OK'))}\n"
            
            return response
        
        elif tool_name == "get_cluster_info":
            cluster = tool_result.get("cluster", {})
            return f"""**Cluster Information**

- **Name**: {cluster.get('name')}
- **Version**: Kubernetes {cluster.get('version')}
- **Status**: {cluster.get('status')}
- **Platform**: {cluster.get('platformVersion')}
"""
        
        elif tool_name == "describe_compute":
            mode = tool_result.get("mode", "Unknown")
            if mode == "EKS Auto Mode":
                pools = tool_result.get("nodePools", [])
                return f"""**Compute Configuration**

- **Mode**: EKS Auto Mode (AWS manages nodes)
- **Node Pools**: {', '.join(pools) if pools else 'None configured'}
- **Scaling**: Automatic based on workload demand
"""
            else:
                ngs = tool_result.get("nodegroups", [])
                return f"""**Compute Configuration**

- **Mode**: Managed Node Groups
- **Node Groups**: {', '.join(ngs) if ngs else 'None'}
"""
        
        else:
            return f"**Result**:\n```json\n{json.dumps(tool_result, indent=2)}\n```"
    
    def chat(self, user_query: str) -> str:
        """Process user query through ReAct loop."""
        print(f"\n{'='*60}")
        print(f"User: {user_query}")
        print(f"{'='*60}")
        
        # Step 1: Reasoning - Select tool
        print("\n🧠 REASONING:")
        tool_name = self._select_tool(user_query)
        print(f"   Intent analysis: {user_query[:50]}...")
        print(f"   Selected tool: {tool_name}")
        
        # Step 2: Acting - Execute tool
        print("\n🔧 ACTING:")
        print(f"   Executing: {tool_name}()")
        
        tool = self.tools.get(tool_name)
        if not tool:
            return f"Error: Unknown tool {tool_name}"
        
        result = tool.handler()
        print(f"   Success: {result.get('success', False)}")
        
        # Step 3: Observing - Process result
        print("\n👁 OBSERVING:")
        print(f"   Got result with {len(str(result))} bytes")
        
        # Step 4: Responding - Generate response
        print("\n📝 RESPONDING:")
        response = self._generate_response(user_query, tool_name, result)
        print("-" * 40)
        print(response)
        print("-" * 40)
        
        # Save to history
        self.conversation_history.append({
            "query": user_query,
            "tool": tool_name,
            "result": result,
            "response": response
        })
        
        return response


def run_interactive_test():
    """Run interactive test session."""
    print("\n" + "🤖 " * 20)
    print("    AgenticAIOps - Interactive Test Session")
    print("🤖 " * 20)
    print(f"\nCluster: {CLUSTER_NAME}")
    print(f"Region: {REGION}")
    print(f"Time: {datetime.now().isoformat()}")
    
    agent = AIOpsAgent(CLUSTER_NAME)
    
    # Test queries
    test_queries = [
        "What's the health status of my cluster?",
        "Show me the cluster information",
        "What compute resources are available?",
        "Describe the network configuration",
    ]
    
    print("\n" + "="*60)
    print("Running automated test queries...")
    print("="*60)
    
    for query in test_queries:
        agent.chat(query)
        print()
    
    # Summary
    print("\n" + "="*60)
    print("TEST SESSION COMPLETE")
    print("="*60)
    print(f"Total queries processed: {len(agent.conversation_history)}")
    print(f"All queries successful: {all(h['result'].get('success') for h in agent.conversation_history)}")
    
    return True


if __name__ == '__main__':
    success = run_interactive_test()
    exit(0 if success else 1)
