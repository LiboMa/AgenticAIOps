# AgenticAIOps — 系统架构文档

**版本:** v3.0  
**更新日期:** 2026-02-13  
**维护者:** AgenticAIOps Team  

---

## 1. 系统概述

AgenticAIOps 是 AI 驱动的多 Agent 云运维平台。核心理念：**采集一次，分析多次，执行闭环**。

```
┌─────────────────────────────────────────────────────────────┐
│                    AgenticAIOps Platform                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  📡 主动监控      → ProactiveAgent 定时巡检                   │
│  🔍 异常检测      → DetectAgent 采集 + 缓存 + Pattern Match  │
│  🧠 根因分析      → RCA (Bedrock Claude) + 向量检索增强       │
│  📋 标准化运维    → SOP 推荐 + Safety 分级 + 自动/人工执行    │
│  🔄 闭环学习      → Pattern → S3 + OpenSearch → Feedback      │
│  💬 自然语言交互  → Chat + REST API + WebUI                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 核心管道架构

### 2.1 闭环管道 (Closed-Loop Pipeline)

```
ProactiveAgent (定时巡检)          CloudWatch Alarm (事件触发)
       │                                    │
       ▼                                    ▼
┌─────────────────────────────────────────────────┐
│              DetectAgent                         │
│  EventCorrelator.collect()                       │
│  → CloudWatch Metrics + Alarms + CloudTrail      │
│  → 缓存 DetectResult (TTL 5min)                 │
│  → Pattern Match                                 │
│  → 持久化 (JSON + S3)                            │
└──────────────┬──────────────────────────────────┘
               │ DetectResult (含采集数据)
               ▼
┌─────────────────────────────────────────────────┐
│         IncidentOrchestrator                     │
│                                                  │
│  Stage 1: Data Collection                        │
│    R1: detect_result fresh → 复用 (0ms)          │
│    R1: detect_result stale → fallback fresh       │
│    R2: manual trigger → 总是 fresh               │
│                                                  │
│  Stage 2: RCA Analysis                           │
│    → rca_inference.py (Bedrock Claude)           │
│    → KnowledgeSearch 向量增强                     │
│                                                  │
│  Stage 3: SOP Match + Safety Check               │
│    → rca_sop_bridge.py → sop_system.py           │
│    → sop_safety.py (L1-L4 分级, dry_run)         │
│                                                  │
│  Stage 4: Execute / Approval                     │
│    → L1 auto-execute                             │
│    → L2+ require approval / dry_run              │
│                                                  │
│  Stage 5: Learn + Feedback                       │
│    → S3KnowledgeBase.add_pattern()               │
│    → VectorSearch.index()                        │
│    → OperationsKnowledge feedback                │
└─────────────────────────────────────────────────┘
```

### 2.2 数据复用规则

| 规则 | 条件 | 行为 |
|------|------|------|
| **R1** | `detect_result` 存在且 fresh (< TTL) | 跳过采集，直接分析 |
| **R1** | `detect_result` 存在但 stale (> TTL) | Fallback 重新采集 |
| **R2** | `trigger_type == "manual"` | 总是重新采集 |
| **R3** | 无 `detect_result` | 正常采集 |

---

## 3. 模块清单

### 3.1 核心管道模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **ProactiveAgent** | `src/proactive_agent.py` | 471 | 定时巡检，调度 DetectAgent |
| **DetectAgent** | `src/detect_agent.py` | 374 | 采集 + 缓存 + 异常分发 |
| **EventCorrelator** | `src/event_correlator.py` | 729 | AWS 数据采集 (CloudWatch/Trail/Health) |
| **IncidentOrchestrator** | `src/incident_orchestrator.py` | 660 | 闭环管道编排 |
| **RCA Inference** | `src/rca_inference.py` | 368 | Bedrock Claude 根因分析 |
| **RCA-SOP Bridge** | `src/rca_sop_bridge.py` | 515 | RCA→SOP 映射 |
| **SOP System** | `src/sop_system.py` | 757 | SOP 定义、推荐、执行 |
| **SOP Safety** | `src/sop_safety.py` | 612 | 安全分级 (L1-L4) + dry_run |
| **Alarm Webhook** | `src/alarm_webhook.py` | 172 | CloudWatch Alarm 入口 |

### 3.2 知识 & 存储模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **KnowledgeSearch** | `src/knowledge_search.py` | 375 | 统一检索 (L1 keyword / L2 vector / L3 RAG) |
| **S3 KnowledgeBase** | `src/s3_knowledge_base.py` | 440 | S3 Pattern 持久化 |
| **Vector Search** | `src/vector_search.py` | 438 | OpenSearch kNN + Bedrock Titan Embeddings |
| **Operations Knowledge** | `src/operations_knowledge.py` | 337 | 兼容 shim (→ knowledge_search) |

### 3.3 RCA 引擎模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **RCA Engine** | `src/rca/engine.py` | 338 | 投票式 RCA (multi-agent) |
| **Pattern Matcher** | `src/rca/pattern_matcher.py` | 351 | YAML 规则匹配 |
| **RCA Models** | `src/rca/models.py` | 157 | RCAResult / Severity / Remediation |

### 3.4 基础设施模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **API Server** | `api_server.py` | ~4,700 | FastAPI 主服务 |
| **AWS Scanner** | `src/aws_scanner.py` | 737 | 13 服务资源扫描 |
| **AWS Ops** | `src/aws_ops.py` | 1,793 | EC2/RDS/Lambda CRUD (Chat 用) |
| **Config** | `src/config.py` | 81 | 环境配置 |
| **Intent Classifier** | `src/intent_classifier.py` | 160 | Chat 意图识别 |
| **Notifications** | `src/notifications.py` | 267 | Slack 告警 |
| **kubectl Wrapper** | `src/kubectl_wrapper.py` | 265 | K8s 操作封装 |

### 3.5 ACI (Agent-Cloud Interface)

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **ACI Interface** | `src/aci/interface.py` | 383 | Agent-Cloud 统一接口 |
| **MCP Bridge** | `src/aci/mcp_bridge.py` | 177 | MCP 协议桥接 |
| **Telemetry** | `src/aci/telemetry/` | ~872 | 指标/日志/事件/Prometheus |
| **Operations** | `src/aci/operations/` | ~249 | kubectl/shell 操作 |
| **Security** | `src/aci/security/` | ~314 | 审计 + 过滤 |

### 3.6 其他

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **Voting** | `src/voting/` | 265+530 | Multi-Agent 投票决策 |
| **Plugins** | `src/plugins/` | ~1,539 | EC2/EKS/Lambda/HPC 插件 |
| **Runbook** | `src/runbook/` | ~772 | Runbook 加载/执行 |
| **Issues** | `src/issues/` | ~858 | Issue 跟踪 |
| **Health** | `src/health/` | ~887 | 定时健康检查 |

---

## 4. 技术栈

| 层级 | 技术 |
|------|------|
| **Frontend** | React + Vite + Ant Design |
| **Backend** | Python 3.12 + FastAPI + Uvicorn |
| **AI/LLM** | Amazon Bedrock (Claude Sonnet / Opus) |
| **Embeddings** | Bedrock Titan (1024 维) |
| **向量搜索** | OpenSearch 2.17 (kNN) |
| **存储** | S3 (Patterns + SOP) |
| **监控** | CloudWatch Metrics + Alarms + CloudTrail |
| **基础设施** | AWS EC2 (m6i.xlarge), ap-southeast-1 |

---

## 5. 支持的 AWS 服务 (13个)

| 服务 | Scanner | Operations | Health Check |
|------|---------|------------|--------------|
| EC2 | ✅ | ✅ start/stop/reboot | ✅ |
| RDS | ✅ | ✅ reboot/failover | ✅ |
| Lambda | ✅ | ✅ invoke | ✅ |
| S3 | ✅ | — | ✅ |
| VPC | ✅ | — | ✅ |
| ELB | ✅ | — | ✅ |
| Route53 | ✅ | — | ✅ |
| DynamoDB | ✅ | — | ✅ |
| ECS | ✅ | — | ✅ |
| ElastiCache | ✅ | — | ✅ |
| EKS | ✅ | — | ✅ |
| CloudWatch | ✅ | — | ✅ |
| IAM | ✅ | — | — |

---

## 6. 目录结构

```
agentic-aiops-mvp/
├── api_server.py              # FastAPI 主服务 (~4,700 行)
├── src/
│   ├── proactive_agent.py     # 主动巡检 Agent
│   ├── detect_agent.py        # 检测 Agent (采集+缓存+分发)
│   ├── event_correlator.py    # AWS 数据采集
│   ├── incident_orchestrator.py # 闭环管道编排
│   ├── rca_inference.py       # Bedrock RCA
│   ├── rca_sop_bridge.py      # RCA→SOP 映射
│   ├── sop_system.py          # SOP 管理
│   ├── sop_safety.py          # 安全分级
│   ├── knowledge_search.py    # 统一检索 (L1/L2/L3)
│   ├── s3_knowledge_base.py   # S3 存储
│   ├── vector_search.py       # OpenSearch 向量搜索
│   ├── alarm_webhook.py       # CloudWatch Alarm 入口
│   ├── aws_scanner.py         # 13 服务扫描
│   ├── aws_ops.py             # AWS 操作 (Chat 用)
│   ├── config.py              # 配置
│   ├── intent_classifier.py   # 意图分类
│   ├── notifications.py       # Slack 通知
│   ├── kubectl_wrapper.py     # K8s 封装
│   ├── operations_knowledge.py # 兼容 shim
│   ├── utils/time.py          # 时间工具
│   ├── rca/                   # RCA 引擎 + Pattern Matcher
│   ├── aci/                   # Agent-Cloud Interface
│   ├── plugins/               # 服务插件
│   ├── runbook/               # Runbook 系统
│   ├── issues/                # Issue 跟踪
│   ├── health/                # 健康检查
│   └── voting/                # Multi-Agent 投票
├── config/
│   ├── plugins/               # 插件配置 YAML
│   ├── sops/                  # SOP 定义 YAML
│   └── patterns/              # Pattern 规则 YAML
├── dashboard/                 # React 前端
├── tests/                     # 测试 (503+ cases)
└── docs/                      # 文档
    ├── ARCHITECTURE.md        # 本文件 (唯一架构文档)
    └── designs/               # 设计文档
```

---

## 7. 部署

```
EC2: mbot-sg-1 (m6i.xlarge, ap-southeast-1)
├── Backend:    FastAPI (port 8000)
├── Frontend:   React (port 3000)
├── OpenSearch: 3x r7g.large.search (v2.17)
├── S3:         agentic-aiops-knowledge-base
├── Bedrock:    Claude Sonnet + Titan Embeddings
└── IAM Role:   iam-mbot-role
```

---

## 8. 已知限制

| 限制 | 描述 | 优先级 |
|------|------|--------|
| 单账户 | 仅支持一个 AWS 账户 | P1 |
| DetectAgent → Pattern Match | 采集后未自动走 PatternMatcher | P1 |
| DetectAgent → Vectorize | 采集后未自动向量化存储 | P1 |
| S3 Bucket | `agentic-aiops-knowledge-base` 需手动创建 | P2 |
| api_server.py 过大 | ~4,700 行，待拆分 Router | P2 |
| 无 RBAC | 所有用户同权限 | P3 |
| 单点部署 | 无 HA/灾备 | P3 |

---

*本文件是唯一的架构文档。其他版本已清理。*
