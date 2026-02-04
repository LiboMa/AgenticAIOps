# V2 Architecture - Agent-First Cloud Observability

**Version**: 2.0  
**Author**: Architect  
**Date**: 2026-02-04  
**Branch**: v2-agent-first

---

## 1. Overview

AgenticAIOps v2 is an **Agent-First** cloud observability platform that focuses on:
- AI-driven monitoring (not replicating AWS Console)
- Proactive anomaly detection and RCA
- Multi-account, multi-region support

---

## 2. Core Flow

```
┌─────────────────────────────────────────────────────────────┐
│              v2 Core User Journey                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Step 1: Account Configuration                               │
│  ├── Add AWS Account (IAM Role ARN)                         │
│  ├── Backend assumes role via STS                           │
│  └── Verify permissions                                     │
│                                                              │
│  Step 2: Region Selection                                    │
│  ├── Select target region(s)                                │
│  └── Multi-region support                                   │
│                                                              │
│  Step 3: Full Cloud Scan                                     │
│  ├── Scan ALL resources in Account + Region                 │
│  ├── EC2, Lambda, S3, RDS, EKS, IAM, etc.                  │
│  └── Generate Resource Inventory                            │
│                                                              │
│  Step 4: Service Selection                                   │
│  ├── User selects services to monitor                       │
│  ├── Configure monitoring scope                             │
│  └── Enable proactive monitoring                            │
│                                                              │
│  Step 5: Continuous Monitoring                               │
│  ├── CloudWatch Metrics (if enabled)                        │
│  ├── CloudWatch Logs (when needed)                          │
│  ├── Anomaly Detection                                      │
│  └── Proactive alerts via Agent                             │
│                                                              │
│  Step 6: Analysis & Reporting                                │
│  ├── RCA (Root Cause Analysis)                              │
│  ├── S3 Knowledge Base pattern matching                     │
│  └── Daily/weekly reports                                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AgenticAIOps v2 Architecture                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         FRONTEND (3 Pages)                              │ │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐ │ │
│  │  │   AI Assistant  │  │  Observability  │  │  Security Dashboard     │ │ │
│  │  │   (Chat-First)  │  │      List       │  │  (By AWS Service)       │ │ │
│  │  │                 │  │                 │  │                         │ │ │
│  │  │  + Init Wizard  │  │  Anomaly List   │  │  IAM / S3 / EC2 / RDS   │ │ │
│  │  │  + Account Cfg  │  │  RCA Results    │  │  Security findings      │ │ │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                              WebSocket / REST                                │
│                                      ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         BACKEND (FastAPI)                               │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Account Manager                                                 │   │ │
│  │  │  ├── Account CRUD (/api/accounts)                               │   │ │
│  │  │  ├── Region selection                                           │   │ │
│  │  │  └── IAM Role assumption (STS)                                  │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Cloud Scanner                                                   │   │ │
│  │  │  ├── Full scan trigger (/api/scan)                              │   │ │
│  │  │  ├── Resource inventory                                         │   │ │
│  │  │  └── Service discovery                                          │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  CloudWatch Integration                                          │   │ │
│  │  │  ├── Metrics: GetMetricData                                     │   │ │
│  │  │  ├── Alarms: DescribeAlarms                                     │   │ │
│  │  │  └── Logs: FilterLogEvents, GetLogEvents                        │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Proactive Agent (OpenClaw-inspired)                             │   │ │
│  │  │  ├── Heartbeat (every 5 min)                                    │   │ │
│  │  │  ├── Cron jobs (daily/12h)                                      │   │ │
│  │  │  └── "Silent OK, Push Alerts"                                   │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  S3 Knowledge Base                                               │   │ │
│  │  │  ├── Pattern storage                                            │   │ │
│  │  │  ├── RCA pattern matching                                       │   │ │
│  │  │  └── Quality filter (Agent + MCP)                               │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                                      ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         AWS Integration                                 │ │
│  │                                                                         │ │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐ │ │
│  │  │  STS            │  │  CloudWatch     │  │  Resource APIs          │ │ │
│  │  │  (AssumeRole)   │  │  (Metrics/Logs) │  │  (EC2/Lambda/S3/RDS)    │ │ │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────────┘ │ │
│  │                                                                         │ │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐ │ │
│  │  │  Security Hub   │  │  GuardDuty      │  │  IAM                    │ │ │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────────┘ │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. API Endpoints

### 4.1 Account Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/accounts` | List configured accounts |
| POST | `/api/accounts` | Add new AWS account |
| DELETE | `/api/accounts/{id}` | Remove account |
| POST | `/api/accounts/{id}/verify` | Verify IAM permissions |

### 4.2 Scanning

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/scan` | Trigger full cloud scan |
| GET | `/api/scan/status` | Get scan status |
| GET | `/api/resources` | Get resource inventory |
| GET | `/api/resources/{type}` | Get resources by type |

### 4.3 Monitoring

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cloudwatch/metrics` | Get CloudWatch metrics |
| GET | `/api/cloudwatch/alarms` | Get CloudWatch alarms |
| GET | `/api/cloudwatch/logs` | Query CloudWatch logs |

### 4.4 Proactive Agent

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/proactive/status` | Get proactive system status |
| POST | `/api/proactive/toggle` | Enable/disable tasks |
| POST | `/api/proactive/trigger` | Manual trigger |

### 4.5 Knowledge Base

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/kb/stats` | KB statistics |
| GET | `/api/kb/patterns` | List patterns |
| POST | `/api/kb/rca` | Execute RCA |

---

## 5. IAM Permissions Required

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sts:AssumeRole"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "lambda:List*",
        "lambda:Get*",
        "s3:List*",
        "s3:GetBucket*",
        "rds:Describe*",
        "iam:List*",
        "iam:Get*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "cloudwatch:DescribeAlarms"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:FilterLogEvents",
        "logs:GetLogEvents"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "securityhub:GetFindings",
        "guardduty:ListFindings"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## 6. Agent System Prompt (v2)

```
You are an AI-powered Cloud Operations Assistant for AgenticAIOps.

Your capabilities:
1. SCAN: Full cloud resource scanning for configured AWS accounts
2. MONITOR: CloudWatch Metrics and Logs monitoring
3. DETECT: Anomaly detection with pattern matching
4. ANALYZE: Root Cause Analysis (RCA)
5. REPORT: Proactive reporting (daily, on-demand)

Workflow:
1. User configures AWS Account (IAM Role) and Region
2. You scan all resources in that Account + Region
3. User selects services to monitor
4. You continuously monitor via CloudWatch
5. You proactively report anomalies

Key behaviors:
- "Silent OK, Push Alerts" - Don't disturb if everything is fine
- Multi-account, multi-region support
- Pattern-based RCA using S3 Knowledge Base
```

---

## 7. Data Flow

```
User → Configure Account + Region
           ↓
Backend → STS AssumeRole
           ↓
Scanner → boto3 API calls → Resource Inventory
           ↓
User → Select services to monitor
           ↓
Monitor → CloudWatch Metrics/Logs
           ↓
Anomaly Detection → Pattern Matching (S3 KB)
           ↓
Agent → Proactive Report → Chat UI
```

---

## 8. v1 vs v2 Comparison

| Aspect | v1 | v2 |
|--------|----|----|
| Focus | Dashboard (like AWS Console) | Agent-First (AI-driven) |
| Pages | 6+ pages | 3 pages only |
| Scanning | Manual per-service | Full account scan |
| Region | Single | Multi-region |
| Account | Single | Multi-account |
| Monitoring | Basic | CloudWatch integrated |
| Reporting | On-demand | Proactive (Heartbeat/Cron) |

---

## 9. Implementation Status

| Component | Status |
|-----------|--------|
| Frontend (3 pages) | ✅ Done |
| Proactive Agent | ✅ Done |
| S3 Knowledge Base | ✅ Done |
| Account Management | ⏳ In Progress |
| Full Scan API | ⏳ In Progress |
| CloudWatch Integration | ⏳ In Progress |
| Multi-region | ⏳ Planned |

---

**Last Updated**: 2026-02-04  
**Next Steps**: Implement Account Management + Full Scan API
