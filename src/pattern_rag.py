"""
AgenticAIOps - Bedrock Knowledge Base RAG Integration

Provides pattern search using AWS Bedrock Knowledge Base.
"""

import os
import boto3
from typing import List, Dict, Any, Optional


class PatternRAG:
    """
    RAG system for EKS troubleshooting patterns using Bedrock Knowledge Base.
    """
    
    def __init__(
        self,
        knowledge_base_id: str,
        region: str = "ap-southeast-1",
        max_results: int = 3
    ):
        """
        Initialize PatternRAG.
        
        Args:
            knowledge_base_id: Bedrock Knowledge Base ID
            region: AWS region
            max_results: Maximum number of results to return
        """
        self.knowledge_base_id = knowledge_base_id
        self.region = region
        self.max_results = max_results
        
        self.client = boto3.client(
            'bedrock-agent-runtime',
            region_name=region
        )
    
    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search patterns in Knowledge Base.
        
        Args:
            query: Search query
            max_results: Override default max results
            
        Returns:
            List of matching patterns with content and metadata
        """
        try:
            response = self.client.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": max_results or self.max_results
                    }
                }
            )
            
            results = []
            for item in response.get('retrievalResults', []):
                content = item.get('content', {})
                location = item.get('location', {})
                
                results.append({
                    "content": content.get('text', ''),
                    "score": item.get('score', 0),
                    "source": location.get('s3Location', {}).get('uri', ''),
                    "metadata": item.get('metadata', {})
                })
            
            return results
            
        except Exception as e:
            print(f"KB search error: {e}")
            return []
    
    def search_formatted(self, query: str) -> str:
        """
        Search and return formatted results for agent consumption.
        
        Args:
            query: Search query
            
        Returns:
            Formatted string with search results
        """
        results = self.search(query)
        
        if not results:
            return "No patterns found for this query."
        
        output = []
        for i, r in enumerate(results, 1):
            output.append(f"### Pattern {i} (Score: {r['score']:.2f})")
            output.append(r['content'][:1000])
            output.append(f"Source: {r['source']}")
            output.append("")
        
        return "\n".join(output)


# =============================================================================
# Strands Agent Tool
# =============================================================================

# Global instance (initialized when KB ID is provided)
_pattern_rag: Optional[PatternRAG] = None


def init_pattern_rag(knowledge_base_id: str, region: str = "ap-southeast-1"):
    """Initialize the global PatternRAG instance."""
    global _pattern_rag
    _pattern_rag = PatternRAG(knowledge_base_id, region)
    print(f"PatternRAG initialized with KB: {knowledge_base_id}")


def search_eks_patterns(query: str) -> Dict[str, Any]:
    """
    Search EKS troubleshooting patterns in Knowledge Base.
    
    This function is designed to be used as a Strands @tool.
    
    Args:
        query: Search query describing the issue (e.g., "pod OOM killed")
        
    Returns:
        Dict with matching patterns and recommendations
    """
    if _pattern_rag is None:
        return {
            "error": "PatternRAG not initialized",
            "message": "Call init_pattern_rag(kb_id) first"
        }
    
    results = _pattern_rag.search(query)
    
    if not results:
        return {
            "found": False,
            "message": "No matching patterns found",
            "patterns": []
        }
    
    return {
        "found": True,
        "count": len(results),
        "patterns": results
    }


# =============================================================================
# Strands Tool Wrapper
# =============================================================================

def create_pattern_search_tool(knowledge_base_id: str, region: str = "ap-southeast-1"):
    """
    Create a Strands-compatible tool function for pattern search.
    
    Usage:
        from strands import Agent, tool
        
        search_tool = create_pattern_search_tool("YOUR_KB_ID")
        agent = Agent(tools=[search_tool, ...])
    """
    from strands import tool
    
    rag = PatternRAG(knowledge_base_id, region)
    
    @tool
    def search_eks_patterns(query: str) -> dict:
        """
        Search EKS troubleshooting patterns and best practices.
        
        Use this tool when diagnosing issues to find relevant patterns,
        runbooks, and recommendations based on historical knowledge.
        
        Args:
            query: Description of the issue or topic to search for
            
        Returns:
            Matching patterns with content, scores, and sources
        """
        results = rag.search(query)
        
        if not results:
            return {"found": False, "patterns": []}
        
        return {
            "found": True,
            "count": len(results),
            "patterns": [
                {
                    "content": r["content"][:800],
                    "score": r["score"],
                    "source": r["source"].split("/")[-1]
                }
                for r in results
            ]
        }
    
    return search_eks_patterns


# =============================================================================
# Test / Demo
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # Check for KB ID argument
    if len(sys.argv) < 2:
        print("Usage: python pattern_rag.py <KNOWLEDGE_BASE_ID>")
        print("\nDemo mode (no KB):")
        print("  - PatternRAG class ready")
        print("  - search_eks_patterns tool ready")
        print("  - create_pattern_search_tool ready")
        sys.exit(0)
    
    kb_id = sys.argv[1]
    print(f"Testing PatternRAG with KB: {kb_id}")
    
    # Initialize
    rag = PatternRAG(kb_id)
    
    # Test searches
    test_queries = [
        "pod OOM killed memory limit",
        "crashloopbackoff container restart",
        "image pull backoff",
        "resource limits best practices"
    ]
    
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)
        
        results = rag.search(query)
        
        if results:
            for i, r in enumerate(results, 1):
                print(f"\nResult {i} (score: {r['score']:.3f}):")
                print(f"Source: {r['source']}")
                print(f"Content: {r['content'][:200]}...")
        else:
            print("No results found")
