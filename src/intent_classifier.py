"""
AgenticAIOps - Intent Classification

Classifies user queries into operation intents and recommends appropriate tools.
"""

from typing import Dict, List, Tuple


# Intent categories with keywords and recommended tools
INTENT_CATEGORIES = {
    "diagnose": {
        "description": "Diagnose issues and troubleshoot problems",
        "keywords": [
            "issue", "error", "fail", "crash", "why", "wrong", "problem",
            "crashloop", "oom", "restart", "backoff", "pending",
            "问题", "故障", "错误", "为什么", "怎么回事"
        ],
        "tools": ["get_pods", "get_events", "get_pod_logs", "describe_pod"]
    },
    "monitor": {
        "description": "Monitor and check status",
        "keywords": [
            "status", "health", "check", "how", "running", "ready",
            "状态", "健康", "检查", "运行"
        ],
        "tools": ["get_cluster_health", "get_pods", "get_nodes", "get_hpa"]
    },
    "scale": {
        "description": "Scale resources up or down",
        "keywords": [
            "scale", "replica", "increase", "decrease", "more", "less",
            "扩容", "缩容", "扩展", "副本"
        ],
        "tools": ["scale_deployment", "get_hpa", "get_deployments"]
    },
    "info": {
        "description": "Get information and list resources",
        "keywords": [
            "what", "list", "show", "get", "version", "info", "describe",
            "什么", "多少", "列出", "显示", "版本"
        ],
        "tools": ["get_cluster_info", "get_pods", "get_deployments", "get_nodes"]
    },
    "recover": {
        "description": "Recovery operations like restart and rollback",
        "keywords": [
            "restart", "rollback", "fix", "recover", "restore",
            "恢复", "回滚", "重启", "修复"
        ],
        "tools": ["scale_deployment", "get_deployments"]  # restart/rollback not implemented yet
    }
}


def classify_intent(query: str) -> Tuple[str, float]:
    """
    Classify user query into an intent category.
    
    Args:
        query: User's natural language query
    
    Returns:
        Tuple of (intent_name, confidence_score)
    """
    query_lower = query.lower()
    
    scores = {}
    for intent, cfg in INTENT_CATEGORIES.items():
        # Count matching keywords
        matches = sum(1 for kw in cfg["keywords"] if kw in query_lower)
        scores[intent] = matches
    
    # Find best match
    max_score = max(scores.values())
    
    if max_score == 0:
        return ("info", 0.0)  # Default to info if no matches
    
    best_intent = max(scores, key=scores.get)
    
    # Calculate confidence (normalized)
    total_keywords = len(INTENT_CATEGORIES[best_intent]["keywords"])
    confidence = min(max_score / 3.0, 1.0)  # Cap at 1.0, need 3 matches for full confidence
    
    return (best_intent, confidence)


def get_tools_for_intent(intent: str) -> List[str]:
    """
    Get recommended tools for a given intent.
    
    Args:
        intent: Intent category name
    
    Returns:
        List of tool names
    """
    return INTENT_CATEGORIES.get(intent, {}).get("tools", [])


def get_intent_description(intent: str) -> str:
    """Get human-readable description of an intent."""
    return INTENT_CATEGORIES.get(intent, {}).get("description", "Unknown intent")


def filter_tools_by_intent(tools: List, intent: str) -> List:
    """
    Filter a list of tools to only those relevant for the intent.
    
    Args:
        tools: List of tool objects
        intent: Intent category
    
    Returns:
        Filtered list of tools
    """
    recommended = get_tools_for_intent(intent)
    if not recommended:
        return tools  # Return all if no recommendations
    
    # Filter tools by name
    return [t for t in tools if getattr(t, '__name__', str(t)) in recommended]


# Convenience function for quick classification
def analyze_query(query: str) -> Dict:
    """
    Full analysis of a user query.
    
    Returns dict with intent, confidence, description, and recommended tools.
    """
    intent, confidence = classify_intent(query)
    return {
        "query": query,
        "intent": intent,
        "confidence": confidence,
        "description": get_intent_description(intent),
        "recommended_tools": get_tools_for_intent(intent)
    }


# Test
if __name__ == "__main__":
    test_queries = [
        "What pods are having issues?",
        "Check the health of my cluster",
        "Scale the deployment to 5 replicas",
        "List all deployments in bookstore",
        "Why is my pod crashing?",
        "集群状态怎么样?",
        "扩容 shop-frontend 到 4 个副本",
    ]
    
    print("Intent Classification Test\n" + "="*50)
    for query in test_queries:
        result = analyze_query(query)
        print(f"\nQuery: {query}")
        print(f"  Intent: {result['intent']} (confidence: {result['confidence']:.2f})")
        print(f"  Tools: {', '.join(result['recommended_tools'][:3])}...")
