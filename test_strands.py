#!/usr/bin/env python3
"""
AgenticAIOps - Strands Agent Test Script

Test the Strands-based EKS agent with multiple queries.
"""

import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from typing import Dict, Any
from datetime import datetime


# Configuration
CLUSTER_NAME = "testing-cluster"
REGION = "ap-southeast-1"
eks_client = boto3.client('eks', region_name=REGION)


# ============================================
# Tools
# ============================================

@tool
def get_cluster_health(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Check the health status of an EKS cluster.
    
    Use this tool when users ask about cluster health, status, or overall condition.
    """
    cluster = eks_client.describe_cluster(name=cluster_name)['cluster']
    compute = cluster.get('computeConfig', {})
    
    return {
        "success": True,
        "cluster": cluster_name,
        "status": cluster['status'],
        "version": cluster['version'],
        "healthy": cluster['status'] == 'ACTIVE',
        "computeMode": "EKS Auto Mode" if compute.get('enabled') else "Standard"
    }


@tool
def get_cluster_info(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Get basic information about an EKS cluster.
    
    Use this tool when users want cluster details like version, endpoint, or platform.
    """
    cluster = eks_client.describe_cluster(name=cluster_name)['cluster']
    
    return {
        "success": True,
        "name": cluster['name'],
        "version": cluster['version'],
        "status": cluster['status'],
        "platformVersion": cluster.get('platformVersion'),
        "endpoint": cluster['endpoint'][:50] + "..."
    }


@tool
def get_nodes(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Get information about cluster nodes and compute configuration.
    
    Use this tool when users ask about nodes, compute resources, or capacity.
    """
    cluster = eks_client.describe_cluster(name=cluster_name)['cluster']
    compute = cluster.get('computeConfig', {})
    
    if compute.get('enabled'):
        return {
            "success": True,
            "mode": "EKS Auto Mode",
            "nodePools": compute.get('nodePools', []),
            "description": "Nodes are automatically managed by EKS"
        }
    else:
        ng_response = eks_client.list_nodegroups(clusterName=cluster_name)
        return {
            "success": True,
            "mode": "Managed Node Groups",
            "nodegroups": ng_response.get('nodegroups', [])
        }


@tool
def get_vpc_config(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Get VPC and networking configuration for the cluster.
    
    Use this tool when users ask about networking, VPC, or endpoint access.
    """
    vpc = eks_client.describe_cluster(name=cluster_name)['cluster']['resourcesVpcConfig']
    
    return {
        "success": True,
        "vpcId": vpc['vpcId'],
        "subnetCount": len(vpc['subnetIds']),
        "publicAccess": vpc['endpointPublicAccess'],
        "privateAccess": vpc['endpointPrivateAccess']
    }


# ============================================
# Test Runner
# ============================================

def run_tests():
    """Run test queries against the Strands agent."""
    
    print("=" * 70)
    print("  AgenticAIOps - Strands SDK Test Suite")
    print("=" * 70)
    print(f"Cluster: {CLUSTER_NAME}")
    print(f"Region: {REGION}")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # Create agent
    print("\n[1/4] Creating Bedrock model...")
    model = BedrockModel(
        model_id="apac.anthropic.claude-3-haiku-20240307-v1:0",
        region_name=REGION
    )
    
    print("[2/4] Creating agent with tools...")
    agent = Agent(
        model=model,
        tools=[get_cluster_health, get_cluster_info, get_nodes, get_vpc_config],
        system_prompt="You are an EKS operations assistant. Be concise and helpful."
    )
    
    print("[3/4] Agent ready!")
    print("[4/4] Running test queries...\n")
    
    # Test queries
    test_queries = [
        "Check the health of my EKS cluster",
        "What version is my cluster running?",
        "Tell me about the compute configuration",
        "What's the VPC setup for this cluster?"
    ]
    
    results = []
    
    for i, query in enumerate(test_queries, 1):
        print("-" * 70)
        print(f"Test {i}: {query}")
        print("-" * 70)
        
        try:
            response = agent(query)
            print(f"\n✅ Response: {response}\n")
            results.append(("PASS", query))
        except Exception as e:
            print(f"\n❌ Error: {e}\n")
            results.append(("FAIL", query))
    
    # Summary
    print("=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for r, _ in results if r == "PASS")
    total = len(results)
    
    for status, query in results:
        emoji = "✅" if status == "PASS" else "❌"
        print(f"  {emoji} {status}: {query[:50]}")
    
    print("-" * 70)
    print(f"  Total: {passed}/{total} tests passed")
    print("=" * 70)
    
    return passed == total


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
