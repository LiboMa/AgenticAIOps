#!/usr/bin/env python3
"""
Test script for the full Strands Agent with K8s tools.
"""

import sys
sys.path.insert(0, '/home/ubuntu/agentic-aiops-mvp')

from strands_agent_full import create_eks_agent


def run_tests():
    """Run test queries against the full agent."""
    
    print("=" * 70)
    print("  AgenticAIOps - Full Agent Test Suite")
    print("=" * 70)
    
    agent = create_eks_agent()
    
    test_queries = [
        "List all pods in the onlineshop namespace",
        "What deployments are in the bookstore namespace?",
        "Show me recent events in faulty-apps namespace",
        "Are there any pods with issues?",
        "Check the HPA status for all namespaces",
    ]
    
    results = []
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'='*70}")
        print(f"Test {i}: {query}")
        print("="*70)
        
        try:
            response = agent(query)
            # Convert AgentResult to string
            response_text = str(response)
            print(f"\n✅ Response: {response_text[:500]}...")
            results.append(("PASS", query))
        except Exception as e:
            print(f"\n❌ Error: {e}")
            results.append(("FAIL", query))
    
    # Summary
    print("\n" + "="*70)
    print("  TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for r, _ in results if r == "PASS")
    for status, query in results:
        emoji = "✅" if status == "PASS" else "❌"
        print(f"  {emoji} {status}: {query[:50]}")
    
    print(f"\n  Total: {passed}/{len(results)} tests passed")
    print("="*70)
    
    return passed == len(results)


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
