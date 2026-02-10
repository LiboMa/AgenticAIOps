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

## 9. Full Ops Support Per Service

Every monitored service needs complete operational capabilities:

```
┌─────────────────────────────────────────────────────────────┐
│          Per-Service Ops Matrix                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Capability      | EC2 | RDS | Lambda | S3  | EKS | IAM    │
│  ─────────────────────────────────────────────────────────  │
│  Scan/Discovery  | ✅  | ✅  | ✅     | ✅  | ✅  | ✅     │
│  Health Check    | ⏳  | ⏳  | ⏳     | ⏳  | ✅  | ⏳     │
│  Metrics         | ⏳  | ⏳  | ⏳     | ⏳  | ✅  | N/A    │
│  Logs            | ⏳  | ⏳  | ⏳     | N/A | ✅  | N/A    │
│  Anomaly Detect  | ⏳  | ⏳  | ⏳     | ⏳  | ✅  | ⏳     │
│  Operations      | ⏳  | ⏳  | ⏳     | N/A | ⏳  | N/A    │
│                                                              │
└─────────────────────────────────────────────────────────────┘

Legend: ✅ Done | ⏳ In Progress | N/A Not Applicable
```

### Per-Service Details

**EC2**:
- Health Check: Instance status, system checks, reachability
- Metrics: CPUUtilization, NetworkIn/Out, DiskReadOps, StatusCheckFailed
- Logs: /var/log/messages, CloudWatch Agent logs
- Operations: Start, Stop, Reboot

**RDS**:
- Health Check: Connection status, replica lag, storage space
- Metrics: CPUUtilization, FreeStorageSpace, DatabaseConnections, ReadIOPS
- Logs: Error logs, Slow query logs, General logs
- Operations: Reboot, Failover

**Lambda**:
- Health Check: Error rate, throttle rate, concurrent executions
- Metrics: Invocations, Errors, Duration, Throttles, ConcurrentExecutions
- Logs: /aws/lambda/{function-name}
- Operations: Invoke, Update configuration

**S3**:
- Health Check: ACL check, public access, encryption status
- Metrics: NumberOfObjects, BucketSizeBytes, 4xxErrors, 5xxErrors
- Operations: N/A (read-only for safety)

---

## 10. Chatbot Commands (Expanded)

```
# EC2 Commands
"list ec2"                    → List all EC2 instances
"check ec2 health"            → Health check all EC2
"show ec2 metrics {id}"       → CloudWatch metrics
"show ec2 logs {id}"          → Instance logs
"start ec2 {id}"              → Start instance
"stop ec2 {id}"               → Stop instance
"detect ec2 anomalies"        → Anomaly detection

# RDS Commands
"list rds"                    → List all RDS instances
"check rds health"            → Health check all RDS
"show rds metrics {id}"       → CloudWatch metrics
"show rds logs {id}"          → Error/slow query logs
"reboot rds {id}"             → Reboot database

# Lambda Commands
"list lambda"                 → List all Lambda functions
"check lambda health"         → Health check all functions
"show lambda metrics {name}"  → CloudWatch metrics
"show lambda logs {name}"     → Function logs
"invoke lambda {name}"        → Invoke function

# General Commands
"detect anomalies"            → All services anomaly detection
"generate health report"      → Full system health report
"scan all"                    → Full cloud scan
```

---

## 11. Implementation Status

### P0 Sprint - COMPLETED ✅ (2026-02-09)

| Component | Status | Commit |
|-----------|--------|--------|
| Frontend (3 pages) | ✅ Done | 588b182 |
| Frontend Scan Config | ✅ Done | af6b2e4 |
| Frontend Scan Results | ✅ Done | 5b4d215 |
| Proactive Agent | ✅ Done | 7e7202f |
| S3 Knowledge Base | ✅ Done | ac39fcd |
| AWS Scanner (10 services) | ✅ Done | ffa07f7 |
| Full Ops (EC2/RDS/Lambda/S3) | ✅ Done | 172d22c |
| Networking (VPC/ELB/Route53) | ✅ Done | 01a88a9 |
| EC2 Operations | ✅ Done | 0223d4e |
| AWS MCP Research | ✅ Done | (doc) |

### P1 Sprint - COMPLETED ✅ (2026-02-10)

| Component | Status | Commit |
|-----------|--------|--------|
| DynamoDB Support | ✅ Done (pending IAM) | 8bc3729 |
| ECS Support | ✅ Done (pending IAM) | 8bc3729 |
| ElastiCache Support | ✅ Done (pending IAM) | 20528ef |
| RDS Operations | ✅ Done | f20ed31 |
| Lambda Operations | ✅ Done | f20ed31 |
| Slack Alerts | ✅ Done | 765efb5 |
| Health Timeout Fix | ✅ Done | d2b2dc0 |
| Bug Fixes | ✅ Done | 4a84fbb |

### P2 Sprint - PLANNED

| Component | Status |
|-----------|--------|
| Auto-Fix | ⏳ Planned |
| Cost Optimization | ⏳ Planned |
| Security Hub Integration | ⏳ Planned |
| Daily/Weekly Reports | ⏳ Planned |

---

**Last Updated**: 2026-02-05  
**Next Steps**: Implement Full Ops (Health/Metrics/Logs/Anomaly) for EC2, RDS, Lambda, S3
