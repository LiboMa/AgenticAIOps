# AgenticAIOps - 当前架构文档

> 最后更新: 2026-02-12
> 版本: v2 (Agent-First Architecture)

## 1. 系统概述

AgenticAIOps 是基于 AWS 的智能运维平台，采用 Agent-First 架构，通过 Chat 交互实现 AWS 云资源的统一管理和自动化运维。

## 2. 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React + Ant Design + Vite |
| 后端 | Python FastAPI (Uvicorn) |
| AI/LLM | AWS Bedrock (Claude Opus 4) |
| 向量搜索 | OpenSearch 2.17 + Titan Embeddings |
| 知识库 | S3 + OpenSearch |
| 监控 | CloudWatch |
| 通知 | Slack Webhooks |
| 版本管理 | Git (GitHub) |

## 3. 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Web UI (React + Ant Design)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ AgentChat│ │ScanConfig│ │ Metrics  │ │Diagnosis │ │ Settings │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       └─────────────┴────────────┴─────────────┴────────────┘       │
│                               │ REST API                             │
└───────────────────────────────┼──────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI - api_server.py)                  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Chat Handler (自然语言命令解析)                                │   │
│  │ ├── EC2 命令: health, start, stop, reboot, metrics           │   │
│  │ ├── RDS 命令: health, reboot, failover                       │   │
│  │ ├── Lambda 命令: list, invoke, logs                          │   │
│  │ ├── Networking: vpc, elb, route53                            │   │
│  │ ├── SOP 命令: list, show, suggest, run                      │   │
│  │ ├── KB 命令: stats, search, semantic, index                  │   │
│  │ └── 通用: scan, health, anomaly, help                       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐       │
│  │ AWS Scanner│ │ AWS Ops    │ │ SOP System │ │ Vector     │       │
│  │ (13 服务)  │ │ (6 操作)   │ │ (3 内置SOP)│ │ Search     │       │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘       │
│        │              │              │              │               │
│  ┌─────┴──────────────┴──────────────┴──────────────┴─────────┐    │
│  │ Core Modules                                                │    │
│  │ ├── aws_scanner.py      → 资源扫描 (13 AWS 服务)           │    │
│  │ ├── aws_ops.py          → 运维操作 (EC2/RDS/Lambda)        │    │
│  │ ├── sop_system.py       → SOP 管理和执行                   │    │
│  │ ├── operations_knowledge.py → 知识库管理                    │    │
│  │ ├── vector_search.py    → 向量搜索 (OpenSearch)            │    │
│  │ ├── notifications.py    → Slack 告警通知                    │    │
│  │ ├── proactive_agent.py  → 主动巡检                         │    │
│  │ ├── multi_agent_voting.py→ 多Agent投票决策                  │    │
│  │ ├── bedrock_agent.py    → LLM 交互                         │    │
│  │ ├── s3_knowledge_base.py→ S3 知识库                        │    │
│  │ └── pattern_rag.py      → Pattern RAG 分析                 │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                      │
│  │ ACI Layer  │ │ Plugin Sys │ │ Issue Mgr  │                      │
│  │ (Agent-    │ │ (EC2/EKS   │ │ (Issue     │                      │
│  │  Cloud     │ │  plugins)  │ │  Tracking) │                      │
│  │  Interface)│ │            │ │            │                      │
│  └────────────┘ └────────────┘ └────────────┘                      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────────┐
    │    AWS API   │ │OpenSearch│ │    S3        │
    │  (Boto3)     │ │  (os2)   │ │ Knowledge   │
    │  13 Services │ │ k-NN     │ │ Base        │
    └──────────────┘ └──────────┘ └──────────────┘

```

## 4. 支持的 AWS 服务 (13个)

| 服务 | 扫描 | 健康检查 | 操作 |
|------|------|---------|------|
| EC2 | ✅ | ✅ | start/stop/reboot |
| RDS | ✅ | ✅ | reboot/failover |
| Lambda | ✅ | ✅ | invoke |
| S3 | ✅ | ✅ | - |
| EKS | ✅ | ✅ | - |
| VPC | ✅ | ✅ | - |
| ELB/ALB | ✅ | ✅ | - |
| Route53 | ✅ | ✅ | - |
| DynamoDB | ✅ | ✅ | - |
| ECS | ✅ | ✅ | - |
| ElastiCache | ✅ | ✅ | - |
| CloudWatch | ✅ | ✅ | - |
| IAM | ✅ | - | - |

## 5. 闭环知识系统

```
┌──────────┐    ┌─────────────┐    ┌──────────────┐
│ Collection│───▶│   Pattern   │───▶│ S3 + OpenSearch│
│   Agent   │    │ Recognition │    │  向量存储      │
└──────────┘    └─────────────┘    └──────┬───────┘
     │                                     │
     │         ┌───────────────────────────┘
     │         │
     │         ▼
     │    ┌─────────┐         ┌─────────┐
     └───▶│ Detect  │────────▶│   RCA   │
          │  Agent  │         │  Agent  │
          └────┬────┘         └────┬────┘
               │                   │
               └─────────┬─────────┘
                         │
                         ▼
                  ┌────────────┐
                  │   Action   │
                  │   + 反馈   │──────▶ 回流到 Pattern
                  └────────────┘
```

## 6. API 端点 (70+)

### 核心 API
- `POST /api/chat` - Chat 交互入口
- `GET /health` - 健康检查

### AWS 扫描 API
- `GET /api/scanner/scan` - 全资源扫描
- `GET /api/scanner/service/{service}` - 单服务扫描
- `GET /api/scanner/account` - 账户信息
- `POST /api/scanner/region` - 切换区域

### CloudWatch API
- `GET /api/cloudwatch/metrics/ec2/{id}` - EC2 指标
- `GET /api/cloudwatch/metrics/rds/{id}` - RDS 指标
- `GET /api/cloudwatch/metrics/lambda/{name}` - Lambda 指标

### 知识库 API
- `GET /api/knowledge/stats` - 知识库统计
- `POST /api/knowledge/search` - 搜索知识
- `POST /api/knowledge/learn` - 学习新知识
- `POST /api/knowledge/feedback` - 反馈

### SOP API
- `GET /api/sop/list` - SOP 列表
- `GET /api/sop/{id}` - SOP 详情
- `POST /api/sop/suggest` - SOP 推荐
- `POST /api/sop/execute` - 执行 SOP

### 向量搜索 API
- `POST /api/vector/search` - 语义搜索
- `POST /api/vector/hybrid-search` - 混合搜索
- `POST /api/vector/index/create` - 创建索引

### RCA API
- `GET /api/rca/reports` - RCA 报告
- `POST /api/rca/reports` - 创建 RCA
- `POST /api/aci/diagnosis` - 诊断分析

### 其他 API
- `GET /api/issues` - Issue 管理
- `GET /api/proactive/status` - 主动巡检状态
- `GET /api/notifications/status` - 通知状态

## 7. 前端页面

| 页面 | 功能 |
|------|------|
| AgentChat | Chat 交互主页面 |
| ScanConfig | AWS 资源扫描配置 |
| Metrics | 监控指标 |
| CloudServices | 云服务总览 |
| Diagnosis | 诊断分析 |
| SecurityDashboard | 安全面板 |
| ObservabilityList | 可观测性列表 |
| IssueCenterPD | Issue 中心 |
| Settings | 系统设置 |

## 8. 开发进度

### P0 Sprint (100% ✅)
- Networking 服务 (VPC/ELB/Route53)
- EC2 Operations (start/stop/reboot)
- Frontend Scan 优化

### P1 Sprint (100% ✅)
- DynamoDB/ECS/ElastiCache 支持
- RDS Operations (reboot/failover)
- Lambda Operations (invoke)
- Slack 告警通知系统
- Health 超时优化

### P2 Sprint (90% ⏳)
- Knowledge Base Enhancement
- SOP 系统 (3 内置 SOP)
- Vector Search (S3 + OpenSearch)
- 待完成: OpenSearch 向量索引测试

### Git Commits: 30+

## 9. 部署架构

```
┌─────────────────────────────────────┐
│ EC2: mbot-sg-1 (m6i.xlarge)        │
│ ├── Backend (Port 8000)             │
│ ├── Frontend (Port 5173)            │
│ └── Region: ap-southeast-1          │
│                                     │
│ OpenSearch: os2                     │
│ ├── 3x r7g.large.search            │
│ └── Engine: OpenSearch 2.17         │
│                                     │
│ S3: agentic-aiops-knowledge-base    │
│ IAM Role: iam-mbot-role (Admin)     │
└─────────────────────────────────────┘
```

## 10. 已知限制

1. 单账户设计 - 无多账户 AssumeRole
2. 单实例部署 - 无 HA
3. 无操作审批流程
4. 无 RBAC 权限分层
5. Chat Handler 使用 if-else 链
6. 无 dry-run 模式

---
*文档生成: AgenticAIOps Team @ 2026-02-12*
