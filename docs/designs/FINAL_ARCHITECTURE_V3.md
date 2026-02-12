# AgenticAIOps 最终架构文档 v3.0

## 1. 项目概览

AgenticAIOps 是一个 AI 驱动的多服务云运维平台，通过多 Agent 协作实现自动化运维。

### 1.1 技术栈

| 层级 | 技术 |
|------|------|
| **Frontend** | React + Vite + Ant Design |
| **Backend** | Python + FastAPI |
| **AI** | Strands Agents + Amazon Bedrock |
| **向量搜索** | S3 + OpenSearch |
| **Embedding** | Bedrock Titan (1024维) |
| **基础设施** | AWS EKS + EC2 |

### 1.2 完成进度

```
P0 Sprint: ✅ 100% (2026-02-09)
P1 Sprint: ✅ 100% (2026-02-10)
P2 Sprint: ✅ 90% (2026-02-10, 待 OpenSearch 权限)

Total Commits: 30+
```

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         AgenticAIOps Platform                             │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────┐     ┌─────────────────────────────────────────────┐     │
│  │  Dashboard   │────▶│              Backend (FastAPI)              │     │
│  │  React +     │     │  ┌─────────┐  ┌──────────┐  ┌──────────┐  │     │
│  │  Ant Design  │     │  │ Chat    │  │ Scanner  │  │ Health   │  │     │
│  │              │     │  │ Handler │  │ Engine   │  │ Checker  │  │     │
│  │  Pages:      │     │  └────┬────┘  └────┬─────┘  └────┬─────┘  │     │
│  │  - AgentChat │     │       │            │             │        │     │
│  │  - ScanConfig│     │       ▼            ▼             ▼        │     │
│  │  - Metrics   │     │  ┌─────────────────────────────────────┐  │     │
│  │  - Diagnosis │     │  │           aws_ops.py (69KB)         │  │     │
│  │  - Security  │     │  │  EC2|RDS|Lambda|S3|EKS|IAM|CW|     │  │     │
│  │  - Overview  │     │  │  VPC|ELB|Route53|DynamoDB|ECS|     │  │     │
│  │              │     │  │  ElastiCache (13 services)          │  │     │
│  └─────────────┘     │  └──────────────┬──────────────────┘  │     │
│                       │                 │                      │     │
│                       │       ┌─────────┴─────────┐           │     │
│                       │       ▼                   ▼           │     │
│                       │  ┌──────────┐      ┌──────────────┐   │     │
│                       │  │ Strands  │      │ Bedrock      │   │     │
│                       │  │ Agent    │      │ Claude/Titan │   │     │
│                       │  └──────────┘      └──────────────┘   │     │
│                       └───────────────────────────────────────┘     │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │                    知识沉淀系统                                │     │
│  │  ┌────────────┐  ┌────────────┐  ┌──────────────────────┐   │     │
│  │  │ Knowledge  │  │   SOP      │  │   Vector Search      │   │     │
│  │  │ System     │  │  System    │  │ S3 + OpenSearch      │   │     │
│  │  │ (Pattern)  │  │ (Runbook)  │  │ (Titan Embedding)    │   │     │
│  │  └────────────┘  └────────────┘  └──────────────────────┘   │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │                    告警通知系统                                │     │
│  │  └── Slack Webhook → INFO/WARNING/ERROR/CRITICAL            │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 后端模块清单

| 模块 | 文件 | 大小 | 功能 |
|------|------|------|------|
| **AWS Operations** | `src/aws_ops.py` | 69KB | 13 服务的查询/健康检查/指标 |
| **AWS Scanner** | `src/aws_scanner.py` | 26KB | 全服务资源扫描 |
| **Bedrock Agent** | `src/bedrock_agent.py` | 19KB | Strands Agent 集成 |
| **Knowledge System** | `src/operations_knowledge.py` | 15KB | Pattern 学习/反馈/存储 |
| **SOP System** | `src/sop_system.py` | 20KB | SOP 定义/执行/推荐 |
| **Vector Search** | `src/vector_search.py` | 15KB | OpenSearch 向量搜索 |
| **Notifications** | `src/notifications.py` | 9KB | Slack 告警通知 |
| **S3 Knowledge Base** | `src/s3_knowledge_base.py` | 16KB | S3 知识存储 |
| **Intent Classifier** | `src/intent_classifier.py` | 5KB | 用户意图分类 |
| **Multi-Agent Voting** | `src/multi_agent_voting.py` | 8KB | 多 Agent 投票决策 |
| **Proactive Agent** | `src/proactive_agent.py` | 12KB | 主动巡检/告警 |
| **Pattern RAG** | `src/pattern_rag.py` | 7KB | 模式检索增强 |
| **Lambda/EKS Ops** | `src/lambda_eks_operations.py` | 16KB | Lambda/EKS 操作 |
| **Kubectl Wrapper** | `src/kubectl_wrapper.py` | 9KB | K8s 命令封装 |

---

## 4. 支持的 AWS 服务 (13/32)

| 服务 | 扫描 | 健康检查 | 指标 | 操作 |
|------|------|----------|------|------|
| EC2 | ✅ | ✅ | ✅ | start/stop/reboot |
| RDS | ✅ | ✅ | ✅ | reboot/failover |
| Lambda | ✅ | ✅ | ✅ | invoke |
| S3 | ✅ | ✅ | ✅ | - |
| EKS | ✅ | ✅ | ✅ | - |
| IAM | ✅ | ✅ | - | - |
| CloudWatch | ✅ | ✅ | ✅ | - |
| VPC | ✅ | ✅ | - | - |
| ELB | ✅ | ✅ | ✅ | - |
| Route53 | ✅ | ✅ | - | - |
| DynamoDB | ✅ | ✅ | ✅ | - |
| ECS | ✅ | ✅ | - | - |
| ElastiCache | ✅ | ✅ | - | - |

---

## 5. Chat 命令体系

### 5.1 资源查询

```
ec2 / rds / lambda / s3 / eks / iam
vpc / elb / route53 / dynamodb / ecs / elasticache
```

### 5.2 健康检查

```
health / health check / anomaly
ec2 health / rds health / lambda health / ...
vpc health / elb health / dynamodb health
```

### 5.3 运维操作 (6个)

```
ec2 start/stop/reboot <instance-id>
rds reboot/failover <db-id>
lambda invoke <function-name>
```

### 5.4 知识管理

```
kb stats / kb search <query> / kb semantic <query>
kb index
learn incident
feedback <id> good/bad
```

### 5.5 SOP 系统

```
sop list / sop show <id>
sop suggest <keywords>
sop run <id>
```

### 5.6 告警通知

```
notification status
test notification
send alert <message>
```

### 5.7 通用

```
help / scan / report
```

---

## 6. API Endpoints

### 6.1 Core

```
POST /api/chat             # Chat 对话
GET  /health               # 健康检查
POST /api/scan             # 全资源扫描
POST /api/health-check     # 健康检查
```

### 6.2 Knowledge

```
GET  /api/knowledge/stats
GET  /api/knowledge/patterns
POST /api/knowledge/search
POST /api/knowledge/learn
POST /api/knowledge/feedback
```

### 6.3 SOP

```
GET  /api/sop/list
GET  /api/sop/{sop_id}
POST /api/sop/suggest
POST /api/sop/execute
GET  /api/sop/execution/{id}
```

### 6.4 Vector Search

```
GET  /api/vector/stats
POST /api/vector/index/create
POST /api/vector/index
POST /api/vector/search
POST /api/vector/hybrid-search
```

### 6.5 Notifications

```
GET  /api/notifications/status
POST /api/notifications/test
POST /api/notifications/send
```

---

## 7. 闭环智能运维架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    闭环系统 (S3 + OpenSearch)                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Collection ──▶ Pattern ──▶ S3 + OpenSearch ──▶ Detect/RCA         │
│      ↑              (Titan Embedding)                ↓              │
│      └───────────────── Feedback 学习 ←─────── Action ┘             │
│                                                                      │
│  存储: S3 (原始 Pattern JSON)                                       │
│  索引: OpenSearch os2 (kNN 向量, HNSW, Cosine)                     │
│  嵌入: Bedrock Titan (1024维)                                      │
│  搜索: 语义搜索 + 混合搜索 (关键词+向量)                           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. 前端页面

| 页面 | 文件 | 功能 |
|------|------|------|
| Agent Chat | `AgentChat.jsx` | Chat 对话界面 |
| Scan Config | `ScanConfig.jsx` | 扫描配置 |
| Metrics | `Metrics.jsx` | 指标展示 |
| Diagnosis | `Diagnosis.jsx` | 诊断分析 |
| Security | `SecurityDashboard.jsx` | 安全仪表盘 |
| Overview | `OverviewPD.jsx` | 总览 |
| Cloud Services | `CloudServices.jsx` | 云服务管理 |
| Settings | `Settings.jsx` | 设置 |

---

## 9. Sprint 完成记录

### P0 Sprint (2026-02-09)

| Commit | 功能 |
|--------|------|
| 01a88a9 | Networking (VPC/ELB/Route53) |
| 0223d4e | EC2 Operations + Help |
| 5b4d215 | Frontend Scan 优化 |

### P1 Sprint (2026-02-10)

| Commit | 功能 |
|--------|------|
| 8bc3729 | DynamoDB + ECS |
| 43cae09 | IAM 错误处理优化 |
| 20528ef | ElastiCache |
| f20ed31 | RDS/Lambda Operations |
| 765efb5 | Slack 告警通知 |
| d2b2dc0 | Health 超时优化 |
| 4a84fbb | 语法错误修复 |

### P2 Sprint (2026-02-10)

| Commit | 功能 |
|--------|------|
| 5380583 | Knowledge System Phase 1 |
| 165e6aa | SOP System Phase 2 |
| 117ab2c | Vector Search Phase 3 |
| 10f2708 | OpenSearch auth 修复 |
| a895c6c | SOP handler 修复 |
| ba8a23e | f-string 修复 |
| ac5a262 | Knowledge/SOP 设计文档 |

---

## 10. 已知问题与待改进

### 10.1 待修复

- [ ] OpenSearch 权限配置 (Fine-Grained Access Control)
- [ ] DynamoDB/ECS/ElastiCache 需要 inline IAM policy

### 10.2 架构改进 (Brainstorming 结论)

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| P0 | 操作审批流程 | 敏感操作二次确认 |
| P0 | 审计日志 | 完整操作记录 |
| P1 | 多账户支持 | Cross-Account AssumeRole |
| P1 | HA 部署 | 避免单点故障 |
| P2 | RBAC | 角色权限分层 |
| P2 | Dry-run 模式 | 预览操作影响 |

---

**作者**: Architect
**日期**: 2026-02-12
**版本**: 3.0
