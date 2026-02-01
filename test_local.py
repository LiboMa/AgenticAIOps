#!/usr/bin/env python3
"""
AgenticAIOps - Local Test Script

Test the MVP locally using boto3 to access EKS (no kubectl needed).
"""

import boto3
import json
from datetime import datetime

# Configuration
CLUSTER_NAME = 'testing-cluster'
REGION = 'ap-southeast-1'

# Initialize clients
eks_client = boto3.client('eks', region_name=REGION)

def print_header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def test_cluster_info():
    """Test getting cluster information."""
    print_header("Test 1: Get Cluster Info")
    
    response = eks_client.describe_cluster(name=CLUSTER_NAME)
    cluster = response['cluster']
    
    print(f"Cluster Name: {cluster['name']}")
    print(f"Version: {cluster['version']}")
    print(f"Status: {cluster['status']}")
    print(f"Endpoint: {cluster['endpoint'][:50]}...")
    print(f"Platform Version: {cluster.get('platformVersion', 'N/A')}")
    
    return cluster['status'] == 'ACTIVE'

def test_compute_config():
    """Test getting compute/node configuration."""
    print_header("Test 2: Get Compute Config")
    
    response = eks_client.describe_cluster(name=CLUSTER_NAME)
    cluster = response['cluster']
    
    compute = cluster.get('computeConfig', {})
    
    if compute.get('enabled'):
        print("Mode: EKS Auto Mode")
        print(f"Node Pools: {compute.get('nodePools', [])}")
        print(f"Node Role: {compute.get('nodeRoleArn', 'N/A')}")
    else:
        # Traditional node groups
        ng_response = eks_client.list_nodegroups(clusterName=CLUSTER_NAME)
        print("Mode: Managed Node Groups")
        print(f"Node Groups: {ng_response.get('nodegroups', [])}")
    
    return True

def test_cluster_health():
    """Test cluster health check."""
    print_header("Test 3: Cluster Health Check")
    
    response = eks_client.describe_cluster(name=CLUSTER_NAME)
    cluster = response['cluster']
    
    health = {
        'overall': 'healthy',
        'checks': {}
    }
    
    # Cluster status
    health['checks']['cluster'] = {
        'status': cluster['status'],
        'healthy': cluster['status'] == 'ACTIVE'
    }
    
    if cluster['status'] != 'ACTIVE':
        health['overall'] = 'degraded'
    
    # Compute config
    compute = cluster.get('computeConfig', {})
    if compute.get('enabled'):
        health['checks']['compute'] = {
            'mode': 'EKS Auto Mode',
            'nodePools': compute.get('nodePools', []),
            'healthy': True
        }
    
    print(f"Overall Health: {health['overall']}")
    for check_name, check_data in health['checks'].items():
        status = '✅' if check_data.get('healthy') else '❌'
        print(f"  {status} {check_name}: {check_data.get('status', check_data.get('mode', 'OK'))}")
    
    return health['overall'] == 'healthy'

def test_vpc_config():
    """Test VPC configuration."""
    print_header("Test 4: VPC Configuration")
    
    response = eks_client.describe_cluster(name=CLUSTER_NAME)
    vpc_config = response['cluster']['resourcesVpcConfig']
    
    print(f"VPC ID: {vpc_config['vpcId']}")
    print(f"Subnets: {len(vpc_config['subnetIds'])} subnets")
    print(f"Public Access: {vpc_config['endpointPublicAccess']}")
    print(f"Private Access: {vpc_config['endpointPrivateAccess']}")
    
    return True

def simulate_agent_interaction():
    """Simulate an agent interaction."""
    print_header("Test 5: Simulated Agent Interaction")
    
    user_query = "Check the health of my EKS cluster"
    print(f"User: {user_query}\n")
    
    # Simulate agent reasoning
    print("🧠 Agent Reasoning:")
    print("   → User wants cluster health check")
    print("   → Will call getClusterHealth action")
    print()
    
    # Execute the "tool"
    print("🔧 Executing: getClusterHealth()")
    
    response = eks_client.describe_cluster(name=CLUSTER_NAME)
    cluster = response['cluster']
    compute = cluster.get('computeConfig', {})
    
    print("👁 Observation: Got cluster data\n")
    
    # Generate response
    print("📝 Agent Response:")
    print("-" * 40)
    print(f"""
Your EKS cluster 'testing-cluster' is healthy! ✅

**Cluster Status**: {cluster['status']}
**Kubernetes Version**: {cluster['version']}
**Mode**: {'EKS Auto Mode' if compute.get('enabled') else 'Standard'}

**Compute Configuration**:
- Node Pools: {', '.join(compute.get('nodePools', ['N/A']))}
- All systems operational

No issues detected. Your cluster is ready for workloads.
""")
    print("-" * 40)
    
    return True

def main():
    """Run all tests."""
    print("\n" + "🚀 " * 20)
    print("      AgenticAIOps MVP - Local Test Suite")
    print("🚀 " * 20)
    print(f"\nCluster: {CLUSTER_NAME}")
    print(f"Region: {REGION}")
    print(f"Time: {datetime.now().isoformat()}")
    
    tests = [
        ("Cluster Info", test_cluster_info),
        ("Compute Config", test_compute_config),
        ("Cluster Health", test_cluster_health),
        ("VPC Config", test_vpc_config),
        ("Agent Simulation", simulate_agent_interaction),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Error: {e}")
            results.append((name, False))
    
    # Summary
    print_header("Test Summary")
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("\n" + "="*60)
    
    return passed == total

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
