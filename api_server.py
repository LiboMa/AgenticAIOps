#!/usr/bin/env python3
"""
AgenticAIOps - Backend API Server

FastAPI server providing REST endpoints for the React dashboard.
"""

import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# AWS Scanner imports (early import for chat handler)
try:
    from src.aws_scanner import get_scanner, AWSCloudScanner
    AWS_SCANNER_AVAILABLE = True
    print("✅ AWS Scanner loaded successfully")
except ImportError as e:
    AWS_SCANNER_AVAILABLE = False
    print(f"❌ AWS Scanner not available: {e}")
    def get_scanner(region): return None

# Global state for scanner
_current_region = "ap-southeast-1"

# Import our modules (handle import errors gracefully)
K8S_TOOLS_AVAILABLE = False

try:
    from src.kubectl_wrapper import (
        get_pods, get_deployments, get_nodes, get_events,
        get_pod_logs, describe_pod, get_cluster_info, get_cluster_health
    )
    K8S_TOOLS_AVAILABLE = True
    print("kubectl wrapper loaded successfully")
except Exception as e:
    print(f"Warning: kubectl wrapper not available: {e}")
    # Define mock functions
    def get_pods(ns=None): return {"pods": []}
    def get_deployments(ns=None): return {"deployments": []}
    def get_nodes(): return {"nodes": []}
    def get_events(ns=None): return {"events": []}
    def get_pod_logs(ns, name, lines=100): return {"logs": ""}
    def describe_pod(ns, name): return {}
    def get_cluster_health(): return {"status": "unknown"}
    def get_cluster_info(): return {"name": "testing-cluster", "version": "1.32", "status": "ACTIVE", "region": "ap-southeast-1"}

def get_hpa(ns=None): return {"hpas": []}

from src.intent_classifier import analyze_query
from src.multi_agent_voting import extract_diagnosis, simple_vote

# Import plugin system
from src.plugins import PluginRegistry, PluginConfig
from src.plugins.eks_plugin import EKSPlugin
from src.plugins.ec2_plugin import EC2Plugin
from src.plugins.lambda_plugin import LambdaPlugin
from src.plugins.hpc_plugin import HPCPlugin

# Import ACI for real telemetry data
try:
    from src.aci import AgentCloudInterface
    ACI_AVAILABLE = True
    print("ACI (Agent-Cloud Interface) loaded successfully")
except Exception as e:
    print(f"Warning: ACI not available: {e}")
    ACI_AVAILABLE = False

# Import Voting for diagnosis
try:
    from src.voting import MultiAgentVoting, TaskType
    VOTING_AVAILABLE = True
    print("Multi-Agent Voting loaded successfully")
except Exception as e:
    print(f"Warning: Voting not available: {e}")
    VOTING_AVAILABLE = False

# Import Issue Manager
try:
    from src.issues import IssueManager
    ISSUES_AVAILABLE = True
    _issue_manager = None
    print("Issue Manager loaded successfully")
except Exception as e:
    print(f"Warning: Issue Manager not available: {e}")
    ISSUES_AVAILABLE = False

# Import Runbook Executor
try:
    from src.runbook import RunbookExecutor, RunbookLoader
    RUNBOOK_AVAILABLE = True
    _runbook_executor = None
    print("Runbook Executor loaded successfully")
except Exception as e:
    print(f"Warning: Runbook Executor not available: {e}")
    RUNBOOK_AVAILABLE = False

# Import Health Checker
try:
    from src.health import HealthChecker, HealthCheckScheduler, HealthCheckConfig
    HEALTH_AVAILABLE = True
    _health_scheduler = None
    print("Health Checker loaded successfully")
except Exception as e:
    print(f"Warning: Health Checker not available: {e}")
    HEALTH_AVAILABLE = False

app = FastAPI(
    title="AgenticAIOps API",
    description="Backend API for EKS AIOps Dashboard",
    version="1.0.0"
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Available Models API
# =============================================================================

@app.get("/api/models")
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
                "model_id": "anthropic.claude-sonnet-4-6-v1",
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

# Request/Response models
class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None  # Model selection: auto, claude-opus, claude-sonnet, nova-pro, nova-lite

class ChatResponse(BaseModel):
    response: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    ui_action: Optional[dict] = None  # A2UI action if applicable
    model_used: Optional[str] = None  # Which model was actually used

# A2UI Widget Request/Response
class A2UIWidgetConfig(BaseModel):
    id: Optional[str] = None
    type: str
    config: dict
    span: Optional[int] = 8

class A2UIGenerateRequest(BaseModel):
    prompt: str
    
class A2UIGenerateResponse(BaseModel):
    success: bool
    widget: Optional[A2UIWidgetConfig] = None
    message: str


# =============================================================================
# Strands Agent Integration
# =============================================================================

# =============================================================================
# Multi-Model Agent Factory
# =============================================================================

# Model ID mapping: frontend model key → Bedrock model ID
BEDROCK_MODEL_MAP = {
    "claude-opus": "anthropic.claude-opus-4-6-v1",
    "claude-sonnet": "anthropic.claude-sonnet-4-6-v1",
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

@app.post("/api/chat", response_model=ChatResponse)
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
        
        # Check for AWS operation intents
        aws_response = await handle_aws_chat_intent(request.message)
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


async def handle_aws_chat_intent(message: str) -> Optional[str]:
    """Handle AWS-related chat intents directly."""
    message_lower = message.lower()
    
    scanner = get_scanner(_current_region)
    
    # Import AWS Ops for health/metrics/logs
    try:
        from src.aws_ops import get_aws_ops
        ops = get_aws_ops(_current_region)
    except ImportError:
        ops = None
    
    # ===========================================
    # Help Command
    # ===========================================
    if any(kw in message_lower for kw in ['help', 'commands', '帮助', '命令']):
        return f"""📚 **AgenticAIOps Chat Commands**

**🔍 资源查询:**
| Command | Description |
|---------|-------------|
| `ec2` | 列出 EC2 实例 |
| `lambda` | 列出 Lambda 函数 |
| `s3` | 列出 S3 存储桶 |
| `rds` | 列出 RDS 数据库 |
| `dynamodb` | 列出 DynamoDB 表 |
| `ecs` | 列出 ECS 集群 |
| `elasticache` | 列出 ElastiCache 集群 |
| `vpc` | 列出 VPCs |
| `elb` | 列出负载均衡器 |
| `scan` | 扫描所有资源 |

**🏥 健康检查:**
| Command | Description |
|---------|-------------|
| `ec2 health` | EC2 健康检查 |
| `rds health` | RDS 健康检查 |
| `lambda health` | Lambda 健康检查 |
| `s3 health` | S3 健康检查 |
| `dynamodb health` | DynamoDB 健康检查 |
| `ecs health` | ECS 健康检查 |
| `elasticache health` | ElastiCache 健康检查 |
| `vpc health` | VPC 健康检查 |
| `elb health` | ELB 健康检查 |
| `route53 health` | Route53 健康检查 |
| `health` | 全服务健康检查 |
| `anomaly` | 异常检测 |

**⚙️ EC2 操作:**
| Command | Description |
|---------|-------------|
| `ec2 start i-xxx` | 启动实例 |
| `ec2 stop i-xxx` | 停止实例 |
| `ec2 reboot i-xxx` | 重启实例 |

**⚙️ RDS 操作:**
| Command | Description |
|---------|-------------|
| `rds reboot xxx` | 重启 RDS 实例 |
| `rds failover xxx` | RDS 故障转移 (Multi-AZ) |

**⚙️ Lambda 操作:**
| Command | Description |
|---------|-------------|
| `lambda invoke xxx` | 调用 Lambda 函数 |

**📊 监控:**
| Command | Description |
|---------|-------------|
| `ec2 metrics i-xxx` | EC2 指标 |
| `rds metrics xxx` | RDS 指标 |
| `lambda logs xxx` | Lambda 日志 |

**🔔 告警通知:**
| Command | Description |
|---------|-------------|
| `notification status` | 查看通知配置状态 |
| `test notification` | 发送测试通知 |
| `send alert <msg>` | 发送自定义告警 |

**🔧 其他:**
| Command | Description |
|---------|-------------|
| `account` | AWS 账号信息 |
| `region us-east-1` | 切换 Region |

当前 Region: **{_current_region}** | 支持服务: **13**"""
    
    # ===========================================
    # Health Check Commands
    # ===========================================
    
    # EC2 Health Check
    if any(kw in message_lower for kw in ['ec2 health', 'ec2 健康', 'check ec2', '检查 ec2', 'ec2 status']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.ec2_health_check()
            response = f"""🏥 **EC2 健康检查** (Region: {_current_region})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Name | ID | State | Health | CPU | Issues |
|------|----| ------|--------|-----|--------|"""
            
            for inst in health.get('instances', [])[:10]:
                health_icon = "✅" if inst['health'] == 'healthy' else "⚠️" if inst['health'] == 'warning' else "❌"
                issues_str = ", ".join(inst.get('issues', [])[:2]) or "None"
                response += f"\n| {inst['name'][:15]} | {inst['id']} | {inst['state']} | {health_icon} | {inst.get('cpu_avg', 0):.1f}% | {issues_str[:20]} |"
            
            if health.get('issues'):
                response += f"\n\n**发现问题 ({len(health['issues'])}):**"
                for issue in health['issues'][:5]:
                    response += f"\n- {issue['resource']}: {issue['issue']}"
            
            return response
        except Exception as e:
            return f"❌ EC2 健康检查失败: {str(e)}"
    
    # RDS Health Check
    if any(kw in message_lower for kw in ['rds health', 'rds 健康', 'check rds', '检查 rds', 'database health', '数据库健康']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.rds_health_check()
            response = f"""🏥 **RDS 健康检查** (Region: {_current_region})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| ID | Engine | Status | Health | CPU | Connections | Issues |
|----|--------|--------|--------|-----|-------------|--------|"""
            
            for db in health.get('databases', []):
                health_icon = "✅" if db['health'] == 'healthy' else "⚠️" if db['health'] == 'warning' else "❌"
                issues_str = ", ".join(db.get('issues', [])[:2]) or "None"
                response += f"\n| {db['id']} | {db['engine'][:15]} | {db['status']} | {health_icon} | {db.get('cpu_avg', 0):.1f}% | {db.get('connections', 0):.0f} | {issues_str[:15]} |"
            
            if health.get('issues'):
                response += f"\n\n**发现问题 ({len(health['issues'])}):**"
                for issue in health['issues'][:5]:
                    response += f"\n- {issue['resource']}: {issue['issue']}"
            
            return response
        except Exception as e:
            return f"❌ RDS 健康检查失败: {str(e)}"
    
    # RDS Reboot
    if any(kw in message_lower for kw in ['rds reboot', 'reboot rds', 'restart rds', '重启 rds', '重启数据库']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        import re
        # Extract DB identifier (usually lowercase with hyphens)
        match = re.search(r'([a-z0-9][a-z0-9-]*[a-z0-9])', message_lower)
        if not match or match.group(1) in ['rds', 'reboot', 'restart']:
            return """⚠️ **请提供 DB Identifier**

用法: `rds reboot mydb-instance`

示例:
- `rds reboot production-mysql`
- `restart rds test-postgres`"""
        
        db_id = match.group(1)
        try:
            result = ops.rds_operations(db_id, 'reboot')
            if result.get('success'):
                return f"""🔄 **RDS Reboot 命令已发送**

| 项目 | 值 |
|------|-----|
| DB ID | `{db_id}` |
| Action | Reboot |
| Status | {result.get('status', 'rebooting')} |

⏳ 数据库重启需要几分钟，请稍后检查状态。"""
            else:
                return f"❌ 重启失败: {result.get('error')}"
        except Exception as e:
            return f"❌ RDS 重启失败: {str(e)}"
    
    # RDS Failover
    if any(kw in message_lower for kw in ['rds failover', 'failover rds', '故障转移']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        import re
        match = re.search(r'([a-z0-9][a-z0-9-]*[a-z0-9])', message_lower)
        if not match or match.group(1) in ['rds', 'failover']:
            return """⚠️ **请提供 DB Identifier**

用法: `rds failover mydb-instance`

注意: 仅适用于 Multi-AZ 部署"""
        
        db_id = match.group(1)
        try:
            result = ops.rds_operations(db_id, 'failover')
            if result.get('success'):
                return f"""⚠️ **RDS Failover 命令已发送**

| 项目 | 值 |
|------|-----|
| DB ID | `{db_id}` |
| Action | Failover |
| Status | {result.get('status', 'failing-over')} |

⏳ 故障转移进行中..."""
            else:
                return f"❌ Failover 失败: {result.get('error')}"
        except Exception as e:
            return f"❌ RDS Failover 失败: {str(e)}"
    
    # Lambda Health Check
    if any(kw in message_lower for kw in ['lambda health', 'lambda 健康', 'check lambda', '检查 lambda', 'function health']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.lambda_health_check()
            response = f"""🏥 **Lambda 健康检查** (Region: {_current_region})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Function | Health | Invocations | Errors | Error Rate | Throttles |
|----------|--------|-------------|--------|------------|-----------|"""
            
            for func in health.get('functions', [])[:10]:
                health_icon = "✅" if func['health'] == 'healthy' else "⚠️" if func['health'] == 'warning' else "❌"
                response += f"\n| {func['name'][:25]} | {health_icon} | {func.get('invocations', 0):.0f} | {func.get('errors', 0):.0f} | {func.get('error_rate', 0):.1f}% | {func.get('throttles', 0):.0f} |"
            
            if health.get('issues'):
                response += f"\n\n**发现问题 ({len(health['issues'])}):**"
                for issue in health['issues'][:5]:
                    response += f"\n- {issue['resource']}: {issue['issue']}"
            
            return response
        except Exception as e:
            return f"❌ Lambda 健康检查失败: {str(e)}"
    
    # Lambda Invoke
    if any(kw in message_lower for kw in ['lambda invoke', 'invoke lambda', '调用 lambda', '执行 lambda']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        import re
        # Extract function name
        match = re.search(r'invoke\s+([a-zA-Z0-9_-]+)|([a-zA-Z0-9_-]+)\s+invoke', message)
        if not match:
            return """⚠️ **请提供 Function Name**

用法: `lambda invoke my-function`

示例:
- `lambda invoke hello-world`
- `invoke lambda process-data`"""
        
        function_name = match.group(1) or match.group(2)
        if function_name.lower() in ['lambda', 'invoke']:
            return "⚠️ 请提供函数名称"
        
        try:
            result = ops.lambda_invoke(function_name)
            if result.get('success'):
                response_preview = str(result.get('response', ''))[:200]
                return f"""✅ **Lambda Invoke 成功**

| 项目 | 值 |
|------|-----|
| Function | `{function_name}` |
| Status Code | {result.get('status_code', 'N/A')} |
| Type | {result.get('invocation_type', 'sync')} |

**Response Preview:**
```
{response_preview}...
```"""
            else:
                return f"❌ 调用失败: {result.get('error')}"
        except Exception as e:
            return f"❌ Lambda Invoke 失败: {str(e)}"
    
    # S3 Health Check
    if any(kw in message_lower for kw in ['s3 health', 's3 健康', 'check s3', '检查 s3', 'bucket health', 's3 security']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.s3_health_check()
            response = f"""🏥 **S3 健康检查**

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}
**公开桶数量:** {health.get('public_buckets', 0)} {'⚠️' if health.get('public_buckets', 0) > 0 else ''}

| Bucket | Public | Encryption | Versioning | Issues |
|--------|--------|------------|------------|--------|"""
            
            for bucket in health.get('buckets', [])[:15]:
                public_icon = "⚠️ Yes" if bucket['public'] else "No"
                issues_str = ", ".join(bucket.get('issues', [])) or "None"
                response += f"\n| {bucket['name'][:30]} | {public_icon} | {bucket.get('encryption', 'N/A')} | {bucket.get('versioning', 'N/A')} | {issues_str[:15]} |"
            
            return response
        except Exception as e:
            return f"❌ S3 健康检查失败: {str(e)}"
    
    # ===========================================
    # Anomaly Detection
    # ===========================================
    
    if any(kw in message_lower for kw in ['anomaly', '异常', 'detect', '检测问题', '发现问题']):
        # Enhanced anomaly detection with Event Correlator
        try:
            import asyncio
            from src.event_correlator import get_correlator
            
            correlator = get_correlator(_current_region)
            
            # Parse optional service filter
            services = None
            for svc in ['ec2', 'rds', 'lambda']:
                if svc in message_lower:
                    services = [svc]
                    break
            
            # Run async collection
            loop = asyncio.new_event_loop()
            try:
                event = loop.run_until_complete(
                    correlator.collect(services=services, lookback_minutes=60)
                )
            finally:
                loop.close()
            
            return event.summary()
        except Exception as e:
            logger.warning(f"Event correlator failed, falling back: {e}")
            # Fallback to original anomaly detection
            if not ops:
                return "❌ AWS Ops module not available"
        try:
            response = f"""🔍 **异常检测报告** (Region: {_current_region})

"""
            total_anomalies = []
            
            # Check each service
            for service in ['ec2', 'rds', 'lambda']:
                anomalies = ops.detect_anomalies(service)
                if anomalies.get('anomalies'):
                    total_anomalies.extend(anomalies['anomalies'])
            
            if total_anomalies:
                response += f"**发现 {len(total_anomalies)} 个异常:**\n\n"
                response += "| 服务 | 资源 | 类型 | 值 | 严重性 |\n"
                response += "|------|------|------|-----|--------|\n"
                
                for a in total_anomalies[:10]:
                    severity_icon = "🔴" if a['severity'] == 'critical' else "🟠" if a['severity'] == 'high' else "🟡"
                    response += f"| {a.get('type', 'N/A').split('_')[0]} | {a['resource'][:20]} | {a['type']} | {a.get('value', 'N/A')} | {severity_icon} {a['severity']} |\n"
            else:
                response += "✅ **未发现异常！所有服务运行正常。**"
            
            return response
        except Exception as e:
            return f"❌ 异常检测失败: {str(e)}"
    
    # ===========================================
    # Metrics Commands
    # ===========================================
    
    # EC2 Metrics
    if any(kw in message_lower for kw in ['ec2 metrics', 'ec2 指标', 'ec2 监控']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        # Extract instance ID if provided
        import re
        instance_match = re.search(r'i-[a-f0-9]+', message)
        
        if instance_match:
            instance_id = instance_match.group()
            try:
                metrics = ops.ec2_get_metrics(instance_id)
                response = f"""📊 **EC2 Metrics** - {instance_id}

| Metric | Average | Max | Min |
|--------|---------|-----|-----|"""
                
                for metric_name, data in metrics.get('metrics', {}).items():
                    if data:
                        response += f"\n| {metric_name} | {data.get('avg', 0):.2f} | {data.get('max', 0):.2f} | {data.get('min', 0):.2f} |"
                
                return response
            except Exception as e:
                return f"❌ 获取 EC2 指标失败: {str(e)}"
        else:
            return "请指定实例 ID，例如: `EC2 metrics i-0123456789abcdef0`"
    
    # RDS Metrics
    if any(kw in message_lower for kw in ['rds metrics', 'rds 指标', 'rds 监控', 'database metrics']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        # Extract DB ID if provided (simplified)
        words = message.split()
        db_id = None
        for i, word in enumerate(words):
            if word.lower() in ['metrics', 'for', '指标']:
                if i + 1 < len(words):
                    db_id = words[i + 1]
                    break
        
        if db_id and not db_id.startswith(('metrics', 'for')):
            try:
                metrics = ops.rds_get_metrics(db_id)
                response = f"""📊 **RDS Metrics** - {db_id}

| Metric | Average | Max |
|--------|---------|-----|"""
                
                for metric_name, data in metrics.get('metrics', {}).items():
                    if data:
                        value = data.get('avg', 0)
                        # Format storage in GB
                        if 'Storage' in metric_name or 'Memory' in metric_name:
                            value = value / (1024**3)
                            response += f"\n| {metric_name} | {value:.2f} GB | {data.get('max', 0) / (1024**3):.2f} GB |"
                        else:
                            response += f"\n| {metric_name} | {value:.2f} | {data.get('max', 0):.2f} |"
                
                return response
            except Exception as e:
                return f"❌ 获取 RDS 指标失败: {str(e)}"
        else:
            # Show all RDS metrics summary
            health = ops.rds_health_check()
            response = f"""📊 **RDS Metrics Summary** (Region: {_current_region})

| Database | CPU Avg | CPU Max | Connections |
|----------|---------|---------|-------------|"""
            
            for db in health.get('databases', []):
                response += f"\n| {db['id']} | {db.get('cpu_avg', 0):.1f}% | {db.get('cpu_max', 0):.1f}% | {db.get('connections', 0):.0f} |"
            
            response += "\n\n💡 查看详细指标: `RDS metrics <db-id>`"
            return response
    
    # ===========================================
    # Logs Commands
    # ===========================================
    
    # Lambda Logs
    if any(kw in message_lower for kw in ['lambda logs', 'lambda 日志', 'function logs']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        # Extract function name
        words = message.split()
        func_name = None
        for i, word in enumerate(words):
            if word.lower() in ['logs', 'log', '日志', 'for']:
                if i + 1 < len(words) and words[i + 1].lower() not in ['logs', 'log', '日志', 'for']:
                    func_name = words[i + 1]
                    break
        
        if func_name:
            try:
                filter_errors = 'error' in message_lower
                logs = ops.lambda_get_logs(func_name, hours=1, filter_errors=filter_errors)
                
                response = f"""📜 **Lambda Logs** - {func_name}
{'(Filtered: ERRORS only)' if filter_errors else ''}

"""
                events = logs.get('events', [])
                if events:
                    for event in events[:20]:
                        response += f"**{event['timestamp']}**\n```\n{event['message'][:200]}\n```\n\n"
                else:
                    response += "📭 没有找到日志记录"
                
                return response
            except Exception as e:
                return f"❌ 获取 Lambda 日志失败: {str(e)}"
        else:
            return "请指定函数名，例如: `Lambda logs my-function` 或 `Lambda error logs my-function`"
    
    # ===========================================
    # General Health Check (all services)
    # ===========================================
    
    if any(kw in message_lower for kw in ['health', '健康', '状态检查', 'status check', '诊断', 'diagnose']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            response = f"""🏥 **AWS 服务健康状态** (Region: {_current_region})

"""
            all_issues = []
            
            # EC2 Health
            ec2_health = ops.ec2_health_check()
            ec2_status = "✅" if ec2_health['overall_status'] == 'healthy' else "⚠️" if ec2_health['overall_status'] == 'warning' else "❌"
            response += f"**EC2:** {ec2_status} {len(ec2_health.get('instances', []))} instances | Issues: {len(ec2_health.get('issues', []))}\n"
            all_issues.extend(ec2_health.get('issues', []))
            
            # RDS Health
            rds_health = ops.rds_health_check()
            rds_status = "✅" if rds_health['overall_status'] == 'healthy' else "⚠️" if rds_health['overall_status'] == 'warning' else "❌"
            response += f"**RDS:** {rds_status} {len(rds_health.get('databases', []))} databases | Issues: {len(rds_health.get('issues', []))}\n"
            all_issues.extend(rds_health.get('issues', []))
            
            # Lambda Health
            lambda_health = ops.lambda_health_check()
            lambda_status = "✅" if lambda_health['overall_status'] == 'healthy' else "⚠️" if lambda_health['overall_status'] == 'warning' else "❌"
            response += f"**Lambda:** {lambda_status} {len(lambda_health.get('functions', []))} functions | Issues: {len(lambda_health.get('issues', []))}\n"
            all_issues.extend(lambda_health.get('issues', []))
            
            # S3 Health
            s3_health = ops.s3_health_check()
            s3_status = "✅" if s3_health['overall_status'] == 'healthy' else "⚠️"
            response += f"**S3:** {s3_status} {len(s3_health.get('buckets', []))} buckets | Public: {s3_health.get('public_buckets', 0)}\n"
            all_issues.extend(s3_health.get('issues', []))
            
            if all_issues:
                response += f"\n---\n**⚠️ 发现 {len(all_issues)} 个问题:**\n"
                for issue in all_issues[:10]:
                    response += f"- {issue['resource']}: {issue['issue']}\n"
            else:
                response += "\n---\n✅ **所有服务运行正常！**"
            
            return response
        except Exception as e:
            return f"❌ 健康检查失败: {str(e)}"
    
    # Scan all resources
    if any(kw in message_lower for kw in ['scan', '扫描', 'all resources', '所有资源']):
        try:
            results = scanner.scan_all_resources()
            
            response = f"""📊 **AWS 资源扫描报告**
Account: {results['account'].get('account_id', 'N/A')}
Region: {results['region']}

| 服务 | 数量 | 状态 |
|------|------|------|"""
            
            for service, data in results.get('services', {}).items():
                if 'error' not in data:
                    count = data.get('count', 0)
                    status = ""
                    if 'status' in data:
                        status = f"{data['status'].get('running', 0)} running"
                    elif 'public_count' in data and data['public_count'] > 0:
                        status = f"⚠️ {data['public_count']} public"
                    else:
                        status = "OK"
                    response += f"\n| {service.upper()} | {count} | {status} |"
            
            issues = results.get('summary', {}).get('issues_found', [])
            if issues:
                response += f"\n\n⚠️ **发现 {len(issues)} 个潜在问题**"
                for issue in issues[:3]:
                    response += f"\n- [{issue['severity'].upper()}] {issue['service']}: {issue['type']}"
            
            return response
        except Exception as e:
            return f"❌ 扫描失败: {str(e)}"
    
    # ===========================================
    # EC2 Operations (Start/Stop/Reboot)
    # ===========================================
    
    # EC2 Start
    if any(kw in message_lower for kw in ['ec2 start', 'start ec2', 'start instance', '启动实例', '启动 ec2']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        # Extract instance ID
        import re
        match = re.search(r'(i-[a-f0-9]+)', message)
        if not match:
            return """⚠️ **请提供 Instance ID**

用法: `ec2 start i-xxxxxxxxx`

示例:
- `ec2 start i-0abc123def456`
- `start instance i-0abc123def456`"""
        
        instance_id = match.group(1)
        try:
            result = ops.ec2_operations(instance_id, 'start')
            if result.get('success'):
                return f"""✅ **EC2 Start 命令已发送**

| 项目 | 值 |
|------|-----|
| Instance ID | `{instance_id}` |
| Action | Start |
| Status | 启动中... |

⏳ 实例启动需要 1-2 分钟，请稍后使用 `ec2 health {instance_id}` 检查状态。"""
            else:
                return f"❌ 启动失败: {result.get('error')}"
        except Exception as e:
            return f"❌ 启动 EC2 失败: {str(e)}"
    
    # EC2 Stop
    if any(kw in message_lower for kw in ['ec2 stop', 'stop ec2', 'stop instance', '停止实例', '停止 ec2']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        import re
        match = re.search(r'(i-[a-f0-9]+)', message)
        if not match:
            return """⚠️ **请提供 Instance ID**

用法: `ec2 stop i-xxxxxxxxx`

示例:
- `ec2 stop i-0abc123def456`
- `stop instance i-0abc123def456`"""
        
        instance_id = match.group(1)
        try:
            result = ops.ec2_operations(instance_id, 'stop')
            if result.get('success'):
                return f"""🛑 **EC2 Stop 命令已发送**

| 项目 | 值 |
|------|-----|
| Instance ID | `{instance_id}` |
| Action | Stop |
| Status | 停止中... |

⏳ 实例停止需要 30-60 秒。"""
            else:
                return f"❌ 停止失败: {result.get('error')}"
        except Exception as e:
            return f"❌ 停止 EC2 失败: {str(e)}"
    
    # EC2 Reboot
    if any(kw in message_lower for kw in ['ec2 reboot', 'reboot ec2', 'reboot instance', '重启实例', '重启 ec2']):
        if not ops:
            return "❌ AWS Ops module not available"
        
        import re
        match = re.search(r'(i-[a-f0-9]+)', message)
        if not match:
            return """⚠️ **请提供 Instance ID**

用法: `ec2 reboot i-xxxxxxxxx`

示例:
- `ec2 reboot i-0abc123def456`
- `reboot instance i-0abc123def456`"""
        
        instance_id = match.group(1)
        try:
            result = ops.ec2_operations(instance_id, 'reboot')
            if result.get('success'):
                return f"""🔄 **EC2 Reboot 命令已发送**

| 项目 | 值 |
|------|-----|
| Instance ID | `{instance_id}` |
| Action | Reboot |
| Status | 重启中... |

⏳ 实例重启需要 1-2 分钟。"""
            else:
                return f"❌ 重启失败: {result.get('error')}"
        except Exception as e:
            return f"❌ 重启 EC2 失败: {str(e)}"
    
    # List EC2 instances (skip if SOP command)
    if any(kw in message_lower for kw in ['ec2', 'instance', '实例']) and not any(sop_kw in message_lower for sop_kw in ['sop list', 'sop show', 'sop suggest', 'sop run', 'sop 列表', 'sop 详情', 'sop 推荐', 'sop 执行']):
        try:
            data = scanner._scan_ec2()
            response = f"""🖥️ **EC2 Instances** (Region: {_current_region})

Total: {data['count']} | Running: {data['status']['running']} | Stopped: {data['status']['stopped']}

| Name | ID | Type | State | IP |
|------|----|----- |-------|-----|"""
            
            for inst in data.get('instances', [])[:10]:
                response += f"\n| {inst['name'][:20]} | {inst['id']} | {inst['type']} | {inst['state']} | {inst.get('private_ip', 'N/A')} |"
            
            if data['count'] > 10:
                response += f"\n\n... 还有 {data['count'] - 10} 个实例"
            
            return response
        except Exception as e:
            return f"❌ 获取 EC2 失败: {str(e)}"
    
    # List Lambda functions
    if any(kw in message_lower for kw in ['lambda', '函数', 'function']):
        try:
            data = scanner._scan_lambda()
            response = f"""⚡ **Lambda Functions** (Region: {_current_region})

Total: {data['count']}

| Function | Runtime | Memory | Timeout |
|----------|---------|--------|---------|"""
            
            for func in data.get('functions', [])[:10]:
                response += f"\n| {func['name'][:30]} | {func['runtime']} | {func['memory']}MB | {func['timeout']}s |"
            
            return response
        except Exception as e:
            return f"❌ 获取 Lambda 失败: {str(e)}"
    
    # List S3 buckets
    if any(kw in message_lower for kw in ['s3', 'bucket', '桶', '存储']):
        try:
            data = scanner._scan_s3()
            response = f"""📁 **S3 Buckets**

Total: {data['count']} | Public: {data.get('public_count', 0)} ⚠️

| Bucket Name | Public |
|-------------|--------|"""
            
            for bucket in data.get('buckets', [])[:15]:
                public_tag = "⚠️ Yes" if bucket.get('public') else "No"
                response += f"\n| {bucket['name'][:40]} | {public_tag} |"
            
            if data['count'] > 15:
                response += f"\n\n... 还有 {data['count'] - 15} 个桶"
            
            return response
        except Exception as e:
            return f"❌ 获取 S3 失败: {str(e)}"
    
    # List RDS instances
    if any(kw in message_lower for kw in ['rds', 'database', '数据库']):
        try:
            data = scanner._scan_rds()
            response = f"""🗄️ **RDS Databases** (Region: {_current_region})

Total: {data['count']}

| ID | Engine | Class | Status | Public |
|----|--------|-------|--------|--------|"""
            
            for db in data.get('instances', []):
                public_tag = "⚠️ Yes" if db.get('public') else "No"
                response += f"\n| {db['id']} | {db['engine']} | {db['class']} | {db['status']} | {public_tag} |"
            
            return response
        except Exception as e:
            return f"❌ 获取 RDS 失败: {str(e)}"
    
    # ===========================================
    # Networking Commands (VPC, ELB, Route53)
    # ===========================================
    
    # VPC Health Check
    if any(kw in message_lower for kw in ['vpc health', 'vpc 健康', 'check vpc']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.vpc_health_check()
            response = f"""🏥 **VPC 健康检查** (Region: {_current_region})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Name | ID | State | Subnets | IGW | NAT | Issues |
|------|----| ------|---------|-----|-----|--------|"""
            
            for vpc in health.get('vpcs', [])[:10]:
                health_icon = "✅" if vpc['health'] == 'healthy' else "⚠️"
                igw = "✅" if vpc['has_igw'] else "❌"
                issues_str = ", ".join(vpc.get('issues', [])[:2]) or "None"
                response += f"\n| {vpc['name'][:15]} | {vpc['id']} | {vpc['state']} | {vpc['subnets_available']}/{vpc['subnets_count']} | {igw} | {vpc['nat_gateways']} | {issues_str[:15]} |"
            
            return response
        except Exception as e:
            return f"❌ VPC 健康检查失败: {str(e)}"
    
    # List VPCs
    if any(kw in message_lower for kw in ['vpc', '网络', 'network']):
        try:
            data = scanner._scan_vpc()
            response = f"""🌐 **VPCs** (Region: {_current_region})

Total: {data['count']}

| Name | ID | CIDR | State | Default |
|------|----| -----|-------|---------|"""
            
            for vpc in data.get('vpcs', []):
                default_tag = "✅" if vpc.get('is_default') else ""
                response += f"\n| {vpc['name'][:20]} | {vpc['id']} | {vpc['cidr']} | {vpc['state']} | {default_tag} |"
            
            return response
        except Exception as e:
            return f"❌ 获取 VPC 失败: {str(e)}"
    
    # ELB Health Check
    if any(kw in message_lower for kw in ['elb health', 'lb health', 'load balancer health']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.elb_health_check()
            response = f"""🏥 **ELB 健康检查** (Region: {_current_region})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Name | Type | State | Targets | Unhealthy | Issues |
|------|------|-------|---------|-----------|--------|"""
            
            for lb in health.get('load_balancers', [])[:10]:
                health_icon = "✅" if lb['health'] == 'healthy' else "⚠️"
                issues_str = ", ".join(lb.get('issues', [])[:2]) or "None"
                response += f"\n| {lb['name'][:20]} | {lb['type']} | {lb['state']} | {lb['total_targets']} | {lb['unhealthy_targets']} | {issues_str[:15]} |"
            
            return response
        except Exception as e:
            return f"❌ ELB 健康检查失败: {str(e)}"
    
    # List ELBs
    if any(kw in message_lower for kw in ['elb', 'load balancer', '负载均衡']):
        try:
            data = scanner._scan_elb()
            response = f"""⚖️ **Load Balancers** (Region: {_current_region})

Total: {data['count']} | Active: {data.get('status', {}).get('active', 0)}

| Name | Type | Scheme | State | DNS |
|------|------|--------|-------|-----|"""
            
            for lb in data.get('load_balancers', [])[:10]:
                response += f"\n| {lb['name'][:20]} | {lb['type']} | {lb['scheme']} | {lb['state']} | {lb['dns_name'][:30]}... |"
            
            return response
        except Exception as e:
            return f"❌ 获取 ELB 失败: {str(e)}"
    
    # Route53 Health Check
    if any(kw in message_lower for kw in ['route53 health', 'dns health', 'route 53']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.route53_health_check()
            response = f"""🏥 **Route 53 健康检查**

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

**Hosted Zones:** {len(health.get('hosted_zones', []))}
| Name | ID | Private | Records |
|------|----| --------|---------|"""
            
            for zone in health.get('hosted_zones', [])[:10]:
                private_tag = "✅" if zone.get('private') else ""
                response += f"\n| {zone['name'][:30]} | {zone['id']} | {private_tag} | {zone.get('record_count', 0)} |"
            
            hcs = health.get('health_checks', [])
            if hcs:
                response += f"\n\n**Health Checks:** {len(hcs)}"
                unhealthy = [hc for hc in hcs if hc['status'] != 'healthy']
                if unhealthy:
                    response += f"\n⚠️ {len(unhealthy)} unhealthy health checks"
            
            return response
        except Exception as e:
            return f"❌ Route53 健康检查失败: {str(e)}"
    
    # ===========================================
    # DynamoDB Commands
    # ===========================================
    
    # DynamoDB Health Check
    if any(kw in message_lower for kw in ['dynamodb health', 'ddb health', 'dynamo health']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.dynamodb_health_check()
            response = f"""🏥 **DynamoDB 健康检查** (Region: {_current_region})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Table | Status | Billing | RCU | WCU | Items | Issues |
|-------|--------|---------|-----|-----|-------|--------|"""
            
            for table in health.get('tables', [])[:10]:
                health_icon = "✅" if table['health'] == 'healthy' else "⚠️"
                issues_str = ", ".join(table.get('issues', [])[:2]) or "None"
                response += f"\n| {table['name'][:15]} | {table['status']} | {table['billing_mode'][:10]} | {table['read_capacity']} | {table['write_capacity']} | {table['item_count']} | {issues_str[:15]} |"
            
            return response
        except Exception as e:
            return f"❌ DynamoDB 健康检查失败: {str(e)}"
    
    # List DynamoDB tables
    if any(kw in message_lower for kw in ['dynamodb', 'ddb', 'dynamo', '表']):
        try:
            data = scanner._scan_dynamodb()
            if data.get('error'):
                return f"⚠️ **DynamoDB 访问受限**\n\n{data['error']}\n\n*需要 IAM 权限: dynamodb:ListTables, dynamodb:DescribeTable*"
            
            response = f"""📊 **DynamoDB Tables** (Region: {_current_region})

Total: {data['count']}

| Table | Status | Billing | RCU | WCU | Items |
|-------|--------|---------|-----|-----|-------|"""
            
            for table in data.get('tables', [])[:15]:
                response += f"\n| {table['name'][:20]} | {table['status']} | {table.get('billing_mode', 'N/A')[:10]} | {table.get('read_capacity', 0)} | {table.get('write_capacity', 0)} | {table.get('item_count', 0)} |"
            
            if data['count'] > 15:
                response += f"\n\n... 还有 {data['count'] - 15} 个表"
            
            return response
        except Exception as e:
            return f"❌ 获取 DynamoDB 失败: {str(e)}"
    
    # ===========================================
    # ECS Commands
    # ===========================================
    
    # ECS Health Check
    if any(kw in message_lower for kw in ['ecs health', 'container health']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.ecs_health_check()
            response = f"""🏥 **ECS 健康检查** (Region: {_current_region})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Cluster | Status | Running | Pending | Services | Issues |
|---------|--------|---------|---------|----------|--------|"""
            
            for cluster in health.get('clusters', [])[:10]:
                health_icon = "✅" if cluster['health'] == 'healthy' else "⚠️"
                issues_str = ", ".join(cluster.get('issues', [])[:2]) or "None"
                response += f"\n| {cluster['name'][:15]} | {cluster['status']} | {cluster['running_tasks']} | {cluster['pending_tasks']} | {cluster['active_services']} | {issues_str[:15]} |"
            
            return response
        except Exception as e:
            return f"❌ ECS 健康检查失败: {str(e)}"
    
    # List ECS clusters
    if any(kw in message_lower for kw in ['ecs', 'container', '容器']):
        try:
            data = scanner._scan_ecs()
            if data.get('error'):
                return f"⚠️ **ECS 访问受限**\n\n{data['error']}\n\n*需要 IAM 权限: ecs:ListClusters, ecs:DescribeClusters*"
            
            response = f"""🐳 **ECS Clusters** (Region: {_current_region})

Total: {data['count']}

| Cluster | Status | Running | Pending | Services |
|---------|--------|---------|---------|----------|"""
            
            for cluster in data.get('clusters', [])[:10]:
                response += f"\n| {cluster['name'][:20]} | {cluster['status']} | {cluster['running_tasks']} | {cluster['pending_tasks']} | {cluster['active_services']} |"
            
            return response
        except Exception as e:
            return f"❌ 获取 ECS 失败: {str(e)}"
    
    # ===========================================
    # ElastiCache Commands
    # ===========================================
    
    # ElastiCache Health Check
    if any(kw in message_lower for kw in ['elasticache health', 'cache health', 'redis health', 'memcached health']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.elasticache_health_check()
            if health.get('error'):
                return f"⚠️ **ElastiCache 访问受限**\n\n{health['error']}"
            
            response = f"""🏥 **ElastiCache 健康检查** (Region: {_current_region})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Cluster | Engine | Status | Nodes | Hit Ratio | Issues |
|---------|--------|--------|-------|-----------|--------|"""
            
            for cluster in health.get('clusters', [])[:10]:
                health_icon = "✅" if cluster['health'] == 'healthy' else "⚠️"
                issues_str = ", ".join(cluster.get('issues', [])[:2]) or "None"
                response += f"\n| {cluster['id'][:15]} | {cluster['engine']} | {cluster['status']} | {cluster.get('num_nodes', 0)} | {cluster.get('hit_ratio', '-')}% | {issues_str[:15]} |"
            
            return response
        except Exception as e:
            return f"❌ ElastiCache 健康检查失败: {str(e)}"
    
    # List ElastiCache clusters
    if any(kw in message_lower for kw in ['elasticache', 'cache', 'redis', 'memcached', '缓存']):
        try:
            data = scanner._scan_elasticache()
            if data.get('error'):
                return f"⚠️ **ElastiCache 访问受限**\n\n{data['error']}\n\n*需要 IAM 权限: elasticache:DescribeCacheClusters*"
            
            response = f"""🗄️ **ElastiCache Clusters** (Region: {_current_region})

Total: {data['count']}

| Cluster | Engine | Version | Status | Type | Nodes |
|---------|--------|---------|--------|------|-------|"""
            
            for cluster in data.get('clusters', [])[:10]:
                response += f"\n| {cluster['id'][:15]} | {cluster['engine']} | {cluster.get('engine_version', '-')} | {cluster['status']} | {cluster.get('node_type', cluster.get('type', '-'))} | {cluster.get('num_nodes', 0)} |"
            
            return response
        except Exception as e:
            return f"❌ 获取 ElastiCache 失败: {str(e)}"
    
    # ===========================================
    # Notification Commands
    # ===========================================
    
    # Check notification status
    if any(kw in message_lower for kw in ['notification status', '通知状态', 'alert status', '告警状态']):
        try:
            from src.notifications import get_notification_manager
            manager = get_notification_manager()
            status = manager.get_status()
            
            slack_status = "✅ 已配置" if status['channels']['slack'] else "❌ 未配置 (需设置 SLACK_WEBHOOK_URL)"
            
            return f"""🔔 **告警通知状态**

| Channel | Status |
|---------|--------|
| Slack | {slack_status} |

**配置方法:**
设置环境变量 `SLACK_WEBHOOK_URL` 即可启用 Slack 告警"""
        except Exception as e:
            return f"❌ 获取通知状态失败: {str(e)}"
    
    # Send test notification
    if any(kw in message_lower for kw in ['test notification', '测试通知', 'test alert', '测试告警']):
        try:
            from src.notifications import get_notification_manager
            manager = get_notification_manager()
            
            if not manager.is_configured():
                return """⚠️ **告警通知未配置**

请设置 `SLACK_WEBHOOK_URL` 环境变量后重试。

示例:
```
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
```"""
            
            result = manager.send_alert(
                title="测试告警",
                message="这是一条测试消息，确认告警通知功能正常工作。",
                level="info",
                details={"Source": "AgenticAIOps", "Type": "Test"}
            )
            
            if result.get('success'):
                return "✅ **测试告警已发送！** 请检查 Slack 频道。"
            else:
                return f"❌ 发送失败: {result.get('error')}"
        except Exception as e:
            return f"❌ 测试通知失败: {str(e)}"
    
    # Send custom alert
    if any(kw in message_lower for kw in ['send alert', '发送告警']):
        try:
            from src.notifications import get_notification_manager
            manager = get_notification_manager()
            
            if not manager.is_configured():
                return "⚠️ 告警通知未配置，请设置 SLACK_WEBHOOK_URL"
            
            # Extract message after 'alert' keyword
            import re
            match = re.search(r'alert\s+(.+)', message, re.IGNORECASE)
            if match:
                alert_message = match.group(1)
                result = manager.send_alert(
                    title="自定义告警",
                    message=alert_message,
                    level="warning"
                )
                if result.get('success'):
                    return f"✅ 告警已发送: {alert_message[:50]}..."
                else:
                    return f"❌ 发送失败: {result.get('error')}"
            else:
                return """**发送自定义告警**

用法: `send alert <消息内容>`

示例: `send alert Production DB CPU 超过 90%`"""
        except Exception as e:
            return f"❌ 发送告警失败: {str(e)}"
    
    # ===========================================
    # Knowledge Base Commands
    # ===========================================
    
    # KB Stats
    if any(kw in message_lower for kw in ['kb stats', 'knowledge stats', '知识库统计']):
        try:
            from src.operations_knowledge import get_knowledge_store
            store = get_knowledge_store()
            stats = store.get_stats()
            
            response = f"""📚 **知识库统计**

| 项目 | 值 |
|------|-----|
| 总 Patterns | {stats['total_patterns']} |
| 平均置信度 | {stats['avg_confidence']:.2f} |

**按分类:**
"""
            for cat, count in stats.get('by_category', {}).items():
                response += f"- {cat}: {count}\n"
            
            response += "\n**按服务:**\n"
            for svc, count in stats.get('by_service', {}).items():
                response += f"- {svc}: {count}\n"
            
            return response
        except Exception as e:
            return f"❌ 获取知识库统计失败: {str(e)}"
    
    # KB Search (keyword-based)
    if any(kw in message_lower for kw in ['kb search', 'knowledge search', '知识搜索']) and 'semantic' not in message_lower:
        try:
            from src.operations_knowledge import get_knowledge_store
            store = get_knowledge_store()
            
            import re
            match = re.search(r'search\s+(.+)', message, re.IGNORECASE)
            if not match:
                return """**知识搜索**

用法: `kb search <关键词>`

示例: 
- `kb search high cpu`
- `kb search ec2 timeout`

**语义搜索:** `kb semantic <问题描述>`"""
            
            query = match.group(1).strip()
            keywords = query.lower().split()
            
            patterns = store.search_patterns(keywords=keywords, limit=5)
            
            if not patterns:
                return f"🔍 未找到匹配 '{query}' 的知识条目\n\n💡 试试语义搜索: `kb semantic {query}`"
            
            response = f"""🔍 **知识搜索结果: '{query}'**

找到 {len(patterns)} 条匹配:

"""
            for p in patterns:
                response += f"""**{p.title}** ({p.pattern_id})
- 分类: {p.category} | 服务: {p.service} | 置信度: {p.confidence:.2f}
- 症状: {', '.join(p.symptoms[:3])}...
- 解决方案: {p.remediation[:100]}...

"""
            return response
        except Exception as e:
            return f"❌ 知识搜索失败: {str(e)}"
    
    # KB Semantic Search (vector-based)
    if any(kw in message_lower for kw in ['kb semantic', 'semantic search', '语义搜索']):
        try:
            import re
            match = re.search(r'(?:semantic|语义搜索)\s+(.+)', message, re.IGNORECASE)
            if not match:
                return """**语义搜索 (AI 驱动)**

用法: `kb semantic <问题描述>`

示例: 
- `kb semantic 服务器响应很慢怎么办`
- `kb semantic database connection timeout`
- `kb semantic lambda 函数执行失败`

使用 AI 向量匹配，支持自然语言查询"""
            
            query = match.group(1).strip()
            
            from src.vector_search import get_vector_search
            search = get_vector_search()
            
            if not search._initialized:
                return "⚠️ 向量搜索服务未初始化，请稍后再试"
            
            results = search.hybrid_search(query, limit=5)
            
            if not results:
                return f"🔍 未找到与 '{query}' 语义相关的知识"
            
            response = f"""🧠 **语义搜索结果: '{query}'**

找到 {len(results)} 条相关知识:

"""
            for r in results:
                response += f"""**{r.get('title', 'N/A')}** ({r.get('type', 'unknown')})
- 服务: {r.get('service', 'N/A')} | 相关度: {r.get('score', 0):.2f}
- {r.get('description', '')[:100]}...

"""
            return response
        except Exception as e:
            return f"❌ 语义搜索失败: {str(e)}"
    
    # KB Index (create OpenSearch index)
    if any(kw in message_lower for kw in ['kb index', 'kb init', 'create index']):
        try:
            from src.vector_search import get_vector_search
            search = get_vector_search()
            
            if search.create_index():
                return "✅ **知识库向量索引创建成功！**\n\n现在可以使用 `kb semantic <查询>` 进行语义搜索"
            else:
                return "❌ 索引创建失败，请检查 OpenSearch 连接"
        except Exception as e:
            return f"❌ 索引创建失败: {str(e)}"
    
    # Learn from incident
    if any(kw in message_lower for kw in ['learn incident', '学习故障', 'learn from']):
        return """📚 **学习故障/Incident**

用法: 通过 API 提交 Incident 记录

```
POST /api/knowledge/learn
{
  "incident_id": "INC-001",
  "title": "EC2 High CPU",
  "description": "Instance CPU utilization exceeded 90%",
  "service": "ec2",
  "severity": "high",
  "symptoms": ["high cpu", "slow response"],
  "root_cause": "Memory leak in application",
  "resolution": "Restarted application",
  "resolution_steps": ["Identified leak", "Restarted app", "Monitored"]
}
```

或使用: `POST /api/knowledge/learn`"""
    
    # Pattern feedback
    if any(kw in message_lower for kw in ['feedback', '反馈']):
        try:
            import re
            # Format: feedback <pattern_id> good/bad
            match = re.search(r'feedback\s+([a-f0-9]+)\s+(good|bad|helpful|not helpful)', message_lower)
            if not match:
                return """**提交 Pattern 反馈**

用法: `feedback <pattern_id> good/bad`

示例:
- `feedback abc123 good` - 标记为有帮助
- `feedback abc123 bad` - 标记为无帮助"""
            
            pattern_id = match.group(1)
            is_helpful = match.group(2) in ['good', 'helpful']
            
            from src.operations_knowledge import get_feedback_handler
            handler = get_feedback_handler()
            
            if handler.submit_feedback(pattern_id, is_helpful):
                return f"✅ 反馈已提交: Pattern {pattern_id} {'👍 有帮助' if is_helpful else '👎 无帮助'}"
            else:
                return f"❌ Pattern {pattern_id} 不存在"
        except Exception as e:
            return f"❌ 提交反馈失败: {str(e)}"
    
    # ===========================================
    # RCA + SOP Bridge Commands (Enhanced)
    # ===========================================
    
    # RCA Analyze: Combined RCA + SOP suggestion
    # RCA Deep: Full pipeline — Collect → Analyze with Claude → SOP
    if any(kw in message_lower for kw in ['rca deep', 'rca 深度', 'deep analyze', '深度分析']):
        try:
            import asyncio
            from src.event_correlator import get_correlator
            from src.rca_inference import get_rca_inference_engine
            from src.rca_sop_bridge import get_bridge
            
            # Parse optional service filter
            import re
            match = re.search(r'(?:rca deep|deep analyze|深度分析)\s*(.*)', message, re.IGNORECASE)
            service_filter = None
            if match and match.group(1).strip():
                svc = match.group(1).strip().lower()
                if svc in ['ec2', 'rds', 'lambda']:
                    service_filter = [svc]
            
            # Step 1: Collect data
            correlator = get_correlator(_current_region)
            loop = asyncio.new_event_loop()
            try:
                event = loop.run_until_complete(
                    correlator.collect(services=service_filter, lookback_minutes=60)
                )
                
                # Step 2: Claude inference
                engine = get_rca_inference_engine()
                rca_result = loop.run_until_complete(engine.analyze(event))
            finally:
                loop.close()
            
            # Step 3: SOP suggestion
            bridge = get_bridge()
            sop_suggestions = bridge._find_matching_sops(rca_result)
            
            # Build response
            from src.rca.models import Severity
            severity_icon = '🔴' if rca_result.severity == Severity.HIGH else '🟡' if rca_result.severity == Severity.MEDIUM else '🟢'
            
            # Build response
            response = f"""🔬 **深度 RCA 分析** (Region: {_current_region})

**采集数据:** {len(event.metrics)} 指标 | {len(event.alarms)} 告警 | {len(event.trail_events)} 事件 | 耗时 {event.duration_ms}ms

---

**根因:** {rca_result.root_cause}
**严重性:** {severity_icon} {rca_result.severity.value.upper()}
**置信度:** {rca_result.confidence:.0%}
**分析模型:** `{rca_result.pattern_id}`

### 📋 证据链
"""
            for e in rca_result.evidence:
                response += f"- {e}\n"
            
            if sop_suggestions:
                response += "\n### 🛠️ 推荐 SOP\n\n"
                response += "| SOP | 名称 | 匹配度 | 步骤 |\n|-----|------|--------|------|\n"
                for sop in sop_suggestions[:3]:
                    response += f"| `{sop['sop_id']}` | {sop['name']} | {sop['match_confidence']:.0%} | {sop['steps']}步 |\n"
                response += "\n使用 `sop run <id>` 执行"
            
            if rca_result.remediation.suggestion:
                response += f"\n\n### 💡 建议\n{rca_result.remediation.suggestion}"
            
            return response
        except Exception as e:
            import traceback
            return f"❌ 深度 RCA 分析失败: {str(e)}\n```\n{traceback.format_exc()[:500]}\n```"
    
    # RCA Analyze: Combined RCA + SOP suggestion (existing - symptom based)
    if any(kw in message_lower for kw in ['rca analyze', 'rca 分析', 'diagnose', '诊断问题', 'root cause']):
        try:
            import re
            from src.rca_sop_bridge import get_bridge
            
            bridge = get_bridge()
            
            # Extract symptoms from the message
            # e.g., "rca analyze high cpu memory leak"
            match = re.search(r'(?:rca analyze|diagnose|诊断问题|root cause)\s*(.*)', message, re.IGNORECASE)
            symptoms = []
            if match and match.group(1).strip():
                symptoms = match.group(1).strip().split()
            
            if not symptoms:
                return """🔍 **RCA 分析 + SOP 推荐**

用法: `rca analyze <症状描述>`

示例:
- `rca analyze high cpu memory leak`
- `rca analyze OOMKilled crash loop`
- `rca analyze rds connection timeout`
- `diagnose lambda timeout error`

这将执行根因分析并自动推荐相关 SOP。"""
            
            result = bridge.analyze_and_suggest(
                symptoms=symptoms,
                auto_execute=False,  # Don't auto-execute from chat
            )
            
            return result.to_markdown()
        except Exception as e:
            return f"❌ RCA 分析失败: {str(e)}"
    
    # RCA Auto-fix: RCA + auto-execute SOP for low severity
    if any(kw in message_lower for kw in ['rca autofix', 'rca 自动修复', 'auto diagnose']):
        try:
            import re
            from src.rca_sop_bridge import get_bridge
            
            bridge = get_bridge()
            
            match = re.search(r'(?:rca autofix|rca 自动修复|auto diagnose)\s*(.*)', message, re.IGNORECASE)
            symptoms = match.group(1).strip().split() if match and match.group(1).strip() else []
            
            if not symptoms:
                return """⚡ **RCA 自动修复**

用法: `rca autofix <症状描述>`

示例: `rca autofix high cpu`

⚠️ 仅 LOW 严重性 + 高置信度 (≥80%) 会自动执行 SOP"""
            
            result = bridge.analyze_and_suggest(
                symptoms=symptoms,
                auto_execute=True,
            )
            
            return result.to_markdown()
        except Exception as e:
            return f"❌ RCA 自动修复失败: {str(e)}"
    
    # RCA Feedback: Submit feedback from SOP execution
    if any(kw in message_lower for kw in ['rca feedback', 'rca 反馈']):
        try:
            import re
            from src.rca_sop_bridge import get_bridge
            
            # Format: rca feedback <execution_id> <sop_id> <pattern_id> success/fail
            match = re.search(
                r'rca feedback\s+(\S+)\s+(\S+)\s+(\S+)\s+(success|fail|good|bad)',
                message_lower
            )
            if not match:
                return """📝 **RCA 执行反馈**

用法: `rca feedback <execution_id> <sop_id> <pattern_id> success/fail`

示例: `rca feedback exec123 sop-ec2-high-cpu oom-killed success`

这有助于系统学习哪些 SOP 能有效解决特定根因。"""
            
            bridge = get_bridge()
            success = match.group(4) in ['success', 'good']
            
            feedback = bridge.submit_feedback(
                execution_id=match.group(1),
                sop_id=match.group(2),
                rca_pattern_id=match.group(3),
                success=success,
                root_cause_confirmed=success,
            )
            
            emoji = "✅" if success else "❌"
            return f"""{emoji} **RCA 反馈已记录**

- 执行 ID: `{feedback.execution_id}`
- SOP: `{feedback.sop_id}`
- Pattern: `{feedback.rca_pattern_id}`
- 结果: {'成功 ✅' if success else '失败 ❌'}
- 根因确认: {'是' if success else '否'}

{'系统将在未来优先推荐此 SOP 处理类似问题。' if success else '系统将降低此 SOP 的推荐优先级。'}"""
        except Exception as e:
            return f"❌ 反馈提交失败: {str(e)}"
    
    # RCA Stats: View feedback statistics
    if any(kw in message_lower for kw in ['rca stats', 'rca 统计', 'rca status']):
        try:
            from src.rca_sop_bridge import get_bridge
            
            bridge = get_bridge()
            stats = bridge.get_feedback_stats()
            
            response = f"""📊 **RCA ↔ SOP 统计**

| 指标 | 值 |
|------|-----|
| 总反馈数 | {stats['total_feedbacks']} |
| 成功解决 | {stats['successful']} |
| 解决失败 | {stats['failed']} |
| 根因确认 | {stats['root_cause_confirmed']} |
| 成功率 | {stats['success_rate']:.0%} |
| 平均解决时间 | {stats['avg_resolution_seconds']:.0f}s |
"""
            if stats['learned_mappings']:
                response += "\n**🧠 已学习的 Pattern → SOP 映射:**\n\n"
                for pattern_id, sops in stats['learned_mappings'].items():
                    for sop_id, count in sops.items():
                        response += f"- `{pattern_id}` → `{sop_id}` ({count}次成功)\n"
            
            return response
        except Exception as e:
            return f"❌ 获取统计失败: {str(e)}"
    
    # ===========================================
    # SOP Commands
    # ===========================================
    
    # SOP List
    if any(kw in message_lower for kw in ['sop list', 'sop 列表', 'list sop']):
        try:
            from src.sop_system import get_sop_store
            store = get_sop_store()
            
            # Parse optional filters
            service_filter = None
            category_filter = None
            
            sops = store.list_sops(service=service_filter, category=category_filter)
            
            if not sops:
                return "📋 没有可用的 SOP"
            
            response = f"""📋 **SOP 列表** ({len(sops)} 个)

| ID | 名称 | 服务 | 分类 | 严重性 |
|-----|------|------|------|--------|
"""
            for sop in sops:
                response += f"| {sop.sop_id} | {sop.name} | {sop.service} | {sop.category} | {sop.severity} |\n"
            
            response += "\n使用 `sop show <id>` 查看详情"
            return response
        except Exception as e:
            return f"❌ 获取 SOP 列表失败: {str(e)}"
    
    # SOP Show
    if any(kw in message_lower for kw in ['sop show', 'sop 详情', 'show sop']):
        try:
            import re
            match = re.search(r'(?:sop show|show sop)\s+(\S+)', message_lower)
            if not match:
                return """**查看 SOP 详情**

用法: `sop show <sop_id>`

示例: `sop show sop-ec2-high-cpu`"""
            
            sop_id = match.group(1)
            
            from src.sop_system import get_sop_store
            store = get_sop_store()
            sop = store.get_sop(sop_id)
            
            if not sop:
                return f"❌ SOP '{sop_id}' 不存在"
            
            response = f"""📋 **SOP: {sop.name}**

**ID:** {sop.sop_id}
**描述:** {sop.description}
**服务:** {sop.service}
**分类:** {sop.category}
**严重性:** {sop.severity}
**触发类型:** {sop.trigger_type}

**步骤:**
"""
            for i, step in enumerate(sop.steps, 1):
                step_obj = step if hasattr(step, 'name') else type('Step', (), step)()
                name = step.name if hasattr(step, 'name') else step.get('name', '')
                desc = step.description if hasattr(step, 'description') else step.get('description', '')
                response += f"{i}. **{name}** - {desc}\n"
            
            response += f"\n**标签:** {', '.join(sop.tags)}"
            return response
        except Exception as e:
            return f"❌ 获取 SOP 详情失败: {str(e)}"
    
    # SOP Suggest
    if any(kw in message_lower for kw in ['sop suggest', 'sop 推荐', 'suggest sop']):
        try:
            import re
            # Format: sop suggest <service> <keywords>
            match = re.search(r'suggest\s+(\w+)\s*(.*)', message, re.IGNORECASE)
            if not match:
                return """**推荐 SOP**

用法: `sop suggest <服务> <问题关键词>`

示例:
- `sop suggest ec2 high cpu`
- `sop suggest rds failover`
- `sop suggest lambda errors`"""
            
            service = match.group(1).lower()
            keywords = match.group(2).strip().split() if match.group(2) else []
            
            from src.sop_system import get_sop_store
            store = get_sop_store()
            
            suggested = store.suggest_sops(service, keywords)
            
            if not suggested:
                return f"🔍 没有找到与 '{service} {' '.join(keywords)}' 相关的 SOP"
            
            response = f"""🔍 **推荐 SOP** (服务: {service})

"""
            for sop in suggested:
                est_time = sum(s.estimated_minutes if hasattr(s, 'estimated_minutes') else 5 for s in sop.steps)
                response += f"**{sop.name}** (`{sop.sop_id}`)\n- {sop.description}\n- 步骤数: {len(sop.steps)} | 预计时间: {est_time}分钟\n\n"
            return response
        except Exception as e:
            return f"❌ SOP 推荐失败: {str(e)}"
    
    # SOP Run
    if any(kw in message_lower for kw in ['sop run', 'sop 执行', 'run sop', 'execute sop']):
        try:
            import re
            match = re.search(r'(?:sop run|run sop|execute sop)\s+(\S+)', message_lower)
            if not match:
                return """**执行 SOP**

用法: `sop run <sop_id>`

示例: `sop run sop-ec2-high-cpu`

⚠️ 注意: 这将启动 SOP 执行流程，部分步骤可能需要人工确认"""
            
            sop_id = match.group(1)
            
            from src.sop_system import get_sop_store, get_sop_executor
            store = get_sop_store()
            executor = get_sop_executor()
            
            sop = store.get_sop(sop_id)
            if not sop:
                return f"❌ SOP '{sop_id}' 不存在"
            
            execution = executor.start_execution(sop_id, triggered_by="chat")
            
            if not execution:
                return f"❌ 启动 SOP 执行失败"
            
            response = f"""🚀 **SOP 执行已启动**

**SOP:** {sop.name}
**执行 ID:** {execution.execution_id}
**状态:** {execution.status}

**步骤预览:**
"""
            for i, step in enumerate(sop.steps, 1):
                name = step.name if hasattr(step, 'name') else step.get('name', '')
                step_type = step.step_type.value if hasattr(step, 'step_type') else step.get('step_type', 'manual')
                response += f"{i}. {name} ({step_type})\n"
            
            response += f"\n使用 `sop status {execution.execution_id}` 查看执行状态"
            return response
        except Exception as e:
            return f"❌ SOP 执行失败: {str(e)}"
    
    # Account info
    if any(kw in message_lower for kw in ['account', '账号', '账户', 'who am i']):
        try:
            data = scanner.get_account_info()
            return f"""🔐 **AWS Account Info**

- Account ID: `{data.get('account_id', 'N/A')}`
- ARN: `{data.get('arn', 'N/A')}`
- Current Region: `{_current_region}`"""
        except Exception as e:
            return f"❌ 获取账号信息失败: {str(e)}"
    
    # Help
    if any(kw in message_lower for kw in ['help', '帮助', 'commands', '命令']):
        return """📚 **AWS 运维命令**

**🏥 健康检查:**
- `health` / `健康` / `诊断` - 全服务健康检查
- `EC2 health` - EC2 健康检查
- `RDS health` - RDS 健康检查
- `Lambda health` - Lambda 健康检查
- `S3 health` - S3 安全检查

**📊 指标监控:**
- `EC2 metrics i-xxx` - EC2 实例指标
- `RDS metrics db-name` - RDS 数据库指标

**📜 日志查询:**
- `Lambda logs function-name` - Lambda 函数日志
- `Lambda error logs function-name` - Lambda 错误日志

**🔍 异常检测:**
- `anomaly` / `异常` / `检测问题` - 异常检测

**🔬 RCA + SOP 联动 (NEW):**
- `rca deep` - **完整分析**: 采集数据 → Claude 推理 → SOP 推荐
- `rca deep ec2` / `rca deep rds` - 指定服务深度分析
- `rca analyze <症状>` - 基于症状的快速分析
- `rca autofix <症状>` - 分析并自动执行低风险 SOP
- `rca feedback <exec_id> <sop_id> <pattern_id> success/fail` - 执行反馈
- `rca stats` - 查看 RCA↔SOP 学习统计

**📋 资源列表:**
- `scan` / `扫描` - 全资源扫描
- `show EC2` / `显示 EC2` - EC2 实例列表
- `show Lambda` / `显示 Lambda` - Lambda 函数
- `show S3` / `显示 S3` - S3 桶列表
- `show RDS` / `显示 RDS` - RDS 数据库
- `show account` - 账号信息

**🔧 运维操作:**
- `ec2 start/stop/reboot <id>` - EC2 操作
- `rds reboot/failover <id>` - RDS 操作
- `lambda invoke <name>` - Lambda 调用

**📚 知识库:**
- `kb stats` - 知识库统计
- `kb search <关键词>` - 搜索知识
- `feedback <id> good/bad` - 提交反馈

**📋 SOP 系统:**
- `sop list` - 列出所有 SOP
- `sop show <id>` - 查看 SOP 详情
- `sop suggest <服务> <关键词>` - 推荐 SOP
- `sop run <id>` - 执行 SOP

**🔔 告警通知:**
- `notification status` - 告警系统状态
- `test notification` - 发送测试告警

💡 **示例:**
- "检查 EC2 健康状态"
- "sop suggest ec2 high cpu"
- "kb search timeout error"
"""
    
    return None


def detect_ui_action(message: str) -> Optional[dict]:
    """Detect if the message is requesting a UI action (A2UI)."""
    message_lower = message.lower()
    
    # Widget creation patterns
    add_patterns = ['添加', 'add', '创建', 'create', '显示', 'show', '生成', 'generate']
    widget_types = {
        'ec2': 'stat-card',
        'lambda': 'table',
        'cpu': 'stat-card',
        'memory': 'stat-card',
        'alert': 'alert-list',
        '告警': 'alert-list',
        'service': 'service-status',
        '服务': 'service-status',
        'table': 'table',
        '表格': 'table',
        'card': 'stat-card',
        '卡片': 'stat-card',
    }
    
    # Check if this is an add/create request
    is_add_request = any(pattern in message_lower for pattern in add_patterns)
    
    if not is_add_request:
        return None
    
    # Detect widget type
    detected_type = None
    detected_title = "New Widget"
    
    for keyword, wtype in widget_types.items():
        if keyword in message_lower:
            detected_type = wtype
            detected_title = f"{keyword.upper()} Monitor"
            break
    
    if detected_type:
        return {
            "action": "add_widget",
            "widget": {
                "type": detected_type,
                "config": {
                    "title": detected_title,
                    "value": 0 if detected_type == 'stat-card' else None,
                    "icon": "cloud",
                    "color": "#06AC38"
                },
                "span": 24 if detected_type == 'table' else 8
            }
        }
    
    return None


# =============================================================================
# A2UI Endpoints (Agent-to-UI)
# =============================================================================

@app.post("/api/a2ui/generate", response_model=A2UIGenerateResponse)
async def a2ui_generate(request: A2UIGenerateRequest):
    """Generate a UI widget configuration from natural language prompt."""
    try:
        ui_action = detect_ui_action(request.prompt)
        
        if ui_action and ui_action.get("widget"):
            widget = ui_action["widget"]
            widget["id"] = f"widget-{int(datetime.now().timestamp() * 1000)}"
            
            return A2UIGenerateResponse(
                success=True,
                widget=A2UIWidgetConfig(**widget),
                message=f"Created {widget['type']} widget: {widget['config'].get('title', 'Untitled')}"
            )
        else:
            return A2UIGenerateResponse(
                success=False,
                widget=None,
                message="Could not understand the widget request. Try: 'Add an EC2 monitoring card' or 'Create a Lambda table'"
            )
    except Exception as e:
        return A2UIGenerateResponse(
            success=False,
            widget=None,
            message=f"Error: {str(e)}"
        )


@app.get("/api/a2ui/widget-types")
async def a2ui_widget_types():
    """Get available widget types for A2UI."""
    return {
        "types": [
            {"key": "stat-card", "name": "Stat Card", "description": "KPI/metric display", "icon": "📊"},
            {"key": "table", "name": "Table", "description": "Data table with columns", "icon": "📋"},
            {"key": "alert-list", "name": "Alert List", "description": "List of alerts/issues", "icon": "⚠️"},
            {"key": "service-status", "name": "Service Status", "description": "Service health indicators", "icon": "🟢"},
            {"key": "progress-bar", "name": "Progress Bar", "description": "Progress/utilization meter", "icon": "📈"},
            {"key": "resource-list", "name": "Resource List", "description": "Cloud resource listing", "icon": "☁️"},
        ]
    }


# =============================================================================
# Cluster Endpoints
# =============================================================================

@app.get("/api/cluster/info")
async def cluster_info():
    """Get cluster information."""
    try:
        return get_cluster_info()
    except Exception as e:
        # Return mock data on error
        return {
            "name": "testing-cluster",
            "version": "1.32",
            "status": "ACTIVE",
            "region": "ap-southeast-1"
        }


@app.get("/api/cluster/health")
async def cluster_health():
    """Get cluster health status."""
    try:
        return get_cluster_health()
    except Exception as e:
        return {"status": "unknown", "error": str(e)}


# =============================================================================
# Pod Endpoints
# =============================================================================

@app.get("/api/pods")
async def list_pods(namespace: Optional[str] = None):
    """List all pods, optionally filtered by namespace."""
    try:
        return get_pods(namespace)
    except Exception as e:
        return {"pods": [], "error": str(e)}


@app.get("/api/pods/{namespace}/{name}")
async def pod_details(namespace: str, name: str):
    """Get detailed information about a specific pod."""
    try:
        return describe_pod(namespace, name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/pods/{namespace}/{name}/logs")
async def pod_logs(namespace: str, name: str, lines: int = 100):
    """Get logs from a specific pod."""
    try:
        return get_pod_logs(namespace, name, lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Node Endpoints
# =============================================================================

@app.get("/api/nodes")
async def list_nodes():
    """List all nodes in the cluster."""
    try:
        return get_nodes()
    except Exception as e:
        return {"nodes": [], "error": str(e)}


# =============================================================================
# Deployment Endpoints
# =============================================================================

@app.get("/api/deployments")
async def list_deployments(namespace: Optional[str] = None):
    """List all deployments."""
    try:
        return get_deployments(namespace)
    except Exception as e:
        return {"deployments": [], "error": str(e)}


# =============================================================================
# Events Endpoint
# =============================================================================

@app.get("/api/events")
async def list_events(namespace: Optional[str] = None):
    """Get recent cluster events."""
    try:
        return get_events(namespace)
    except Exception as e:
        return {"events": [], "error": str(e)}


# =============================================================================
# Anomaly Detection Endpoint
# =============================================================================

@app.get("/api/anomalies")
async def detect_anomalies():
    """Detect anomalies in the cluster."""
    anomalies = []
    
    try:
        # Get pods and check for issues
        pods_data = get_pods()
        
        for pod in pods_data.get('pods', []):
            status = pod.get('status', '')
            restarts = pod.get('restarts', 0)
            
            if 'CrashLoop' in status:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "critical",
                    "type": "CrashLoopBackOff",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": f"Pod has restarted {restarts} times",
                    "timestamp": datetime.utcnow().isoformat(),
                    "aiSuggestion": "Check application logs and configuration."
                })
            elif 'OOM' in status:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "critical", 
                    "type": "OOMKilled",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": "Container killed due to out of memory",
                    "timestamp": datetime.utcnow().isoformat(),
                    "aiSuggestion": "Increase memory limits in deployment spec."
                })
            elif restarts > 5:
                anomalies.append({
                    "id": len(anomalies) + 1,
                    "severity": "warning",
                    "type": "HighRestarts",
                    "resource": pod.get('name'),
                    "namespace": pod.get('namespace'),
                    "message": f"Pod restart count ({restarts}) exceeds threshold",
                    "timestamp": datetime.utcnow().isoformat(),
                    "aiSuggestion": "Review application health and probe configurations."
                })
                
    except Exception as e:
        pass  # Return empty list on error
    
    return {"anomalies": anomalies}


# =============================================================================
# RCA Reports Endpoints
# =============================================================================

class RCAReport(BaseModel):
    id: str
    title: str
    status: str
    severity: str
    createdAt: str
    resolvedAt: Optional[str]
    rootCause: str
    symptoms: List[str]
    diagnosis: dict
    solution: str
    commands: List[str]


@app.get("/api/rca/reports")
async def list_rca_reports():
    """List all RCA reports."""
    return {"reports": rca_reports}


@app.post("/api/rca/reports")
async def create_rca_report(report: RCAReport):
    """Create a new RCA report."""
    rca_reports.append(report.dict())
    return {"status": "created", "id": report.id}


@app.get("/api/rca/reports/{report_id}")
async def get_rca_report(report_id: str):
    """Get a specific RCA report."""
    for report in rca_reports:
        if report["id"] == report_id:
            return report
    raise HTTPException(status_code=404, detail="Report not found")


# =============================================================================
# RCA ↔ SOP Bridge API
# =============================================================================

class RCAAnalyzeRequest(BaseModel):
    symptoms: List[str] = []
    namespace: Optional[str] = None
    pod: Optional[str] = None
    auto_execute: bool = False

class RCAFeedbackRequest(BaseModel):
    execution_id: str
    sop_id: str
    rca_pattern_id: str
    success: bool
    root_cause_confirmed: bool = False
    resolution_time_seconds: int = 0
    notes: str = ""


@app.post("/api/rca/analyze")
async def rca_analyze(request: RCAAnalyzeRequest):
    """Run RCA analysis with SOP recommendations."""
    try:
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()
        
        result = bridge.analyze_and_suggest(
            namespace=request.namespace,
            pod=request.pod,
            symptoms=request.symptoms,
            auto_execute=request.auto_execute,
        )
        
        return {
            "success": True,
            "result": result.to_dict(),
            "markdown": result.to_markdown(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/rca/feedback")
async def rca_feedback(request: RCAFeedbackRequest):
    """Submit feedback from SOP execution back to RCA."""
    try:
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()
        
        feedback = bridge.submit_feedback(
            execution_id=request.execution_id,
            sop_id=request.sop_id,
            rca_pattern_id=request.rca_pattern_id,
            success=request.success,
            root_cause_confirmed=request.root_cause_confirmed,
            resolution_time_seconds=request.resolution_time_seconds,
            notes=request.notes,
        )
        
        return {
            "success": True,
            "feedback_recorded": True,
            "success_rate": bridge.get_feedback_stats()['success_rate'],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/rca/bridge/stats")
async def rca_bridge_stats():
    """Get RCA ↔ SOP bridge statistics and learned mappings."""
    try:
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()
        return {"success": True, **bridge.get_feedback_stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/rca/bridge/history")
async def rca_bridge_history(limit: int = 20):
    """Get recent RCA → SOP bridge results."""
    try:
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()
        return {"success": True, "history": bridge.get_history(limit)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Event Correlator API (Step 1: Data Collection Layer)
# =============================================================================

@app.get("/api/events/collect")
async def collect_events(
    services: str = None,
    lookback_minutes: int = 60,
):
    """
    Collect and correlate events from multiple AWS sources.
    
    READ-ONLY operation — collects CloudWatch metrics, alarms,
    CloudTrail events, and AWS Health events in parallel.
    
    Query params:
      - services: comma-separated (ec2,rds,lambda). Default: all.
      - lookback_minutes: how far back to look. Default: 60.
    """
    try:
        from src.event_correlator import get_correlator
        
        correlator = get_correlator(_current_region)
        service_list = services.split(',') if services else None
        
        event = await correlator.collect(
            services=service_list,
            lookback_minutes=lookback_minutes,
        )
        
        return {
            "success": True,
            "summary": event.summary(),
            "data": event.to_dict(),
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


@app.get("/api/events/collect/rca")
async def collect_events_for_rca(
    services: str = None,
    lookback_minutes: int = 60,
):
    """
    Collect events and format for RCA Engine consumption.
    Returns telemetry dict compatible with RCAEngine.analyze().
    """
    try:
        from src.event_correlator import get_correlator
        
        correlator = get_correlator(_current_region)
        service_list = services.split(',') if services else None
        
        event = await correlator.collect(
            services=service_list,
            lookback_minutes=lookback_minutes,
        )
        
        return {
            "success": True,
            "telemetry": event.to_rca_telemetry(),
            "collection_id": event.collection_id,
            "duration_ms": event.duration_ms,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/rca/deep")
async def rca_deep_analyze(
    services: str = None,
    lookback_minutes: int = 60,
    force_llm: bool = False,
):
    """
    Full RCA pipeline: Collect → Infer with Claude → SOP suggestions.
    
    This is the main RCA endpoint combining Step 1 + Step 2 + Step 3.
    """
    try:
        from src.event_correlator import get_correlator
        from src.rca_inference import get_rca_inference_engine
        from src.rca_sop_bridge import get_bridge
        
        # Step 1: Collect
        correlator = get_correlator(_current_region)
        service_list = services.split(',') if services else None
        event = await correlator.collect(
            services=service_list,
            lookback_minutes=lookback_minutes,
        )
        
        # Step 2: Analyze
        engine = get_rca_inference_engine()
        rca_result = await engine.analyze(event, force_llm=force_llm)
        
        # Step 3: SOP suggestions
        bridge = get_bridge()
        sop_suggestions = bridge._find_matching_sops(rca_result)
        
        return {
            "success": True,
            "collection": {
                "id": event.collection_id,
                "duration_ms": event.duration_ms,
                "metrics": len(event.metrics),
                "alarms": len(event.alarms),
                "trail_events": len(event.trail_events),
                "anomalies": len(event.anomalies),
            },
            "rca": rca_result.to_dict(),
            "sop_suggestions": sop_suggestions,
        }
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# =============================================================================
# Plugin System Endpoints
# =============================================================================

class PluginCreateRequest(BaseModel):
    plugin_type: str
    name: str
    config: dict = {}


class ClusterAddRequest(BaseModel):
    cluster_id: str
    name: str
    region: str
    plugin_type: str
    config: dict = {}


# Initialize default plugins on startup
@app.on_event("startup")
async def startup_event():
    """Initialize plugins from manifests on startup."""
    try:
        # Try loading from manifests first
        import os
        config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
        loaded = PluginRegistry.load_from_manifests(config_dir)
        
        if loaded == 0:
            # Fallback to default EKS plugin if no manifests
            eks_config = PluginConfig(
                plugin_id="eks-default",
                plugin_type="eks",
                name="EKS Default",
                enabled=True,
                config={"regions": ["ap-southeast-1"]}
            )
            PluginRegistry.create_plugin(eks_config)
        
        # Set active cluster if available
        clusters = PluginRegistry.get_clusters_by_type("eks")
        if clusters:
            PluginRegistry.set_active_cluster(clusters[0].cluster_id)
        
        print(f"Plugins initialized: {len(PluginRegistry.get_all_plugins())} plugins")
        print(f"Clusters discovered: {len(PluginRegistry.get_all_clusters())} clusters")
    except Exception as e:
        print(f"Warning: Failed to initialize plugins: {e}")


@app.get("/api/plugins")
async def list_plugins():
    """List all registered plugins."""
    return {
        "plugins": [p.get_info() for p in PluginRegistry.get_all_plugins()],
        "available_types": PluginRegistry.get_available_plugins()
    }


@app.post("/api/plugins")
async def create_plugin(request: PluginCreateRequest):
    """Create and register a new plugin."""
    import uuid
    
    config = PluginConfig(
        plugin_id=str(uuid.uuid4())[:8],
        plugin_type=request.plugin_type,
        name=request.name,
        enabled=True,
        config=request.config
    )
    
    plugin = PluginRegistry.create_plugin(config)
    if plugin:
        return {"status": "created", "plugin": plugin.get_info()}
    raise HTTPException(status_code=400, detail=f"Unknown plugin type: {request.plugin_type}")


@app.delete("/api/plugins/{plugin_id}")
async def remove_plugin(plugin_id: str):
    """Remove a plugin."""
    if PluginRegistry.remove_plugin(plugin_id):
        return {"status": "removed", "plugin_id": plugin_id}
    raise HTTPException(status_code=404, detail="Plugin not found")


@app.post("/api/plugins/{plugin_id}/enable")
async def enable_plugin(plugin_id: str):
    """Enable a plugin."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        plugin.enable()
        return {"status": "enabled", "plugin": plugin.get_info()}
    raise HTTPException(status_code=404, detail="Plugin not found")


@app.post("/api/plugins/{plugin_id}/disable")
async def disable_plugin(plugin_id: str):
    """Disable a plugin."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        plugin.disable()
        return {"status": "disabled", "plugin": plugin.get_info()}
    raise HTTPException(status_code=404, detail="Plugin not found")


@app.get("/api/plugins/{plugin_id}/status")
async def plugin_status(plugin_id: str):
    """Get plugin status and summary."""
    plugin = PluginRegistry.get_plugin(plugin_id)
    if plugin:
        return plugin.get_status_summary()
    raise HTTPException(status_code=404, detail="Plugin not found")


# =============================================================================
# Cluster Management Endpoints
# =============================================================================

@app.get("/api/clusters")
async def list_clusters(plugin_type: Optional[str] = None):
    """List all clusters/resources."""
    if plugin_type:
        clusters = PluginRegistry.get_clusters_by_type(plugin_type)
    else:
        clusters = PluginRegistry.get_all_clusters()
    
    active = PluginRegistry.get_active_cluster()
    
    return {
        "clusters": [c.to_dict() for c in clusters],
        "active_cluster": active.to_dict() if active else None
    }


@app.post("/api/clusters")
async def add_cluster(request: ClusterAddRequest):
    """Add a cluster manually."""
    from src.plugins.base import ClusterConfig
    
    cluster = ClusterConfig(
        cluster_id=request.cluster_id,
        name=request.name,
        region=request.region,
        plugin_type=request.plugin_type,
        config=request.config
    )
    PluginRegistry.add_cluster(cluster)
    return {"status": "added", "cluster": cluster.to_dict()}


@app.post("/api/clusters/{cluster_id}/activate")
async def activate_cluster(cluster_id: str):
    """Set a cluster as active."""
    if PluginRegistry.set_active_cluster(cluster_id):
        cluster = PluginRegistry.get_cluster(cluster_id)
        return {"status": "activated", "cluster": cluster.to_dict()}
    raise HTTPException(status_code=404, detail="Cluster not found")


@app.get("/api/clusters/active")
async def get_active_cluster():
    """Get the currently active cluster."""
    cluster = PluginRegistry.get_active_cluster()
    if cluster:
        return cluster.to_dict()
    return None


# =============================================================================
# Plugin Registry Status
# =============================================================================

@app.get("/api/registry/status")
async def registry_status():
    """Get overall plugin registry status."""
    return PluginRegistry.get_status()


# =============================================================================
# Manifest Management Endpoints
# =============================================================================

class ManifestRequest(BaseModel):
    name: str
    type: str
    description: str = ""
    icon: str = "🔌"
    enabled: bool = True
    config: dict = {}


@app.get("/api/manifests")
async def list_manifests():
    """List all plugin manifests."""
    from src.plugins.manifest import ManifestLoader
    import os
    
    config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
    loader = ManifestLoader(config_dir)
    manifests = loader.load_all()
    
    return {
        "manifests": [m.to_dict() for m in manifests],
        "config_dir": str(config_dir)
    }


@app.post("/api/manifests")
async def create_manifest(request: ManifestRequest):
    """Create a new plugin manifest."""
    from src.plugins.manifest import ManifestLoader, PluginManifest
    import os
    
    config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
    
    manifest = PluginManifest(
        name=request.name,
        type=request.type,
        description=request.description,
        icon=request.icon,
        enabled=request.enabled,
        config=request.config
    )
    
    loader = ManifestLoader(config_dir)
    if loader.save_manifest(manifest):
        return {"status": "created", "manifest": manifest.to_dict()}
    raise HTTPException(status_code=500, detail="Failed to save manifest")


@app.post("/api/manifests/reload")
async def reload_manifests():
    """Reload all plugins from manifests."""
    import os
    
    # Clear existing plugins
    for plugin_id in list(PluginRegistry._plugins.keys()):
        PluginRegistry.remove_plugin(plugin_id)
    
    config_dir = os.path.join(os.path.dirname(__file__), 'config', 'plugins')
    loaded = PluginRegistry.load_from_manifests(config_dir)
    
    # Re-activate first cluster
    clusters = PluginRegistry.get_all_clusters()
    if clusters:
        PluginRegistry.set_active_cluster(clusters[0].cluster_id)
    
    return {
        "status": "reloaded",
        "plugins_loaded": loaded,
        "registry": PluginRegistry.get_status()
    }


# =============================================================================
# ACI (Agent-Cloud Interface) Endpoints - REAL DATA
# =============================================================================

class ACILogsRequest(BaseModel):
    namespace: str = "default"
    pod_name: Optional[str] = None
    severity: str = "all"
    duration_minutes: int = 30
    limit: int = 100


class ACIMetricsRequest(BaseModel):
    namespace: str = "default"
    metric_names: List[str] = ["cpu_usage", "memory_usage"]


class ACIEventsRequest(BaseModel):
    namespace: str = "default"
    event_type: str = "all"
    duration_minutes: int = 60
    limit: int = 50


class DiagnosisRequest(BaseModel):
    namespace: str = "default"
    query: str = "What is wrong with this namespace?"


@app.get("/api/aci/status")
async def aci_status():
    """Get ACI availability status."""
    return {
        "aci_available": ACI_AVAILABLE,
        "voting_available": VOTING_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/aci/logs")
async def get_aci_logs(request: ACILogsRequest):
    """Get logs via ACI."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": []}
    
    try:
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_logs(
            namespace=request.namespace,
            pod_name=request.pod_name,
            severity=request.severity,
            duration_minutes=request.duration_minutes,
            limit=request.limit
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": []}


@app.post("/api/aci/metrics")
async def get_aci_metrics(request: ACIMetricsRequest):
    """Get metrics via ACI (from Prometheus/CloudWatch)."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": {}}
    
    try:
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_metrics(
            namespace=request.namespace,
            metric_names=request.metric_names
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": {}}


@app.post("/api/aci/events")
async def get_aci_events(request: ACIEventsRequest):
    """Get K8s events via ACI."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available", "data": []}
    
    try:
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        result = aci.get_events(
            namespace=request.namespace,
            event_type=request.event_type if request.event_type != "all" else None,
            duration_minutes=request.duration_minutes,
            limit=request.limit
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/api/aci/telemetry/{namespace}")
async def get_aci_telemetry(namespace: str):
    """Get all telemetry data for a namespace (logs, metrics, events)."""
    if not ACI_AVAILABLE:
        return {"error": "ACI not available"}
    
    try:
        aci = AgentCloudInterface(cluster_name="testing-cluster", region="ap-southeast-1")
        
        # Collect all telemetry
        logs = aci.get_logs(namespace=namespace, severity="error", limit=20)
        metrics = aci.get_metrics(namespace=namespace)
        events = aci.get_events(namespace=namespace, event_type="Warning", limit=30)
        
        return {
            "namespace": namespace,
            "timestamp": datetime.utcnow().isoformat(),
            "logs": logs.to_dict(),
            "metrics": metrics.to_dict(),
            "events": events.to_dict()
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/aci/diagnosis")
async def run_diagnosis(request: DiagnosisRequest):
    """Run multi-agent diagnosis on a namespace."""
    if not ACI_AVAILABLE or not VOTING_AVAILABLE:
        return {"error": "ACI or Voting not available"}
    
    try:
        from scripts.diagnosis.run_diagnosis import DiagnosisRunner
        
        runner = DiagnosisRunner(namespace=request.namespace)
        report = runner.run_diagnosis()
        
        return {
            "status": "success",
            "report": report
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


# =============================================================================
# Issue Management API
# =============================================================================

def get_issue_manager():
    """Get or create IssueManager instance."""
    global _issue_manager
    if not ISSUES_AVAILABLE:
        return None
    if _issue_manager is None:
        _issue_manager = IssueManager()
    return _issue_manager


def get_runbook_executor():
    """Get or create RunbookExecutor instance."""
    global _runbook_executor
    if not RUNBOOK_AVAILABLE:
        return None
    if _runbook_executor is None:
        _runbook_executor = RunbookExecutor()
    return _runbook_executor


@app.get("/api/issues")
async def list_issues(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    namespace: Optional[str] = None,
    limit: int = 50
):
    """List issues with optional filters."""
    manager = get_issue_manager()
    if not manager:
        return {"error": "Issue Manager not available", "issues": []}
    
    try:
        issues = manager.list_issues(
            status=status,
            severity=severity,
            namespace=namespace,
            limit=limit
        )
        return {"issues": [i.to_dict() for i in issues]}
    except Exception as e:
        return {"error": str(e), "issues": []}


@app.get("/api/issues/dashboard")
async def get_issues_dashboard():
    """Get dashboard summary data."""
    manager = get_issue_manager()
    if not manager:
        return {"error": "Issue Manager not available"}
    
    try:
        data = manager.get_dashboard_data()
        return data
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/issues/{issue_id}")
async def get_issue(issue_id: str):
    """Get issue by ID."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")
    
    issue = manager.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    return issue.to_dict()


class IssueCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str = "medium"
    namespace: str = "default"
    resource_type: str = "Pod"
    resource_name: str = ""
    root_cause: Optional[str] = None
    remediation: Optional[str] = None
    pattern_id: Optional[str] = None
    auto_fixable: bool = False


class IssueUpdateRequest(BaseModel):
    status: Optional[str] = None
    severity: Optional[str] = None
    root_cause: Optional[str] = None
    remediation: Optional[str] = None


@app.post("/api/issues")
async def create_issue(request: IssueCreateRequest):
    """Create a new issue."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")
    
    try:
        from src.issues import IssueType
        
        # Map pattern_id to IssueType
        type_map = {
            "oom_killed": IssueType.OOM_KILLED,
            "cpu_throttling": IssueType.CPU_THROTTLING,
            "crash_loop": IssueType.CRASH_LOOP,
            "image_pull_error": IssueType.IMAGE_PULL_ERROR,
            "memory_pressure": IssueType.MEMORY_PRESSURE,
        }
        issue_type = type_map.get(request.pattern_id, IssueType.UNKNOWN)
        
        issue = manager.create_issue(
            issue_type=issue_type,
            title=request.title,
            namespace=request.namespace,
            resource=request.resource_name,
            description=request.description or "",
            symptoms=[request.root_cause] if request.root_cause else [],
            metadata={
                "resource_type": request.resource_type,
                "root_cause": request.root_cause,
                "remediation": request.remediation,
                "auto_fixable": request.auto_fixable,
                "pattern_id": request.pattern_id
            }
        )
        return issue.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/issues/{issue_id}")
async def update_issue(issue_id: str, request: IssueUpdateRequest):
    """Update issue fields."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")
    
    try:
        from src.issues import IssueStatus, Severity
        
        status = IssueStatus(request.status) if request.status else None
        severity = Severity(request.severity) if request.severity else None
        
        issue = manager.update_issue(
            issue_id=issue_id,
            status=status,
            severity=severity,
            root_cause=request.root_cause,
            remediation=request.remediation
        )
        
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        return issue.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/issues/{issue_id}/fix")
async def fix_issue(issue_id: str):
    """Trigger auto-fix for an issue."""
    manager = get_issue_manager()
    executor = get_runbook_executor()
    
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")
    
    issue = manager.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    
    if not issue.auto_fixable:
        raise HTTPException(status_code=400, detail="Issue is not auto-fixable")
    
    # Find and execute runbook
    if executor:
        try:
            # Try to find runbook for this issue's type
            pattern_id = issue.metadata.get("pattern_id") or issue.type.value if hasattr(issue.type, 'value') else str(issue.type)
            
            context = {
                "namespace": issue.namespace,
                "resource_type": issue.metadata.get("resource_type", "Pod"),
                "resource_name": issue.resource,
                "container_name": "main",
            }
            
            execution = executor.execute_for_pattern(pattern_id, context, issue_id=issue_id)
            
            if execution:
                # Record fix attempt
                manager.record_fix_attempt(
                    issue_id=issue_id,
                    action=execution.runbook_id,
                    result=f"Execution {execution.execution_id}: {execution.status.value}",
                    success=execution.status.value == "success",
                )
                
                return {
                    "status": "initiated",
                    "execution_id": execution.execution_id,
                    "runbook_id": execution.runbook_id,
                }
            else:
                return {"status": "no_runbook", "message": "No runbook found for this issue"}
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    return {"status": "no_executor", "message": "Runbook executor not available"}


# =============================================================================
# Health Check API
# =============================================================================

def get_health_scheduler():
    """Get or create health scheduler."""
    global _health_scheduler
    if not HEALTH_AVAILABLE:
        return None
    if _health_scheduler is None:
        config = HealthCheckConfig(
            enabled=False,  # Don't auto-start
            interval_seconds=60,
        )
        _health_scheduler = HealthCheckScheduler(config=config)
    return _health_scheduler


@app.get("/api/health/check")
async def run_health_check(namespace: Optional[str] = None):
    """Run health check now."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available"}
    
    try:
        result = scheduler.run_now()
        return result.to_dict()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health/status")
async def get_health_status():
    """Get health check scheduler status."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available"}
    
    return scheduler.get_status()


@app.get("/api/health/history")
async def get_health_history(limit: int = 10):
    """Get health check history."""
    scheduler = get_health_scheduler()
    if not scheduler:
        return {"error": "Health Checker not available", "history": []}
    
    return {"history": scheduler.get_history(limit=limit)}


# =============================================================================
# Runbook API
# =============================================================================

@app.get("/api/runbooks")
async def list_runbooks():
    """List available runbooks."""
    executor = get_runbook_executor()
    if not executor:
        return {"error": "Runbook Executor not available", "runbooks": []}
    
    return {"runbooks": executor.loader.list_runbooks()}


@app.get("/api/runbooks/executions")
async def list_runbook_executions(limit: int = 10):
    """List recent runbook executions."""
    executor = get_runbook_executor()
    if not executor:
        return {"error": "Runbook Executor not available", "executions": []}
    
    return {"executions": executor.list_executions(limit=limit)}


# =============================================================================
# AWS Resource APIs (with mock fallback)
# =============================================================================

def get_aws_client(service_name: str):
    """Get AWS client, returns None if not configured."""
    try:
        import boto3
        return boto3.client(service_name)
    except Exception:
        return None


@app.get("/api/aws/ec2")
async def list_ec2_instances():
    """List EC2 instances."""
    client = get_aws_client('ec2')
    
    if client:
        try:
            response = client.describe_instances()
            instances = []
            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    name = next((t['Value'] for t in instance.get('Tags', []) if t['Key'] == 'Name'), 'Unnamed')
                    instances.append({
                        'id': instance['InstanceId'],
                        'name': name,
                        'type': instance['InstanceType'],
                        'state': instance['State']['Name'],
                        'az': instance.get('Placement', {}).get('AvailabilityZone', 'N/A'),
                        'cpu': 0,  # Would need CloudWatch for real metrics
                    })
            running = sum(1 for i in instances if i['state'] == 'running')
            stopped = sum(1 for i in instances if i['state'] == 'stopped')
            return {
                'instances': instances,
                'stats': {'total': len(instances), 'running': running, 'stopped': stopped}
            }
        except Exception as e:
            pass  # Fall through to mock data
    
    # Mock data for demo
    return {
        'instances': [
            {'id': 'i-0abc123def456', 'name': 'web-server-1', 'type': 't3.medium', 'state': 'running', 'az': 'us-east-1a', 'cpu': 45},
            {'id': 'i-0def456abc789', 'name': 'api-server-1', 'type': 't3.large', 'state': 'running', 'az': 'us-east-1b', 'cpu': 62},
            {'id': 'i-0ghi789jkl012', 'name': 'db-server-1', 'type': 'r5.xlarge', 'state': 'running', 'az': 'us-east-1a', 'cpu': 78},
            {'id': 'i-0mno345pqr678', 'name': 'worker-1', 'type': 't3.small', 'state': 'stopped', 'az': 'us-east-1c', 'cpu': 0},
            {'id': 'i-0stu901vwx234', 'name': 'batch-processor', 'type': 'm5.large', 'state': 'running', 'az': 'us-east-1b', 'cpu': 33},
        ],
        'stats': {'total': 5, 'running': 4, 'stopped': 1}
    }


@app.get("/api/aws/lambda")
async def list_lambda_functions():
    """List Lambda functions."""
    client = get_aws_client('lambda')
    
    if client:
        try:
            response = client.list_functions()
            functions = []
            for fn in response.get('Functions', []):
                functions.append({
                    'name': fn['FunctionName'],
                    'runtime': fn.get('Runtime', 'N/A'),
                    'memory': fn.get('MemorySize', 0),
                    'timeout': fn.get('Timeout', 0),
                    'invocations': 0,  # Would need CloudWatch
                })
            return {'functions': functions}
        except Exception:
            pass
    
    # Mock data
    return {
        'functions': [
            {'name': 'api-handler', 'runtime': 'python3.11', 'memory': 256, 'timeout': 30, 'invocations': 1250},
            {'name': 'image-processor', 'runtime': 'nodejs18.x', 'memory': 512, 'timeout': 60, 'invocations': 340},
            {'name': 'notification-sender', 'runtime': 'python3.11', 'memory': 128, 'timeout': 15, 'invocations': 890},
            {'name': 'data-transformer', 'runtime': 'python3.12', 'memory': 1024, 'timeout': 120, 'invocations': 456},
            {'name': 'auth-validator', 'runtime': 'nodejs20.x', 'memory': 256, 'timeout': 10, 'invocations': 2100},
        ]
    }


@app.get("/api/aws/s3")
async def list_s3_buckets():
    """List S3 buckets."""
    client = get_aws_client('s3')
    
    if client:
        try:
            response = client.list_buckets()
            buckets = []
            for bucket in response.get('Buckets', []):
                buckets.append({
                    'name': bucket['Name'],
                    'region': 'us-east-1',  # Would need additional call
                    'objects': 0,
                    'size': 'N/A',
                    'public': False,
                })
            return {'buckets': buckets}
        except Exception:
            pass
    
    # Mock data
    return {
        'buckets': [
            {'name': 'prod-assets-bucket', 'region': 'us-east-1', 'objects': 12450, 'size': '45.2 GB', 'public': False},
            {'name': 'logs-archive-bucket', 'region': 'us-east-1', 'objects': 89230, 'size': '128.5 GB', 'public': False},
            {'name': 'static-website-bucket', 'region': 'us-east-1', 'objects': 234, 'size': '1.2 GB', 'public': True},
            {'name': 'backup-daily-bucket', 'region': 'us-west-2', 'objects': 567, 'size': '89.7 GB', 'public': False},
        ]
    }


@app.get("/api/aws/rds")
async def list_rds_instances():
    """List RDS database instances."""
    client = get_aws_client('rds')
    
    if client:
        try:
            response = client.describe_db_instances()
            instances = []
            for db in response.get('DBInstances', []):
                instances.append({
                    'id': db['DBInstanceIdentifier'],
                    'engine': db['Engine'],
                    'status': db['DBInstanceStatus'],
                    'class': db['DBInstanceClass'],
                    'storage': db.get('AllocatedStorage', 0),
                })
            return {'instances': instances}
        except Exception:
            pass
    
    # Mock data
    return {
        'instances': [
            {'id': 'prod-mysql-primary', 'engine': 'mysql', 'status': 'available', 'class': 'db.r5.large', 'storage': 500},
            {'id': 'prod-postgres-main', 'engine': 'postgres', 'status': 'available', 'class': 'db.r5.xlarge', 'storage': 1000},
            {'id': 'analytics-redshift', 'engine': 'redshift', 'status': 'available', 'class': 'dc2.large', 'storage': 2000},
        ]
    }


@app.get("/api/aws/scan")
async def scan_aws_resources():
    """Scan all AWS resources and return summary with potential issues."""
    ec2_data = await list_ec2_instances()
    lambda_data = await list_lambda_functions()
    s3_data = await list_s3_buckets()
    rds_data = await list_rds_instances()
    
    # Detect potential issues
    issues = []
    
    # Check EC2 - high CPU
    for instance in ec2_data.get('instances', []):
        if instance.get('cpu', 0) > 70:
            issues.append({
                'resource': f"EC2: {instance['name']}",
                'severity': 'high' if instance['cpu'] > 85 else 'medium',
                'issue': f"High CPU utilization: {instance['cpu']}%",
                'recommendation': 'Consider scaling up or investigating workload'
            })
    
    # Check S3 - public buckets
    for bucket in s3_data.get('buckets', []):
        if bucket.get('public'):
            issues.append({
                'resource': f"S3: {bucket['name']}",
                'severity': 'high',
                'issue': 'Bucket has public access enabled',
                'recommendation': 'Review bucket policy and disable public access if not needed'
            })
    
    return {
        'summary': {
            'ec2': {'count': len(ec2_data.get('instances', [])), 'running': ec2_data.get('stats', {}).get('running', 0)},
            'lambda': {'count': len(lambda_data.get('functions', []))},
            's3': {'count': len(s3_data.get('buckets', []))},
            'rds': {'count': len(rds_data.get('instances', []))},
        },
        'issues': issues,
        'scanned_at': datetime.now().isoformat()
    }


# =============================================================================
# Proactive Agent System (OpenClaw-inspired)
# =============================================================================

from src.proactive_agent import get_proactive_system, ProactiveResult

# Initialize proactive system
proactive_system = get_proactive_system()

@app.on_event("startup")
async def startup_proactive_system():
    """Start proactive agent system on server startup."""
    await proactive_system.start()
    print("🚀 Proactive Agent System started")

@app.on_event("shutdown")
async def shutdown_proactive_system():
    """Stop proactive agent system on server shutdown."""
    await proactive_system.stop()
    print("🛑 Proactive Agent System stopped")

@app.get("/api/proactive/status")
async def get_proactive_status():
    """Get proactive system status."""
    return proactive_system.get_status()

class ProactiveToggleRequest(BaseModel):
    task_name: str
    enabled: bool

@app.post("/api/proactive/toggle")
async def toggle_proactive_task(request: ProactiveToggleRequest):
    """Enable or disable a proactive task."""
    proactive_system.enable_task(request.task_name, request.enabled)
    return {"status": "ok", "task": request.task_name, "enabled": request.enabled}

class ProactiveIntervalRequest(BaseModel):
    task_name: str
    interval_seconds: int

@app.post("/api/proactive/interval")
async def update_proactive_interval(request: ProactiveIntervalRequest):
    """Update proactive task interval."""
    proactive_system.update_task_interval(request.task_name, request.interval_seconds)
    return {"status": "ok", "task": request.task_name, "interval": request.interval_seconds}

class EventTriggerRequest(BaseModel):
    event_type: str
    event_data: dict = {}

@app.post("/api/proactive/trigger")
async def trigger_proactive_event(request: EventTriggerRequest):
    """Trigger an event-driven proactive task (e.g., CloudWatch alert)."""
    result = await proactive_system.trigger_event(request.event_type, request.event_data)
    return {
        "task_name": result.task_name,
        "status": result.status,
        "summary": result.summary,
        "findings": result.findings,
        "timestamp": result.timestamp.isoformat()
    }

@app.get("/api/proactive/results")
async def get_proactive_results():
    """Get pending proactive results (alerts)."""
    results = []
    while not proactive_system.results_queue.empty():
        try:
            result: ProactiveResult = proactive_system.results_queue.get_nowait()
            results.append({
                "task_name": result.task_name,
                "status": result.status,
                "summary": result.summary,
                "findings": result.findings,
                "timestamp": result.timestamp.isoformat()
            })
        except:
            break
    return {"results": results, "count": len(results)}


# =============================================================================
# Notification APIs
# =============================================================================

@app.get("/api/notifications/status")
async def get_notification_status():
    """Get notification system status."""
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()
        return manager.get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/notifications/test")
async def send_test_notification():
    """Send a test notification."""
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()
        
        if not manager.is_configured():
            return {"success": False, "error": "No notification channels configured"}
        
        result = manager.send_alert(
            title="Test Alert",
            message="This is a test notification from AgenticAIOps",
            level="info"
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


class AlertRequest(BaseModel):
    title: str
    message: str
    level: str = "warning"
    details: Optional[Dict[str, Any]] = None


@app.post("/api/notifications/send")
async def send_notification(request: AlertRequest):
    """Send a custom notification."""
    try:
        from src.notifications import get_notification_manager
        manager = get_notification_manager()
        
        result = manager.send_alert(
            title=request.title,
            message=request.message,
            level=request.level,
            details=request.details
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Operations Knowledge (Incident Learning + Pattern Management)
# =============================================================================

@app.get("/api/knowledge/stats")
async def get_ops_knowledge_stats():
    """Get operations knowledge statistics."""
    try:
        from src.operations_knowledge import get_knowledge_store
        store = get_knowledge_store()
        return store.get_stats()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/knowledge/patterns")
async def list_ops_patterns(
    service: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50
):
    """List learned patterns."""
    try:
        from src.operations_knowledge import get_knowledge_store
        store = get_knowledge_store()
        patterns = store.search_patterns(
            service=service,
            category=category,
            severity=severity,
            limit=limit
        )
        return {
            "patterns": [p.to_dict() for p in patterns],
            "count": len(patterns)
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/knowledge/search")
async def search_ops_knowledge(request: Dict[str, Any]):
    """Search operations knowledge base."""
    try:
        from src.operations_knowledge import get_knowledge_store
        store = get_knowledge_store()
        
        keywords = request.get('keywords', [])
        if isinstance(keywords, str):
            keywords = keywords.split()
        
        patterns = store.search_patterns(
            service=request.get('service'),
            category=request.get('category'),
            keywords=keywords,
            limit=request.get('limit', 10)
        )
        return {
            "patterns": [p.to_dict() for p in patterns],
            "count": len(patterns)
        }
    except Exception as e:
        return {"error": str(e)}


class IncidentLearnRequest(BaseModel):
    incident_id: str
    title: str
    description: str
    service: str
    severity: str
    symptoms: List[str] = []
    root_cause: str = ""
    resolution: str = ""
    resolution_steps: List[str] = []


@app.post("/api/knowledge/learn")
async def learn_from_incident(request: IncidentLearnRequest):
    """Learn pattern from a resolved incident."""
    try:
        from src.operations_knowledge import get_incident_learner, IncidentRecord
        learner = get_incident_learner()
        
        incident = IncidentRecord(
            incident_id=request.incident_id,
            title=request.title,
            description=request.description,
            service=request.service,
            severity=request.severity,
            symptoms=request.symptoms,
            root_cause=request.root_cause,
            resolution=request.resolution,
            resolution_steps=request.resolution_steps
        )
        
        pattern = learner.learn_from_incident(incident)
        
        if pattern:
            # Save the pattern
            from src.operations_knowledge import get_knowledge_store
            store = get_knowledge_store()
            store.save_pattern(pattern)
            
            return {
                "success": True,
                "pattern_id": pattern.pattern_id,
                "title": pattern.title,
                "confidence": pattern.confidence,
                "is_new": len(pattern.source_incidents) == 1
            }
        else:
            return {"success": False, "error": "Failed to learn pattern"}
    except Exception as e:
        return {"success": False, "error": str(e)}


class FeedbackRequest(BaseModel):
    pattern_id: str
    helpful: bool
    comment: str = ""


@app.post("/api/knowledge/feedback")
async def submit_pattern_feedback(request: FeedbackRequest):
    """Submit feedback for a pattern."""
    try:
        from src.operations_knowledge import get_feedback_handler
        handler = get_feedback_handler()
        
        success = handler.submit_feedback(
            request.pattern_id,
            request.helpful,
            request.comment
        )
        
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# SOP System APIs
# =============================================================================

@app.get("/api/sop/list")
async def list_sops(
    service: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None
):
    """List available SOPs."""
    try:
        from src.sop_system import get_sop_store
        store = get_sop_store()
        sops = store.list_sops(service=service, category=category, severity=severity)
        return {
            "sops": [s.to_dict() for s in sops],
            "count": len(sops)
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/sop/{sop_id}")
async def get_sop(sop_id: str):
    """Get SOP details."""
    try:
        from src.sop_system import get_sop_store
        store = get_sop_store()
        sop = store.get_sop(sop_id)
        if not sop:
            return {"error": f"SOP {sop_id} not found"}
        return sop.to_dict()
    except Exception as e:
        return {"error": str(e)}


class SOPSuggestRequest(BaseModel):
    service: str
    keywords: List[str] = []
    severity: Optional[str] = None


@app.post("/api/sop/suggest")
async def suggest_sops(request: SOPSuggestRequest):
    """Suggest SOPs for an issue."""
    try:
        from src.sop_system import get_sop_store
        store = get_sop_store()
        suggested = store.suggest_sops(
            request.service,
            request.keywords,
            request.severity
        )
        return {
            "suggestions": [s.to_dict() for s in suggested],
            "count": len(suggested)
        }
    except Exception as e:
        return {"error": str(e)}


class SOPExecuteRequest(BaseModel):
    sop_id: str
    triggered_by: str = "api"
    context: Dict[str, Any] = {}


@app.post("/api/sop/execute")
async def execute_sop(request: SOPExecuteRequest):
    """Start executing an SOP."""
    try:
        from src.sop_system import get_sop_executor
        executor = get_sop_executor()
        
        execution = executor.start_execution(
            request.sop_id,
            request.triggered_by,
            request.context
        )
        
        if not execution:
            return {"success": False, "error": "SOP not found or execution failed"}
        
        return {
            "success": True,
            "execution_id": execution.execution_id,
            "status": execution.status
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/sop/execution/{execution_id}")
async def get_sop_execution(execution_id: str):
    """Get SOP execution status."""
    try:
        from src.sop_system import get_sop_executor
        executor = get_sop_executor()
        
        execution = executor.get_execution(execution_id)
        if not execution:
            return {"error": "Execution not found"}
        
        return execution.to_dict()
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Vector Search APIs (Semantic Search)
# =============================================================================

@app.get("/api/vector/stats")
async def get_vector_stats():
    """Get vector search index statistics."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()
        return search.get_stats()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/vector/index/create")
async def create_vector_index():
    """Create the knowledge vector index."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()
        success = search.create_index()
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


class VectorIndexRequest(BaseModel):
    doc_id: str
    title: str
    description: str
    content: str
    doc_type: str  # pattern, sop, runbook
    category: str = ""
    service: str = ""
    severity: str = ""
    tags: List[str] = []


@app.post("/api/vector/index")
async def index_document(request: VectorIndexRequest):
    """Index a document with embeddings."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()
        
        success = search.index_knowledge(
            doc_id=request.doc_id,
            title=request.title,
            description=request.description,
            content=request.content,
            doc_type=request.doc_type,
            category=request.category,
            service=request.service,
            severity=request.severity,
            tags=request.tags
        )
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


class SemanticSearchRequest(BaseModel):
    query: str
    doc_type: Optional[str] = None
    service: Optional[str] = None
    limit: int = 5


@app.post("/api/vector/search")
async def semantic_search(request: SemanticSearchRequest):
    """Semantic search using vector similarity."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()
        
        results = search.semantic_search(
            query=request.query,
            doc_type=request.doc_type,
            service=request.service,
            limit=request.limit
        )
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/vector/hybrid-search")
async def hybrid_search(request: SemanticSearchRequest):
    """Hybrid search combining keyword and vector similarity."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()
        
        results = search.hybrid_search(
            query=request.query,
            doc_type=request.doc_type,
            service=request.service,
            limit=request.limit
        )
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# S3 Knowledge Base (Pattern Storage + RCA)
# =============================================================================

from src.s3_knowledge_base import get_knowledge_base, AnomalyPattern

@app.get("/api/kb/stats")
async def get_kb_stats():
    """Get knowledge base statistics."""
    kb = await get_knowledge_base()
    return kb.get_stats()

@app.get("/api/kb/patterns")
async def list_patterns(
    resource_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50
):
    """List patterns in the knowledge base."""
    kb = await get_knowledge_base()
    patterns = await kb.search_patterns(
        resource_type=resource_type,
        severity=severity,
        limit=limit
    )
    return {
        "patterns": [p.to_dict() for p in patterns],
        "count": len(patterns)
    }

@app.get("/api/kb/patterns/{pattern_id}")
async def get_pattern(pattern_id: str):
    """Get a specific pattern by ID."""
    kb = await get_knowledge_base()
    pattern = await kb.get_pattern(pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return pattern.to_dict()

class PatternAddRequest(BaseModel):
    title: str
    description: str
    resource_type: str
    severity: str = "medium"
    symptoms: List[str] = []
    root_cause: str = ""
    remediation: str = ""
    tags: List[str] = []
    quality_score: float = 0.8

@app.post("/api/kb/patterns")
async def add_pattern(request: PatternAddRequest):
    """Add a new pattern to the knowledge base."""
    kb = await get_knowledge_base()
    pattern = AnomalyPattern(
        pattern_id="",  # Will be generated
        title=request.title,
        description=request.description,
        resource_type=request.resource_type,
        severity=request.severity,
        symptoms=request.symptoms,
        root_cause=request.root_cause,
        remediation=request.remediation,
        tags=request.tags,
    )
    success = await kb.add_pattern(pattern, quality_score=request.quality_score)
    if not success:
        raise HTTPException(status_code=400, detail="Pattern rejected: quality score too low (< 0.7)")
    return {"status": "ok", "pattern_id": pattern.pattern_id}

class RCARequest(BaseModel):
    id: str = ""
    title: str
    description: str = ""
    resource_type: str

@app.post("/api/kb/rca")
async def perform_rca(request: RCARequest):
    """Perform Root Cause Analysis using pattern matching."""
    kb = await get_knowledge_base()
    issue = {
        "id": request.id or "unknown",
        "title": request.title,
        "description": request.description,
        "resource_type": request.resource_type,
    }
    result = await kb.match_pattern(issue)
    return {
        "issue_id": result.issue_id,
        "matched_pattern": result.matched_pattern.to_dict() if result.matched_pattern else None,
        "confidence": result.confidence,
        "analysis": result.analysis,
        "recommendations": result.recommendations,
        "timestamp": result.timestamp
    }


# =============================================================================
# AWS Cloud Scanner (Full Resource Discovery)
# =============================================================================


# Current scanner state
_monitored_resources: List[Dict[str, Any]] = []

@app.get("/api/scanner/account")
async def get_account_info():
    """Get current AWS account information."""
    scanner = get_scanner(_current_region)
    return scanner.get_account_info()

@app.get("/api/scanner/regions")
async def list_regions():
    """List available AWS regions."""
    scanner = get_scanner(_current_region)
    regions = scanner.list_regions()
    # Add common regions at top
    common = ["ap-southeast-1", "us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1"]
    return {
        "current": _current_region,
        "common": common,
        "all": regions,
    }

class SetRegionRequest(BaseModel):
    region: str

@app.post("/api/scanner/region")
async def set_region(request: SetRegionRequest):
    """Set the current region for scanning."""
    global _current_region
    _current_region = request.region
    return {"status": "ok", "region": _current_region}

@app.get("/api/scanner/scan")
async def scan_all_resources(region: Optional[str] = None):
    """Perform full cloud scan of all AWS resources."""
    scan_region = region or _current_region
    scanner = get_scanner(scan_region)
    return scanner.scan_all_resources()

@app.get("/api/scanner/service/{service}")
async def scan_service(service: str, region: Optional[str] = None):
    """Scan a specific AWS service."""
    scan_region = region or _current_region
    scanner = get_scanner(scan_region)
    
    service_scanners = {
        "ec2": scanner._scan_ec2,
        "lambda": scanner._scan_lambda,
        "s3": scanner._scan_s3,
        "rds": scanner._scan_rds,
        "iam": scanner._scan_iam,
        "eks": scanner._scan_eks,
        "cloudwatch": scanner._scan_cloudwatch_alarms,
    }
    
    if service not in service_scanners:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")
    
    return {
        "service": service,
        "region": scan_region,
        "data": service_scanners[service](),
    }

# Monitoring endpoints

class MonitorResourceRequest(BaseModel):
    resource_id: str
    resource_type: str
    name: str = ""
    service: str

@app.post("/api/scanner/monitor")
async def add_to_monitoring(request: MonitorResourceRequest):
    """Add a resource to the monitoring list."""
    global _monitored_resources
    
    # Check if already monitored
    for r in _monitored_resources:
        if r["resource_id"] == request.resource_id:
            return {"status": "already_monitored", "resource_id": request.resource_id}
    
    _monitored_resources.append({
        "resource_id": request.resource_id,
        "resource_type": request.resource_type,
        "name": request.name,
        "service": request.service,
        "added_at": datetime.now().isoformat(),
    })
    
    return {"status": "ok", "resource_id": request.resource_id, "total_monitored": len(_monitored_resources)}

@app.delete("/api/scanner/monitor/{resource_id}")
async def remove_from_monitoring(resource_id: str):
    """Remove a resource from monitoring."""
    global _monitored_resources
    _monitored_resources = [r for r in _monitored_resources if r["resource_id"] != resource_id]
    return {"status": "ok", "resource_id": resource_id, "total_monitored": len(_monitored_resources)}

@app.get("/api/scanner/monitored")
async def list_monitored_resources():
    """List all monitored resources."""
    return {"resources": _monitored_resources, "count": len(_monitored_resources)}

# CloudWatch Metrics/Logs endpoints

@app.get("/api/cloudwatch/metrics/ec2/{instance_id}")
async def get_ec2_metrics(instance_id: str, metric: str = "CPUUtilization", hours: int = 1):
    """Get CloudWatch metrics for an EC2 instance."""
    scanner = get_scanner(_current_region)
    return scanner.get_ec2_metrics(instance_id, metric, hours)

@app.get("/api/cloudwatch/metrics/rds/{db_id}")
async def get_rds_metrics(db_id: str, metric: str = "CPUUtilization", hours: int = 1):
    """Get CloudWatch metrics for an RDS instance."""
    scanner = get_scanner(_current_region)
    return scanner.get_rds_metrics(db_id, metric, hours)

@app.get("/api/cloudwatch/metrics/lambda/{function_name}")
async def get_lambda_metrics(function_name: str, metric: str = "Duration", hours: int = 1):
    """Get CloudWatch metrics for a Lambda function."""
    scanner = get_scanner(_current_region)
    return scanner.get_lambda_metrics(function_name, metric, hours)

class CloudWatchLogsRequest(BaseModel):
    log_group: str
    filter_pattern: str = ""
    limit: int = 100
    hours: int = 1

@app.post("/api/cloudwatch/logs")
async def get_cloudwatch_logs(request: CloudWatchLogsRequest):
    """Get CloudWatch logs."""
    scanner = get_scanner(_current_region)
    return scanner.get_cloudwatch_logs(
        request.log_group,
        request.filter_pattern,
        request.limit,
        request.hours,
    )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
