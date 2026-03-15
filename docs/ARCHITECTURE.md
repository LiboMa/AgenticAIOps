# AgenticAIOps — 系统架构文档

**版本:** v3.3  
**更新日期:** 2026-03-08  
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
| **ProactiveAgent** | `src/proactive_agent.py` | 498 | 定时巡检，调度 DetectAgent |
| **DetectAgent** | `src/detect_agent.py` | 689 | 采集 + 缓存 + Pattern Match + 异常分发 |
| **EventCorrelator** | `src/event_correlator.py` | 729 | AWS 数据采集 (CloudWatch/Trail/Health) |
| **IncidentOrchestrator** | `src/incident_orchestrator.py` | 660 | 闭环管道编排 |
| **RCA Inference** | `src/rca_inference.py` | 368 | Bedrock Claude 根因分析 |
| **RCA-SOP Bridge** | `src/rca_sop_bridge.py` | 614 | RCA→SOP 映射 |
| **SOP System** | `src/sop_system.py` | 757 | SOP 定义、推荐、执行 |
| **SOP Safety** | `src/sop_safety.py` | 612 | 安全分级 (L1-L4) + dry_run |
| **Alarm Webhook** | `src/alarm_webhook.py` | 172 | CloudWatch Alarm 入口 |

### 3.2 知识 & 存储模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **KnowledgeSearch** | `src/knowledge_search.py` | 665 | 统一检索 (L1 keyword / L2 vector / L3 RAG) + legacy compat |
| **S3 KnowledgeBase** | `src/s3_knowledge_base.py` | 440 | S3 Pattern 持久化 |
| **Vector Search** | `src/vector_search.py` | 438 | OpenSearch kNN + Bedrock Titan Embeddings |

### 3.3 RCA 引擎模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **RCA Engine** | `src/rca/engine.py` | 338 | 投票式 RCA (multi-agent) |
| **Pattern Matcher** | `src/rca/pattern_matcher.py` | 351 | YAML 规则匹配 |
| **RCA Models** | `src/rca/models.py` | 157 | RCAResult / Severity / Remediation |
| **Network Context** | `src/rca/network_context.py` | 401 | 拓扑感知 RCA 上下文 (异常+可达性+爆炸半径+SG链) |

### 3.4 Topology 模块 (ACI 子系统)

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **Types** | `src/aci/topology/types.py` | ~95 | 拓扑数据模型 (Node/Edge/Graph) |
| **Engine** | `src/aci/topology/engine.py` | ~580 | VPC/Region/K8s 拓扑构建 |
| **Algorithms** | `src/aci/topology/algorithms.py` | ~420 | 可达性/影响半径/路径分析/异常检测 |
| **Collector** | `src/aci/topology/collector.py` | ~320 | boto3 数据采集 + PascalCase→snake_case |
| **Serializers** | `src/aci/topology/serializers.py` | ~100 | React Flow JSON 导出 |
| **Tools** | `src/aci/topology/tools.py` | ~65 | Agent 工具接口 |
| **API** | `src/aci/topology/api.py` | ~75 | 7 个 REST 端点 `/api/topology/*` |

### 3.5 Chaos Lab 模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **Engine** | `src/chaos/engine.py` | ~350 | 混沌实验编排 (安全护栏+auto_rollback) |
| **Models** | `src/chaos/models.py` | ~50 | 实验数据模型 |
| **Scenarios** | `src/chaos/scenarios.py` | ~400 | 5 种场景: resource_stress/network_block/pod_kill/config_break/node_drain |
| **API** | `src/chaos/api.py` | ~65 | 6 个 REST 端点 `/api/chaos/*` (dry_run=True 默认) |

### 3.6 HealthIssue 生命周期模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **Models** | `src/health_issue/models.py` | ~220 | HealthIssueStatus (7态) + FixPlan (L0-L3) |
| **Lifecycle** | `src/health_issue/lifecycle.py` | ~190 | 状态机 + 审批门控 + reopen/force_close |
| **Store** | `src/health_issue/store.py` | ~140 | JSON 持久化 |
| **Migration** | `src/health_issue/migration.py` | ~120 | IssueStatus/IncidentStatus → HealthIssueStatus 映射 |

### 3.7 基础设施模块

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **API Server** | `api_server.py` | 169 | FastAPI 入口 (路由注册，22 个 router) |
| **Routers** | `routers/` | 22 文件 | 拆分后的 API 路由层 |
| **Chat Router** | `routers/chat.py` | 289 | Chat 入口 + agent factory |
| **Chat Intents** | `routers/chat_intents/` | 8 模块 ~2,445 行 | 领域意图处理 (health/resources/ops/rca/sop/knowledge/metrics/ui_actions) |
| **AWS Scanner** | `src/aws_scanner.py` | 737 | 13 服务资源扫描 |
| **AWS Ops** | `src/aws_ops.py` | 1,793 | EC2/RDS/Lambda CRUD (Chat 用) |
| **Config** | `src/config.py` | 81 | 环境配置 |
| **Intent Classifier** | `src/intent_classifier.py` | 160 | Chat 意图识别 |
| **Notifications** | `src/notifications.py` | 267 | Slack 告警 |
| **kubectl Wrapper** | `src/kubectl_wrapper.py` | 265 | K8s 操作封装 |

### 3.8 ACI (Agent-Cloud Interface)

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **ACI Interface** | `src/aci/interface.py` | 383 | Agent-Cloud 统一接口 |
| **MCP Bridge** | `src/aci/mcp_bridge.py` | 177 | MCP 协议桥接 |
| **Telemetry** | `src/aci/telemetry/` | ~880 | 指标/日志/事件/Prometheus |
| **Operations** | `src/aci/operations/` | ~255 | kubectl/shell 操作 |
| **Security** | `src/aci/security/` | ~320 | 审计 + 过滤 |

### 3.9 Skills Framework (Agent 能力系统)

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **SkillRegistry** | `src/skills/__init__.py` | ~93 | Skill 注册、发现、加载 |
| **Models** | `src/skills/_models.py` | ~53 | SecurityTier (T0-T3) + SkillManifest |
| **Security** | `src/skills/_security.py` | ~98 | `@secure_tool` 装饰器 + Tier 强制 |
| **Executor** | `src/skills/_executor.py` | ~61 | 安全执行器 (沙箱隔离) |
| **Agent Binding** | `src/skills/agent_binding.py` | ~57 | Agent → Skill 绑定映射 |
| **Kubernetes** | `src/skills/kubernetes/` | 3 文件 | K8s 工具 (kubectl 封装 + 安全策略) |
| **AWS General** | `src/skills/aws_general/tools.py` | ~89 | 30 @tools (16 read + 10 write + 4 dangerous) |
| **Monitoring** | `src/skills/monitoring/tools.py` | ~68 | CloudWatch 指标/告警查询 |
| **Linux Admin** | `src/skills/linux_admin/tools.py` | ~101 | 系统管理工具 |
| **Database** | `src/skills/database_admin/tools.py` | ~51 | RDS/DynamoDB 操作 |
| **Network** | `src/skills/network_engineer/tools.py` | ~73 | VPC/SG/Route 工具 |
| **Storage** | `src/skills/storage/tools.py` | ~47 | S3/EBS 存储工具 |
| **Log Analysis** | `src/skills/log_analysis/tools.py` | ~56 | CloudWatch Logs 分析 |

**安全分级体系:**
- **T0 (Read-Only)**: 只读查询，自动批准
- **T1 (Safe-Write)**: 安全写操作，自动批准
- **T2 (Risky-Write)**: 风险写操作，需审批
- **T3 (Dangerous)**: 危险操作，需 HMAC approval_token 验证

### 3.10 Alert Ingress 模块 (多源告警接入)

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **Alert Models** | `src/alert/models.py` | ~106 | 标准化告警数据模型 |
| **Alert Ingress** | `src/alert/ingress.py` | ~131 | 多源告警接入路由 + 归一化 |
| **Parser Base** | `src/alert/parsers/base.py` | ~47 | 告警解析器基类 |
| **CloudWatch Parser** | `src/alert/parsers/cloudwatch.py` | ~147 | CloudWatch Alarm 告警解析 |
| **Datadog Parser** | `src/alert/parsers/datadog.py` | ~79 | Datadog Webhook 告警解析 |
| **Grafana Parser** | `src/alert/parsers/grafana.py` | ~74 | Grafana Alert 告警解析 |
| **PagerDuty Parser** | `src/alert/parsers/pagerduty.py` | ~87 | PagerDuty 告警解析 |
| **Generic Parser** | `src/alert/parsers/generic.py` | ~87 | 通用告警解析器 (fallback) |

### 3.11 Knowledge Flywheel 模块 (知识飞轮)

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **Flywheel** | `src/knowledge/flywheel.py` | ~246 | 知识飞轮核心引擎 (Pattern→Index→Feedback 闭环) |
| **Case Study** | `src/knowledge/case_study.py` | ~95 | 案例沉淀 + 结构化存储 |
| **Vector Store** | `src/knowledge/vector_store.py` | ~204 | 向量存储抽象层 (Bedrock Titan Embeddings) |
| **Search** | `src/knowledge/search.py` | ~150 | 统一知识检索 (关键词 + 向量 + 混合) |

### 3.12 SOP AutoWriter (SOP 自动生成)

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **SOPAutoWriter** | `src/sop/auto_writer.py` | ~304 | 基于 RCA 结果自动生成 SOP (LLM 辅助) + 去重 + 评审 |

### 3.13 Skills Iteration 模块 (能力自主进化)

| 模块 | 文件 | 行数 | 功能 |
|------|------|------|------|
| **SkillGapDetector** | `src/skills/iteration/gap_detector.py` | ~203 | 技能缺口检测 (基于事件反馈分析) |
| **SkillValidator** | `src/skills/iteration/validator.py` | ~251 | 新技能验证 (沙箱测试 + 安全审查) |
| **SpecBuilder** | `src/skills/iteration/spec_builder.py` | ~142 | 技能规格自动构建器 |
| **Guard** | `src/skills/iteration/guard.py` | ~80 | 技能迭代护栏 (频率限制 + 变更审批) |

### 3.14 其他

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
├── api_server.py              # FastAPI 入口 (169 行, 路由注册)
├── routers/                   # 22 个 API Router 模块
│   ├── chat.py                # Chat 入口 (289 行)
│   ├── chat_intents/          # 8 个领域意图处理模块
│   │   ├── __init__.py        # registry-dict dispatcher
│   │   ├── health.py          # 健康检查意图
│   │   ├── resources.py       # 资源查询意图
│   │   ├── operations.py      # 运维操作意图
│   │   ├── rca.py             # RCA 分析意图
│   │   ├── sop.py             # SOP 推荐意图
│   │   ├── knowledge.py       # 知识库查询意图
│   │   ├── metrics.py         # 指标查询意图
│   │   └── ui_actions.py      # UI 动作意图
│   ├── health_issues.py       # HealthIssue 生命周期 API
│   ├── incident.py            # 事件管理 API
│   ├── aws.py                 # AWS 操作 API
│   └── ...                    # 其他 18 个 router
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
│   ├── utils/time.py          # 时间工具
│   ├── rca/                   # RCA 引擎 + Pattern Matcher + Network Context
│   ├── aci/                   # Agent-Cloud Interface
│   │   └── topology/          # VPC/Region/K8s 拓扑分析 (NetworkX)
│   ├── chaos/                 # 混沌实验 Lab (5 种场景)
│   ├── health_issue/          # HealthIssue 7 状态生命周期
│   ├── alert/                 # 多源告警接入
│   │   ├── ingress.py         # 告警路由 + 归一化
│   │   ├── models.py          # 标准化告警模型
│   │   └── parsers/           # 解析器 (CloudWatch/Datadog/Grafana/PagerDuty/Generic)
│   ├── knowledge/             # 知识飞轮
│   │   ├── flywheel.py        # 闭环学习引擎
│   │   ├── case_study.py      # 案例沉淀
│   │   ├── vector_store.py    # 向量存储抽象层
│   │   └── search.py          # 统一知识检索
│   ├── sop/                   # SOP 子系统
│   │   └── auto_writer.py     # SOP 自动生成 (LLM 辅助)
│   ├── skills/                # Skills Framework (8 skills, 103 tools)
│   │   ├── __init__.py        # SkillRegistry
│   │   ├── _models.py         # SecurityTier + SkillManifest
│   │   ├── _security.py       # @secure_tool 装饰器
│   │   ├── _executor.py       # 安全执行器
│   │   ├── agent_binding.py   # Agent→Skill 绑定
│   │   ├── skill_bridge.py    # Architect SkillBridge
│   │   ├── iteration/         # 能力自主进化 (GapDetector/Validator/SpecBuilder/Guard)
│   │   ├── kubernetes/        # K8s 工具 + 安全策略
│   │   ├── aws_general/       # AWS 通用工具 (30 @tools)
│   │   ├── monitoring/        # 监控工具
│   │   ├── linux_admin/       # 系统管理
│   │   ├── database_admin/    # 数据库工具
│   │   ├── network_engineer/  # 网络工具
│   │   ├── storage/           # 存储工具
│   │   └── log_analysis/      # 日志分析
│   ├── plugins/               # 服务插件
│   ├── runbook/               # Runbook 系统
│   ├── issues/                # Issue 跟踪
│   ├── health/                # 健康检查
│   └── voting/                # Multi-Agent 投票
├── config/
│   ├── plugins/               # 插件配置 YAML
│   └── rca_patterns.yaml      # Pattern 规则 YAML
├── agents/                    # Agent manifests (5 roles)
├── dashboard/                 # React 前端 (AppV2.jsx, LobeChat 风格)
├── tests/                     # 测试 (3,135 cases, 87% 覆盖率)
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
| PatternMatcher 规则 | YAML 规则面向 K8s，需扩充 CloudWatch 场景 | P1 |
| ~~Heartbeat sync boto3~~ | ~~`detect_agent.run_detection()` 同步阻塞事件循环~~ (**已修复**: `run_in_executor`) | ~~P2~~ |
| aws_ops.py 0% 覆盖 | 1,793 行无测试 | P2 |
| Bedrock KB | PatternRAG 未接入 (需 KB ID 配置) | P2 |
| chat.py agent_factory | 可提取为独立模块 (289→~170 行) | P2 |
| 前端 ReactFlow | Topology 可视化未接入前端 | P2 |
| 无 RBAC | 所有用户同权限 | P3 |
| 单点部署 | 无 HA/灾备 | P3 |

---

*本文件是唯一的架构文档。其他版本已清理。*
