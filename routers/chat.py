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


async def handle_aws_chat_intent(message: str) -> Optional[str]:
    """Handle AWS-related chat intents directly."""
    message_lower = message.lower()
    
    scanner = get_scanner(get_current_region())
    
    # Import AWS Ops for health/metrics/logs
    try:
        from src.aws_ops import get_aws_ops
        ops = get_aws_ops(get_current_region())
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

当前 Region: **{get_current_region()}** | 支持服务: **13**"""
    
    # ===========================================
    # Health Check Commands
    # ===========================================
    
    # EC2 Health Check
    if any(kw in message_lower for kw in ['ec2 health', 'ec2 健康', 'check ec2', '检查 ec2', 'ec2 status']):
        if not ops:
            return "❌ AWS Ops module not available"
        try:
            health = ops.ec2_health_check()
            response = f"""🏥 **EC2 健康检查** (Region: {get_current_region()})

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
            response = f"""🏥 **RDS 健康检查** (Region: {get_current_region()})

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
            response = f"""🏥 **Lambda 健康检查** (Region: {get_current_region()})

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
            
            correlator = get_correlator(get_current_region())
            
            # Parse optional service filter
            services = None
            for svc in ['ec2', 'rds', 'lambda']:
                if svc in message_lower:
                    services = [svc]
                    break
            
            # Run async collection
            event = await correlator.collect(services=services, lookback_minutes=15)
            
            return event.summary()
        except Exception as e:
            logger.warning(f"Event correlator failed, falling back: {e}")
            # Fallback to original anomaly detection
            if not ops:
                return "❌ AWS Ops module not available"
        try:
            response = f"""🔍 **异常检测报告** (Region: {get_current_region()})

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
            response = f"""📊 **RDS Metrics Summary** (Region: {get_current_region()})

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
            response = f"""🏥 **AWS 服务健康状态** (Region: {get_current_region()})

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
            response = f"""🖥️ **EC2 Instances** (Region: {get_current_region()})

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
            response = f"""⚡ **Lambda Functions** (Region: {get_current_region()})

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
            response = f"""🗄️ **RDS Databases** (Region: {get_current_region()})

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
            response = f"""🏥 **VPC 健康检查** (Region: {get_current_region()})

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
            response = f"""🌐 **VPCs** (Region: {get_current_region()})

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
            response = f"""🏥 **ELB 健康检查** (Region: {get_current_region()})

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
            response = f"""⚖️ **Load Balancers** (Region: {get_current_region()})

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
            response = f"""🏥 **DynamoDB 健康检查** (Region: {get_current_region()})

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
            
            response = f"""📊 **DynamoDB Tables** (Region: {get_current_region()})

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
            response = f"""🏥 **ECS 健康检查** (Region: {get_current_region()})

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
            
            response = f"""🐳 **ECS Clusters** (Region: {get_current_region()})

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
            
            response = f"""🏥 **ElastiCache 健康检查** (Region: {get_current_region()})

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
            
            response = f"""🗄️ **ElastiCache Clusters** (Region: {get_current_region()})

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
            from src.knowledge_search import get_knowledge_store
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
            from src.knowledge_search import get_knowledge_store
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
            
            from src.knowledge_search import get_feedback_handler
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
    # Incident: Full closed-loop pipeline
    if any(kw in message_lower for kw in ['incident run', '事件处理', 'incident handle', 'closed loop', '闭环']):
        try:
            import asyncio, re
            from src.detect_agent import get_detect_agent
            
            # Parse options
            dry_run = 'dry' in message_lower or '预览' in message_lower
            auto_exec = 'auto' in message_lower or '自动' in message_lower
            force_refresh = 'refresh' in message_lower or '刷新' in message_lower
            
            # Parse lookback (e.g., "incident run 30min")
            lb_match = re.search(r'(\d+)\s*min', message, re.IGNORECASE)
            lookback = int(lb_match.group(1)) if lb_match else 15
            
            match = re.search(r'(?:incident|事件|闭环)\s+(?:run|handle|处理)?\s*(ec2|rds|lambda)?', message, re.IGNORECASE)
            service_filter = [match.group(1).lower()] if match and match.group(1) else None
            
            # Use DetectAgent: collect once, reuse cached data
            detect = get_detect_agent(get_current_region())
            incident = await detect.trigger_incident(
                    trigger_type="manual",
                    services=service_filter,
                    auto_execute=auto_exec,
                    dry_run=dry_run,
                    lookback_minutes=lookback,
                )
            
            return incident.to_markdown()
        except Exception as e:
            import traceback
            return f"❌ 事件处理失败: {str(e)}\n```\n{traceback.format_exc()[:500]}\n```"
    
    # Incident List
    if any(kw in message_lower for kw in ['incident list', '事件列表', 'incidents']):
        try:
            from src.incident_orchestrator import get_orchestrator
            
            orchestrator = get_orchestrator(get_current_region())
            incidents = orchestrator.list_incidents(limit=10)
            
            if not incidents:
                return "📋 暂无事件记录。使用 `incident run` 启动闭环分析。"
            
            response = f"📋 **事件列表** ({len(incidents)})\n\n"
            response += "| ID | 触发 | 状态 | 耗时 | 时间 |\n|-----|------|------|------|------|\n"
            for inc in incidents:
                status_icon = '✅' if inc['status'] == 'completed' else '❌' if inc['status'] == 'failed' else '⏳'
                response += f"| `{inc['incident_id'][:12]}` | {inc['trigger_type']} | {status_icon} {inc['status']} | {inc['duration_ms']}ms | {inc['created_at'][:19]} |\n"
            return response
        except Exception as e:
            return f"❌ 获取事件列表失败: {str(e)}"
    
    # Incident Stats
    if any(kw in message_lower for kw in ['incident stats', '事件统计']):
        try:
            from src.incident_orchestrator import get_orchestrator
            
            orchestrator = get_orchestrator(get_current_region())
            stats = orchestrator.get_stats()
            
            target_icon = '✅' if stats['within_target'] else '⚠️'
            
            response = f"""📊 **闭环管道统计**

| 指标 | 值 |
|------|-----|
| 总事件数 | {stats['total_incidents']} |
| 平均耗时 | {stats['avg_duration_ms']}ms |
| 目标 | {target_icon} {stats['target_ms']}ms |
"""
            if stats['by_status']:
                response += "\n**状态分布:**\n"
                for status, count in stats['by_status'].items():
                    response += f"- {status}: {count}\n"
            
            if stats['avg_stage_timings']:
                response += "\n**各阶段平均耗时:**\n\n"
                response += "| 阶段 | 耗时 |\n|------|------|\n"
                for stage, ms in stats['avg_stage_timings'].items():
                    response += f"| {stage} | {ms}ms |\n"
            
            return response
        except Exception as e:
            return f"❌ 获取统计失败: {str(e)}"
    
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
            correlator = get_correlator(get_current_region())
            event = await correlator.collect(services=service_filter, lookback_minutes=15)
            
            # Step 2: Claude inference
            engine = get_rca_inference_engine()
            rca_result = await engine.analyze(event)
            
            # Step 3: SOP suggestion
            bridge = get_bridge()
            sop_suggestions = bridge.match_sops(rca_result)
            
            # Build response
            from src.rca.models import Severity
            severity_icon = '🔴' if rca_result.severity == Severity.HIGH else '🟡' if rca_result.severity == Severity.MEDIUM else '🟢'
            
            # Build response
            response = f"""🔬 **深度 RCA 分析** (Region: {get_current_region()})

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
    
    # Safety Check: Dry-run / safety preview for SOP
    if any(kw in message_lower for kw in ['safety check', '安全检查', 'sop check', 'dry run', 'dry-run']):
        try:
            import re
            from src.sop_safety import get_safety_layer
            
            match = re.search(r'(?:safety check|安全检查|sop check|dry.run)\s*(\S*)', message, re.IGNORECASE)
            sop_id = match.group(1).strip() if match and match.group(1).strip() else None
            
            if not sop_id:
                return """🛡️ **安全检查 / Dry-Run**

用法: `safety check <sop_id>` 或 `dry run <sop_id>`

示例:
- `safety check sop-ec2-high-cpu`
- `dry run sop-rds-failover`
- `safety check sop-lambda-errors`

显示风险等级、执行模式、冷却状态。"""
            
            safety = get_safety_layer()
            check = safety.check(sop_id=sop_id, dry_run=True)
            return check.to_markdown()
        except Exception as e:
            return f"❌ 安全检查失败: {str(e)}"
    
    # Safety Stats
    if any(kw in message_lower for kw in ['safety stats', '安全统计', 'safety status']):
        try:
            from src.sop_safety import get_safety_layer
            import json
            
            safety = get_safety_layer()
            stats = safety.get_stats()
            
            return f"""🛡️ **安全层状态**

| 指标 | 值 |
|------|-----|
| 活跃冷却 | {stats['active_cooldowns']} |
| 状态快照 | {stats['snapshots_stored']} |
| 待审批 | {stats['pending_approvals']} |

**日执行次数:**
```
{json.dumps(stats['daily_execution_counts'], indent=2) if stats['daily_execution_counts'] else '(今日无执行)'}
```

**日执行上限:**

| 级别 | 上限 | 冷却期 |
|------|------|--------|
| L0 (只读) | {stats['daily_limits']['L0']} | 无 |
| L1 (低风险) | {stats['daily_limits']['L1']} | 5 分钟 |
| L2 (中风险) | {stats['daily_limits']['L2']} | 30 分钟 |
| L3 (高风险) | {stats['daily_limits']['L3']} | 1 小时 |
"""
        except Exception as e:
            return f"❌ 获取安全统计失败: {str(e)}"
    
    # Pending Approvals
    if any(kw in message_lower for kw in ['approvals', '审批列表', 'pending approvals']):
        try:
            from src.sop_safety import get_safety_layer
            
            safety = get_safety_layer()
            pending = safety.get_pending_approvals()
            
            if not pending:
                return "✅ 无待审批的 SOP 执行请求"
            
            response = f"🔐 **待审批 ({len(pending)})**\n\n"
            for a in pending:
                response += f"- `{a['approval_id']}`: **{a['sop_id']}** ({a['risk_level']}) — 请求人: {a['requested_by']}, 过期: {a['expires_at']}\n"
            response += "\n使用 `approve <approval_id>` 或 `reject <approval_id>` 处理"
            return response
        except Exception as e:
            return f"❌ 获取审批列表失败: {str(e)}"

    # Approve / Reject
    if any(kw in message_lower for kw in ['approve ', 'reject ']):
        try:
            import re
            from src.sop_safety import get_safety_layer
            
            safety = get_safety_layer()
            
            match = re.search(r'(approve|reject)\s+(\S+)', message, re.IGNORECASE)
            if not match:
                return "用法: `approve <approval_id>` 或 `reject <approval_id>`"
            
            action = match.group(1).lower()
            approval_id = match.group(2)
            
            if action == "approve":
                result = safety.approve(approval_id, approved_by="chat_user")
            else:
                result = safety.reject(approval_id, rejected_by="chat_user")
            
            if not result:
                return f"❌ 未找到审批请求: {approval_id}"
            
            status = "✅ 已批准" if result.approved else "❌ 已拒绝"
            return f"{status}: `{result.sop_id}` ({result.risk_level.value})"
        except Exception as e:
            return f"❌ 审批处理失败: {str(e)}"
    
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
- Current Region: `{get_current_region()}`"""
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

**🛡️ 安全机制 (NEW):**
- `safety check <sop_id>` - 安全检查 + Dry-Run 预览
- `safety stats` - 安全层状态 (冷却/计数/上限)
- `approvals` - 查看待审批列表 (L2/L3 SOP)
- `approve <id>` / `reject <id>` - 审批处理

**🔄 闭环管道 (NEW):**
- `incident run` - **完整闭环**: 采集→RCA→SOP匹配→安全检查
- `incident run ec2` / `incident run rds` - 指定服务
- `incident run auto` - 闭环 + 自动执行 L0/L1 SOP
- `incident run dry` - 预览模式 (不执行)
- `incident list` - 事件历史
- `incident stats` - 管道性能统计

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
