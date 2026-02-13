"""
AgenticAIOps - Multi-Agent Voting

Implements voting mechanism to reduce hallucinations by running multiple
inferences and selecting the consensus answer.
"""

from collections import Counter
from typing import List, Dict, Any, Optional
import re


# =============================================================================
# Diagnosis Extraction Patterns
# =============================================================================

DIAGNOSIS_PATTERNS = {
    "oom": [
        "oom", "out of memory", "memory limit", "killed", "oomkilled",
        "memory exceeded", "内存不足", "内存溢出"
    ],
    "crashloop": [
        "crashloop", "crash loop", "backoff", "crashloopbackoff",
        "container crash", "重启", "崩溃循环"
    ],
    "imagepull": [
        "imagepull", "image pull", "pull image", "imagepullbackoff",
        "image not found", "镜像拉取", "镜像失败"
    ],
    "pending": [
        "pending", "unschedulable", "insufficient", "no nodes",
        "无法调度", "等待", "资源不足"
    ],
    "network": [
        "network", "connection", "timeout", "dns", "refused",
        "unreachable", "网络", "连接失败"
    ],
    "config": [
        "config", "env", "secret", "configmap", "missing",
        "invalid", "配置", "环境变量"
    ],
    "resource": [
        "resource", "cpu", "quota", "limit", "request",
        "资源", "配额"
    ],
    "permission": [
        "permission", "denied", "forbidden", "rbac", "unauthorized",
        "权限", "拒绝"
    ],
    "healthy": [
        "healthy", "running", "ready", "ok", "success",
        "正常", "健康", "运行中"
    ]
}


def extract_diagnosis(response: str) -> str:
    """
    Extract diagnosis conclusion from agent response.
    
    Args:
        response: Agent's text response
        
    Returns:
        Diagnosis category (e.g., "oom", "crashloop", "healthy")
    """
    response_lower = response.lower()
    scores = {}
    
    for diagnosis, keywords in DIAGNOSIS_PATTERNS.items():
        score = sum(1 for kw in keywords if kw in response_lower)
        if score > 0:
            scores[diagnosis] = score
    
    if scores:
        return max(scores, key=scores.get)
    return "unknown"


# =============================================================================
# Multi-Agent Voting Implementation
# =============================================================================

def multi_agent_vote(
    agent,
    query: str,
    num_votes: int = 3,
    temperatures: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Multi-agent voting mechanism using different temperatures.
    
    This simulates multiple "agents" by running the same query with
    different temperature settings, then aggregating the diagnoses.
    
    Args:
        agent: Strands Agent instance
        query: User's query
        num_votes: Number of voting rounds (default: 3)
        temperatures: Temperature values for each round
        
    Returns:
        Dict with voting results including:
        - final_diagnosis: Winner of the vote
        - confidence: Vote confidence (0-1)
        - consensus: Whether all votes agreed
        - vote_count: Breakdown of votes
        - responses: Individual responses
    """
    if temperatures is None:
        temperatures = [0.1, 0.3, 0.5]
    
    responses = []
    
    # Note: Strands/Bedrock may not support temperature changes on-the-fly
    # This is a simplified implementation that runs multiple queries
    
    for i in range(min(num_votes, len(temperatures))):
        try:
            # Run agent query
            response = str(agent(query))
            diagnosis = extract_diagnosis(response)
            
            responses.append({
                "vote_id": i + 1,
                "temperature": temperatures[i],
                "response": response[:500],  # Truncate for storage
                "diagnosis": diagnosis
            })
        except Exception as e:
            responses.append({
                "vote_id": i + 1,
                "temperature": temperatures[i],
                "response": f"Error: {str(e)}",
                "diagnosis": "error"
            })
    
    # Aggregate votes
    diagnoses = [r["diagnosis"] for r in responses if r["diagnosis"] != "error"]
    
    if not diagnoses:
        return {
            "query": query,
            "final_diagnosis": "error",
            "confidence": 0.0,
            "vote_count": {},
            "consensus": False,
            "responses": responses
        }
    
    vote_count = Counter(diagnoses)
    winner, win_count = vote_count.most_common(1)[0]
    
    return {
        "query": query,
        "final_diagnosis": winner,
        "confidence": round(win_count / len(diagnoses), 2),
        "vote_count": dict(vote_count),
        "consensus": win_count == len(diagnoses),
        "responses": responses
    }


def vote_and_respond(agent, query: str, num_votes: int = 3) -> str:
    """
    Run voting and return a formatted response.
    
    Args:
        agent: Strands Agent instance
        query: User's query
        num_votes: Number of voting rounds
        
    Returns:
        Formatted response string with diagnosis and confidence
    """
    result = multi_agent_vote(agent, query, num_votes=num_votes)
    
    # Determine confidence level
    if result["consensus"]:
        confidence_str = "高置信度 ✅"
    elif result["confidence"] >= 0.66:
        confidence_str = "中置信度 ⚠️"
    else:
        confidence_str = "低置信度 ❓ (建议人工确认)"
    
    # Find the best response (one matching the winning diagnosis)
    best_response = next(
        (r for r in result["responses"] if r["diagnosis"] == result["final_diagnosis"]),
        result["responses"][0] if result["responses"] else {"response": "No response"}
    )
    
    return f"""[{confidence_str}] 诊断结论: {result['final_diagnosis']}
投票结果: {result['vote_count']}
一致性: {'全部一致' if result['consensus'] else '部分分歧'}

{best_response['response']}"""


def simple_vote(responses: List[str]) -> Dict[str, Any]:
    """
    Simple voting from a list of pre-generated responses.
    
    Useful when you already have multiple responses and just need to vote.
    
    Args:
        responses: List of agent response strings
        
    Returns:
        Voting result dict
    """
    diagnoses = [extract_diagnosis(r) for r in responses]
    vote_count = Counter(diagnoses)
    
    if not vote_count:
        return {"diagnosis": "unknown", "confidence": 0.0, "votes": {}}
    
    winner, win_count = vote_count.most_common(1)[0]
    
    return {
        "diagnosis": winner,
        "confidence": round(win_count / len(diagnoses), 2),
        "votes": dict(vote_count),
        "consensus": win_count == len(diagnoses)
    }


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    print("Multi-Agent Voting Test\n" + "="*50)
    
    # Test diagnosis extraction
    test_responses = [
        "The pod is crashing due to OOM - out of memory error",
        "Memory limit exceeded, the container was killed by OOM killer",
        "OOMKilled: container terminated due to memory pressure"
    ]
    
    print("\nTest 1: OOM responses")
    for i, resp in enumerate(test_responses):
        diag = extract_diagnosis(resp)
        print(f"  Response {i+1}: {diag}")
    
    result = simple_vote(test_responses)
    print(f"\n  Vote result: {result}")
    
    # Test mixed responses
    print("\n" + "="*50)
    print("Test 2: Mixed responses")
    
    mixed_responses = [
        "The pod has ImagePullBackOff error - cannot pull the image",
        "Image pull failed: repository not found",
        "The container is in CrashLoopBackOff state"
    ]
    
    for i, resp in enumerate(mixed_responses):
        diag = extract_diagnosis(resp)
        print(f"  Response {i+1}: {diag}")
    
    result = simple_vote(mixed_responses)
    print(f"\n  Vote result: {result}")
    print(f"  Consensus: {result['consensus']}")
