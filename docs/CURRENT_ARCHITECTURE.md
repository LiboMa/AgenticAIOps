# AgenticAIOps - Current Architecture Document

## 1. System Overview

AgenticAIOps 是一个 AI 驱动的多服务运维平台，通过自然语言交互实现 AWS 云资源的监控、诊断、操作和知识沉淀。

```
┌─────────────────────────────────────────────────────────────┐
│                    AgenticAIOps Architecture                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Web UI      │  │  Chat API   │  │  Slack Bot  │         │
│  │  (React)     │  │  (REST)     │  │  (Webhook)  │         │
│  └──────┬───────┘  └──────┬──────┘  └──────┬──────┘         │
│         └──────────────────┼──────────────────┘              │
│                            ▼                                 │
│              ┌─────────────────────────┐                     │
│              │     FastAPI Backend     │                     │
│              │     (api_server.py)     │                     │
│              └────────────┬────────────┘                     │
│                           │                                  │
│    ┌──────────┬───────────┼───────────┬──────────┐          │
│    ▼          ▼           ▼           ▼          ▼          │
│ ┌──────┐ ┌──────┐  ┌──────────┐ ┌──────┐ ┌──────────┐     │
│ │Scanner│ │ Ops  │  │Knowledge │ │ SOP  │ │  Vector  │     │
│ │Module │ │Module│  │  Module  │ │Module│ │  Search  │     │
│ └──┬───┘ └──┬───┘  └────┬─────┘ └──┬───┘ └────┬─────┘     │
│    │        │           │          │           │            │
│    └────────┼───────────┼──────────┼───────────┘            │
│             ▼           ▼          ▼                        │
│  ┌──────────────────────────────────────────────┐           │
│  │              AWS Services (boto3)             │           │
│  ├──────────────────────────────────────────────┤           │
│  │ EC2│RDS│Lambda│S3│EKS│VPC│ELB│Route53│       │           │
│  │ DynamoDB│ECS│ElastiCache│CloudWatch│IAM       │           │
│  └──────────────────────────────────────────────┘           │
│                                                              │
│  ┌──────────────────────────────────────────────┐           │
│  │        Storage Layer                          │           │
│  ├──────────┬──────────────┬────────────────────┤           │
│  │ S3       │ OpenSearch   │ Bedrock             │           │
│  │(Patterns)│ (Vectors)    │ (Embeddings+LLM)   │           │
│  └──────────┴──────────────┴────────────────────┘           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 2. Module Details

### 2.1 Backend (api_server.py)
- **Framework**: FastAPI
- **Port**: 8000
- **Features**: Chat handler, REST APIs, WebSocket, CORS

### 2.2 Scanner Module (aws_scanner.py)
**Supported Services (13):**

| Category | Services | Status |
|----------|----------|--------|
| Compute | EC2, Lambda, EKS | ✅ |
| Database | RDS, DynamoDB | ✅ |
| Storage | S3, ElastiCache | ✅ |
| Networking | VPC, ELB, Route53 | ✅ |
| Container | ECS | ✅ |
| Security | IAM | ✅ |

### 2.3 Operations Module (aws_ops.py)
**Supported Operations (6):**

| Operation | Service | Command |
|-----------|---------|---------|
| Start Instance | EC2 | `ec2 start <id>` |
| Stop Instance | EC2 | `ec2 stop <id>` |
| Reboot Instance | EC2 | `ec2 reboot <id>` |
| Reboot DB | RDS | `rds reboot <id>` |
| Failover DB | RDS | `rds failover <id>` |
| Invoke Function | Lambda | `lambda invoke <name>` |

### 2.4 Knowledge Module (operations_knowledge.py)
- **IncidentLearner**: Auto-learn patterns from incidents
- **LearnedPattern**: Enhanced pattern model with categories
- **PatternFeedback**: Feedback-based improvement
- **KnowledgeStore**: Local + S3 sync
- **Categories**: performance, availability, security, cost, configuration

### 2.5 SOP Module (sop_system.py)
- **SOPStore**: YAML-based SOP management
- **SOPExecutor**: Step-by-step execution tracking
- **Built-in SOPs**:
  - `sop-ec2-high-cpu`: EC2 High CPU Response (5 steps)
  - `sop-rds-failover`: RDS Planned Failover (6 steps)
  - `sop-lambda-errors`: Lambda Error Investigation (6 steps)

### 2.6 Vector Search Module (vector_search.py)
- **Storage**: S3 (raw data) + OpenSearch (vectors)
- **Embeddings**: Bedrock Titan v2 (1024 dimensions)
- **Search**: kNN (HNSW + Cosine) + Hybrid Search
- **Cluster**: os2 (3 nodes, OpenSearch 2.17)

### 2.7 Notification Module (notifications.py)
- **Channel**: Slack Webhook
- **Features**: Alert levels, test notifications
- **Command**: `notification status`, `test notification`

### 2.8 Additional Modules

| Module | File | Description |
|--------|------|-------------|
| RCA Engine | `src/rca/` | Root Cause Analysis with pattern matching |
| Runbook | `src/runbook/` | YAML runbook definitions and execution |
| Multi-Agent Voting | `src/multi_agent_voting.py` | Consensus-based decision making |
| Proactive Agent | `src/proactive_agent.py` | Background monitoring tasks |
| Plugin System | `src/plugins/` | EC2, EKS, Lambda, HPC plugins |
| Intent Classifier | `src/intent_classifier.py` | NLP-based command classification |
| ACI Layer | `src/aci/` | Agent-Computer Interface |

## 3. Frontend (React Dashboard)

```
dashboard/src/
├── pages/
│   ├── AgentChat.jsx      # Chat interface
│   ├── CloudServices.jsx  # AWS services overview
│   ├── Diagnosis.jsx      # Health diagnostics
│   └── ScanConfig.jsx     # Scan configuration
├── components/
│   ├── ChatPanel.jsx      # Chat UI component
│   ├── DynamicDashboard.jsx # A2UI dynamic widgets
│   ├── Anomalies.jsx      # Anomaly display
│   ├── RCAReports.jsx     # RCA report display
│   ├── EKSStatus.jsx      # EKS cluster status
│   └── PluginManager.jsx  # Plugin management
└── main.jsx
```

## 4. Chat Commands

### Health & Monitoring
```
health / 健康                → Full health check
EC2/RDS/Lambda/S3 health   → Service-specific health
anomaly / 异常              → Anomaly detection
```

### Resource Management
```
scan / 扫描                 → Full resource scan
show EC2/Lambda/S3/RDS     → Resource listing
vpc / elb / route53         → Networking
dynamodb / ecs / elasticache → Extended services
```

### Operations
```
ec2 start/stop/reboot <id>  → EC2 operations
rds reboot/failover <id>    → RDS operations
lambda invoke <name>         → Lambda invocation
```

### Knowledge & SOP
```
kb stats                     → Knowledge base statistics
kb search <query>            → Keyword search
kb semantic <query>          → Semantic search (OpenSearch)
sop list                     → List SOPs
sop show/run/suggest <id>   → SOP operations
feedback <id> good/bad       → Pattern feedback
```

### Notifications
```
notification status          → Alert system status
test notification            → Send test alert
send alert <message>         → Custom alert
```

## 5. API Endpoints

### Core APIs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Backend health check |
| POST | `/api/chat` | Chat message handler |
| GET | `/api/scan` | Resource scan |
| GET | `/api/services/{service}` | Service details |

### Knowledge APIs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/knowledge/stats` | Knowledge stats |
| GET | `/api/knowledge/patterns` | List patterns |
| POST | `/api/knowledge/search` | Search patterns |
| POST | `/api/knowledge/learn` | Learn from incident |
| POST | `/api/knowledge/feedback` | Submit feedback |

### SOP APIs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sop/list` | List SOPs |
| GET | `/api/sop/{id}` | SOP details |
| POST | `/api/sop/suggest` | Suggest SOPs |
| POST | `/api/sop/execute` | Execute SOP |
| GET | `/api/sop/execution/{id}` | Execution status |

### Vector Search APIs
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/vector/search` | Semantic search |
| POST | `/api/vector/hybrid-search` | Hybrid search |
| POST | `/api/vector/index` | Index document |
| POST | `/api/vector/index/create` | Create index |

## 6. Closed-Loop Architecture

```
┌──────────┐    ┌──────────┐    ┌──────────────┐
│Collection│───▶│ Pattern  │───▶│S3 + OpenSearch│
│  Agent   │    │Recognition│   │(Vector Store) │
└──────────┘    └──────────┘    └──────┬───────┘
     ▲                                 │
     │         ┌───────────────────────┘
     │         ▼
     │    ┌─────────┐         ┌─────────┐
     │    │ Detect  │────────▶│   RCA   │
     │    │ Agent   │         │  Agent  │
     │    └────┬────┘         └────┬────┘
     │         │                   │
     │         └─────────┬─────────┘
     │                   ▼
     │            ┌────────────┐
     └────────────│  Action +  │
                  │  Feedback  │
                  └────────────┘
```

## 7. Infrastructure

| Resource | Spec | Region |
|----------|------|--------|
| Backend EC2 | m6i.xlarge | ap-southeast-1 |
| OpenSearch | 3x r7g.large.search | ap-southeast-1 |
| S3 Bucket | agentic-aiops-knowledge-base | ap-southeast-1 |
| IAM Role | iam-mbot-role + ExtraServicesPolicy | Global |
| LLM | Bedrock Claude (chat) + Titan (embeddings) | Global |

## 8. Git Statistics

- **Branch**: v2-agent-first
- **Total Commits**: 50+
- **Sprint Completion**: P0 ✅, P1 ✅, P2 90%
