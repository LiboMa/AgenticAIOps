"""Router: /api/chat - Chat endpoints with Strands Agent integration."""

import os
import re
import traceback
from typing import Optional

from fastapi import APIRouter, File, UploadFile, Form

from routers.schemas import ChatRequest, ChatResponse
from routers.deps import (
    analyze_query,
    get_scanner,
    get_current_region,
    set_current_region,
    logger,
)
from routers.chat_intents import dispatch as intent_dispatch
from routers.chat_intents.ui_actions import detect_ui_action

router = APIRouter(tags=["chat"])

# =============================================================================
# Strands Agent Integration
# =============================================================================

# =============================================================================
# Multi-Model Agent Factory
# =============================================================================

# Model ID mapping: frontend model key → Bedrock model ID
BEDROCK_MODEL_MAP = {
    "claude-opus": "global.anthropic.claude-opus-4-6-v1",
    "claude-sonnet": "apac.anthropic.claude-sonnet-4-20250514-v1:0",
    "nova-pro": "amazon.nova-pro-v1:0",
    "nova-lite": "amazon.nova-lite-v1:0",
}

# Cache agents by model to avoid re-creation
_agents = {}
_agent_tools = None
_agent_system_prompt = None

def _load_agent_deps():
    """Load agent tools and system prompt (once)."""
    global _agent_tools, _agent_system_prompt
    if _agent_tools is not None:
        return True
    try:
        from strands_agent_full import (
            get_cluster_health as eks_health,
            get_cluster_info as eks_info,
            get_nodes as eks_nodes,
            get_pods as eks_pods,
            get_deployments as eks_deployments,
            get_events as eks_events,
            get_pod_logs as eks_logs,
            scale_deployment
        )
        _agent_tools = [eks_health, eks_info, eks_nodes, eks_pods,
                        eks_deployments, eks_events, eks_logs, scale_deployment]
        _agent_system_prompt = """You are an expert Cloud Operations AI assistant for AWS infrastructure.

## Your Capabilities

### AWS Resource Discovery & Scanning
- List EC2 instances, Lambda functions, S3 buckets, RDS databases
- Scan all AWS resources in a region
- Get account and region information

### CloudWatch Monitoring
- Query CloudWatch metrics (CPU, Memory, Network, etc.)
- Check CloudWatch alarms
- Search CloudWatch logs

### Operations
- Diagnose issues and provide recommendations
- Root cause analysis using knowledge base patterns
- Security posture assessment

## Response Format
When listing resources, use clear tables or lists.
When reporting issues, include severity and recommendations.
Always be concise but thorough.

## Available Commands (via Chat)
- "Scan my AWS resources" → Full cloud scan
- "List EC2 instances" → EC2 inventory
- "Show S3 buckets" → S3 bucket list
- "Check CloudWatch metrics for [instance-id]" → Metrics query
- "Analyze security status" → Security assessment

Use the available tools to gather data before making conclusions."""
        return True
    except Exception as e:
        print(f"Failed to load agent dependencies: {e}")
        return False


def get_agent(model_key: str = None):
    """Get or create a Strands Agent for the specified model.
    
    Args:
        model_key: One of 'claude-opus', 'claude-sonnet', 'nova-pro', 'nova-lite'.
                   Defaults to env AGENT_MODEL or 'claude-sonnet'.
    """
    global _agents
    
    if not _load_agent_deps():
        return None
    
    # Resolve model key
    if not model_key or model_key == "auto":
        import os
        from src.config import get_model_id, AWS_REGION
        model_name = os.environ.get("AGENT_MODEL", "haiku")
        model_id = get_model_id(model_name)
        cache_key = model_id
    else:
        from src.config import AWS_REGION
        model_id = BEDROCK_MODEL_MAP.get(model_key)
        if not model_id:
            # Fallback to default
            import os
            from src.config import get_model_id
            model_name = os.environ.get("AGENT_MODEL", "haiku")
            model_id = get_model_id(model_name)
        cache_key = model_id
    
    # Return cached agent if exists
    if cache_key in _agents:
        return _agents[cache_key]
    
    # Create new agent for this model
    try:
        from strands import Agent
        from strands.models import BedrockModel
        
        print(f"Initializing Strands Agent with model: {model_id}")
        
        model = BedrockModel(
            model_id=model_id,
            region_name=AWS_REGION
        )
        
        agent = Agent(
            model=model,
            tools=_agent_tools,
            system_prompt=_agent_system_prompt
        )
        
        _agents[cache_key] = agent
        print(f"Strands Agent initialized: {model_id}")
        return agent
    except Exception as e:
        print(f"Failed to initialize Strands Agent ({model_id}): {e}")
        return None


# =============================================================================
# Chat Endpoint (integrates with Strands Agent)
# =============================================================================

@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat with the AIOps agent. Supports multi-model selection."""
    try:
        message_lower = request.message.lower()
        model_key = request.model or "auto"
        
        # Resolve actual model for 'auto' routing (server-side)
        if model_key == "auto":
            model_used = _auto_route_model(message_lower)
        else:
            model_used = model_key
        
        # Check for AWS operation intents via dispatcher
        aws_response = await intent_dispatch(request.message, message_lower)
        if aws_response:
            return ChatResponse(
                response=aws_response,
                intent="aws_operation",
                confidence=0.9,
                model_used=model_used,
            )
        
        # Classify intent
        analysis = analyze_query(request.message)
        
        # Get agent for the selected model
        agent = get_agent(model_used)
        
        if agent:
            # Call real agent with specified model
            result = agent(request.message)
            response_text = str(result)
        else:
            # Fallback to intent-based response
            response_text = f"""Intent: {analysis['intent']} (confidence: {analysis['confidence']:.0%})

Recommended tools: {', '.join(analysis['recommended_tools'][:3])}

[Agent not available for model '{model_used}' - showing intent analysis only]"""
        
        # Check for A2UI intent (add/create widget requests)
        ui_action = detect_ui_action(request.message)
        
        return ChatResponse(
            response=response_text,
            intent=analysis['intent'],
            confidence=analysis['confidence'],
            ui_action=ui_action,
            model_used=model_used,
        )
    except Exception as e:
        import traceback
        return ChatResponse(
            response=f"Error: {str(e)}\n{traceback.format_exc()}",
            model_used=request.model or "auto",
        )


def _auto_route_model(query: str) -> str:
    """Server-side auto routing: pick best model based on query content."""
    # Simple queries → Nova Lite (cheapest)
    if query.strip() in ['help', 'commands', '帮助', '命令', 'hi', 'hello']:
        return 'nova-lite'
    
    # Health checks, list/scan → Nova Pro (fast, AWS-native)
    if any(k in query for k in ['health', 'scan', 'show', 'list', 'vpc', 'elb',
                                  'dynamodb', 'ecs', 'status', 'count']):
        return 'nova-pro'
    
    # Operations → Sonnet (reliable)
    if any(k in query for k in ['start', 'stop', 'reboot', 'failover', 'invoke',
                                  'sop run', 'execute', 'deploy', 'rollback']):
        return 'claude-sonnet'
    
    # Complex analysis → Opus (strongest reasoning)
    if any(k in query for k in ['anomaly', 'rca', 'analyze', 'diagnose', 'root cause',
                                  'why', '分析', '诊断', 'correlate', 'pattern']):
        return 'claude-opus'
    
    # Knowledge/SOP → Sonnet (balanced)
    if any(k in query for k in ['kb', 'sop', 'knowledge', 'pattern', 'semantic',
                                  'search', 'explain']):
        return 'claude-sonnet'
    
    # Default → Sonnet
    return 'claude-sonnet'


@router.post("/api/chat/upload")
async def chat_with_files(
    message: str = Form(""),
    model: str = Form("auto"),
    files: list[UploadFile] = File(default=[]),
):
    """Chat with file attachments. Reads file content and appends to the message for AI analysis."""
    try:
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file
        MAX_CONTENT_PER_FILE = 50000  # chars

        file_sections = []
        file_names = []

        for f in files:
            content_bytes = await f.read()
            if len(content_bytes) > MAX_FILE_SIZE:
                file_sections.append(f"### File: {f.filename}\n⚠️ File too large ({len(content_bytes)//1024}KB > {MAX_FILE_SIZE//1024}KB limit). Skipped.\n")
                continue

            # Try text decode
            try:
                text = content_bytes.decode("utf-8", errors="replace")
            except Exception:
                text = content_bytes.decode("latin-1", errors="replace")

            truncated = text[:MAX_CONTENT_PER_FILE]
            if len(text) > MAX_CONTENT_PER_FILE:
                truncated += f"\n... (truncated, {len(text)} total chars)"

            file_sections.append(f"### File: {f.filename} ({len(content_bytes)} bytes)\n```\n{truncated}\n```")
            file_names.append(f.filename)

        # Build combined prompt
        user_msg = message.strip() or "Please analyze the following uploaded file(s)."
        if file_sections:
            combined = f"{user_msg}\n\n--- Attached Files ---\n" + "\n\n".join(file_sections)
        else:
            combined = user_msg

        # Route to the normal chat handler
        result = await chat(ChatRequest(message=combined, model=model))

        return {
            "response": result.response,
            "intent": result.intent,
            "confidence": result.confidence,
            "model_used": result.model_used,
            "files_processed": file_names,
        }
    except Exception as e:
        import traceback
        return {"response": f"Error processing files: {str(e)}\n{traceback.format_exc()}", "model_used": model}
