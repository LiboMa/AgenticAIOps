"""Router: /api/models - Available AI models."""

from fastapi import APIRouter

router = APIRouter(tags=["models"])


@router.get("/api/models")
async def list_models():
    """List available AI models for the chat interface."""
    return {
        "models": [
            {
                "id": "auto",
                "name": "Auto Router",
                "description": "Smart routing based on query type",
                "provider": "system",
                "cost_tier": "optimal",
            },
            {
                "id": "claude-opus",
                "name": "Claude Opus 4",
                "description": "Best for complex analysis & RCA",
                "provider": "bedrock",
                "model_id": "anthropic.claude-opus-4-6-v1",
                "cost_tier": "high",
            },
            {
                "id": "claude-sonnet",
                "name": "Claude Sonnet 4",
                "description": "Balanced performance & cost",
                "provider": "bedrock",
                "model_id": "anthropic.claude-sonnet-4-20250514-v1:0",
                "cost_tier": "medium",
            },
            {
                "id": "nova-pro",
                "name": "Amazon Nova Pro",
                "description": "AWS native, good for operations",
                "provider": "bedrock",
                "model_id": "amazon.nova-pro-v1:0",
                "cost_tier": "low",
            },
            {
                "id": "nova-lite",
                "name": "Amazon Nova Lite",
                "description": "Fast & cheap for simple queries",
                "provider": "bedrock",
                "model_id": "amazon.nova-lite-v1:0",
                "cost_tier": "very-low",
            },
        ]
    }
