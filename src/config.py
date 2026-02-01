"""
AgenticAIOps Configuration

Centralized configuration for the AIOps system.
"""

import os

# =============================================================================
# Model Configuration
# =============================================================================

# Available models (Claude 4.5 series - Global Inference Profile)
AVAILABLE_MODELS = {
    "haiku": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "opus": "global.anthropic.claude-opus-4-5-20251101-v1:0",
    # Legacy models (APAC)
    "haiku-3": "apac.anthropic.claude-3-haiku-20240307-v1:0",
    "sonnet-3": "apac.anthropic.claude-3-sonnet-20240229-v1:0",
}

# Default model (can be overridden by env var)
DEFAULT_MODEL = os.environ.get("AGENT_MODEL", "haiku")

def get_model_id(model_name: str = None) -> str:
    """
    Get the full model ID for a given model name.
    
    Args:
        model_name: Short name (haiku, sonnet, opus) or full model ID
        
    Returns:
        Full Bedrock model ID
    """
    name = model_name or DEFAULT_MODEL
    
    # If it's already a full model ID, return it
    if name.startswith("anthropic.") or name.startswith("apac."):
        return name
    
    # Look up short name
    return AVAILABLE_MODELS.get(name.lower(), AVAILABLE_MODELS["haiku"])


# =============================================================================
# EKS Configuration
# =============================================================================

CLUSTER_NAME = os.environ.get("EKS_CLUSTER_NAME", "testing-cluster")
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")


# =============================================================================
# Knowledge Base Configuration
# =============================================================================

KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "")
KB_S3_BUCKET = os.environ.get("KB_S3_BUCKET", "agentic-aiops-kb-1769960769")


# =============================================================================
# API Configuration
# =============================================================================

API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))


# Print configuration on import (for debugging)
if __name__ == "__main__":
    print("AgenticAIOps Configuration")
    print("=" * 50)
    print(f"Default Model: {DEFAULT_MODEL} -> {get_model_id()}")
    print(f"Cluster: {CLUSTER_NAME}")
    print(f"Region: {AWS_REGION}")
    print(f"KB ID: {KNOWLEDGE_BASE_ID or '(not set)'}")
    print()
    print("Available Models:")
    for name, model_id in AVAILABLE_MODELS.items():
        print(f"  {name}: {model_id}")
