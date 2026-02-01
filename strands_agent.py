#!/usr/bin/env python3
"""
AgenticAIOps - Strands Agent Implementation

Using Strands SDK for EKS operations with Bedrock model.
"""

import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from typing import Optional, Dict, Any, List


# Configuration
CLUSTER_NAME = "testing-cluster"
REGION = "ap-southeast-1"

# Initialize boto3 clients
eks_client = boto3.client('eks', region_name=REGION)


# ============================================
# EKS Tools - Read Operations
# ============================================

@tool
def get_cluster_health(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Check the health status of an EKS cluster.
    
    Use this tool when users ask about cluster health, status, or overall condition.
    Returns health status including cluster state and compute configuration.
    
    Args:
        cluster_name: Name of the EKS cluster to check (default: testing-cluster)
    
    Returns:
        Dictionary with health status, checks performed, and overall assessment
    """
    response = eks_client.describe_cluster(name=cluster_name)
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
    
    # Check compute config
    compute = cluster.get('computeConfig', {})
    if compute.get('enabled'):
        health["checks"]["compute"] = {
            "mode": "EKS Auto Mode",
            "nodePools": compute.get('nodePools', []),
            "healthy": True
        }
    
    return {
        "success": True,
        "cluster": cluster_name,
        "health": health
    }


@tool
def get_cluster_info(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Get basic information about an EKS cluster.
    
    Use this tool when users want to know cluster details like version, 
    endpoint, creation time, or platform version.
    
    Args:
        cluster_name: Name of the EKS cluster
    
    Returns:
        Dictionary with cluster name, version, status, endpoint, and platform info
    """
    response = eks_client.describe_cluster(name=cluster_name)
    cluster = response['cluster']
    
    return {
        "success": True,
        "cluster": {
            "name": cluster['name'],
            "version": cluster['version'],
            "status": cluster['status'],
            "endpoint": cluster['endpoint'][:60] + "...",
            "platformVersion": cluster.get('platformVersion'),
            "createdAt": str(cluster['createdAt'])
        }
    }


@tool
def get_nodes(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Get information about cluster nodes and compute configuration.
    
    Use this tool when users ask about nodes, compute resources, or capacity.
    
    Args:
        cluster_name: Name of the EKS cluster
    
    Returns:
        Node/compute configuration depending on cluster mode
    """
    response = eks_client.describe_cluster(name=cluster_name)
    cluster = response['cluster']
    
    compute = cluster.get('computeConfig', {})
    
    if compute.get('enabled'):
        return {
            "success": True,
            "mode": "EKS Auto Mode",
            "description": "Nodes are automatically managed by EKS",
            "nodePools": compute.get('nodePools', []),
            "nodeRoleArn": compute.get('nodeRoleArn', '')[:50] + "..."
        }
    else:
        # List managed node groups
        ng_response = eks_client.list_nodegroups(clusterName=cluster_name)
        return {
            "success": True,
            "mode": "Managed Node Groups",
            "nodegroups": ng_response.get('nodegroups', []),
            "count": len(ng_response.get('nodegroups', []))
        }


@tool
def get_vpc_config(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """Get VPC and networking configuration for the cluster.
    
    Use this tool when users ask about networking, VPC, subnets, or endpoint access.
    
    Args:
        cluster_name: Name of the EKS cluster
    
    Returns:
        VPC configuration including subnet count and endpoint access settings
    """
    response = eks_client.describe_cluster(name=cluster_name)
    vpc = response['cluster']['resourcesVpcConfig']
    
    return {
        "success": True,
        "vpc": {
            "vpcId": vpc['vpcId'],
            "subnetCount": len(vpc['subnetIds']),
            "securityGroupId": vpc.get('clusterSecurityGroupId'),
            "publicAccess": vpc['endpointPublicAccess'],
            "privateAccess": vpc['endpointPrivateAccess']
        }
    }


@tool
def list_nodegroups(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """List all managed node groups in the cluster.
    
    Use this tool to get details about node groups including their status,
    instance types, and scaling configuration.
    
    Args:
        cluster_name: Name of the EKS cluster
    
    Returns:
        List of node groups with their configuration and status
    """
    response = eks_client.list_nodegroups(clusterName=cluster_name)
    nodegroup_names = response.get('nodegroups', [])
    
    nodegroups = []
    for ng_name in nodegroup_names:
        try:
            ng = eks_client.describe_nodegroup(
                clusterName=cluster_name,
                nodegroupName=ng_name
            )['nodegroup']
            
            nodegroups.append({
                'name': ng['nodegroupName'],
                'status': ng['status'],
                'instanceTypes': ng.get('instanceTypes', []),
                'scalingConfig': ng.get('scalingConfig', {}),
                'health': ng.get('health', {}).get('issues', [])
            })
        except Exception as e:
            nodegroups.append({
                'name': ng_name,
                'error': str(e)
            })
    
    return {
        "success": True,
        "count": len(nodegroups),
        "nodegroups": nodegroups
    }


@tool
def get_addons(cluster_name: str = CLUSTER_NAME) -> Dict[str, Any]:
    """List installed add-ons on the EKS cluster.
    
    Use this tool when users ask about cluster add-ons, extensions, or plugins.
    
    Args:
        cluster_name: Name of the EKS cluster
    
    Returns:
        List of installed add-ons with their versions and status
    """
    response = eks_client.list_addons(clusterName=cluster_name)
    addon_names = response.get('addons', [])
    
    addons = []
    for addon_name in addon_names:
        try:
            addon = eks_client.describe_addon(
                clusterName=cluster_name,
                addonName=addon_name
            )['addon']
            
            addons.append({
                'name': addon['addonName'],
                'version': addon['addonVersion'],
                'status': addon['status']
            })
        except Exception as e:
            addons.append({
                'name': addon_name,
                'error': str(e)
            })
    
    return {
        "success": True,
        "count": len(addons),
        "addons": addons
    }


# ============================================
# Agent System Prompt
# ============================================

SYSTEM_PROMPT = """You are an expert SRE AI assistant for Amazon EKS clusters.

Your role:
- Help operators diagnose cluster issues
- Check cluster health and status
- Provide insights about compute, networking, and add-ons
- Be thorough but concise in your responses

Current cluster: {cluster_name}
Region: {region}

Guidelines:
1. Always check cluster health first if the user reports an issue
2. Provide actionable recommendations when problems are found
3. Be clear about what you're checking and why
4. Format responses clearly with bullet points when listing multiple items

Available tools:
- get_cluster_health: Check overall cluster health
- get_cluster_info: Get basic cluster information
- get_nodes: Check compute/node configuration
- get_vpc_config: Check networking setup
- list_nodegroups: List managed node groups
- get_addons: List installed add-ons
""".format(cluster_name=CLUSTER_NAME, region=REGION)


# ============================================
# Create Agent
# ============================================

def create_eks_agent() -> Agent:
    """Create and return the EKS operations agent."""
    
    # Configure Bedrock model with APAC inference profile
    # Using inference profile for cross-region access
    model = BedrockModel(
        model_id="apac.anthropic.claude-3-haiku-20240307-v1:0",
        region_name=REGION
    )
    
    # Create agent with tools
    agent = Agent(
        model=model,
        tools=[
            get_cluster_health,
            get_cluster_info,
            get_nodes,
            get_vpc_config,
            list_nodegroups,
            get_addons
        ],
        system_prompt=SYSTEM_PROMPT
    )
    
    return agent


# ============================================
# Main - Interactive Mode
# ============================================

def main():
    """Run interactive agent session."""
    print("=" * 60)
    print("  AgenticAIOps - Strands SDK Edition")
    print("=" * 60)
    print(f"Cluster: {CLUSTER_NAME}")
    print(f"Region: {REGION}")
    print("Type 'quit' to exit\n")
    
    agent = create_eks_agent()
    
    while True:
        try:
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
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()
