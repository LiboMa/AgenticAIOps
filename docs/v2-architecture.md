# AgenticAIOps v2 Architecture

## Overview

v2 采用 **Agent-First** 架构，核心理念是让 AI Agent 主动监控和管理 AWS 云资源。

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AgenticAIOps v2 Architecture                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │
│  │  Frontend   │    │   Backend   │    │  AWS APIs   │              │
│  │  (React)    │◄──►│  (FastAPI)  │◄──►│  (boto3)    │              │
│  └─────────────┘    └─────────────┘    └─────────────┘              │
│         │                  │                  │                      │
│         ▼                  ▼                  ▼                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │
│  │  3 Pages    │    │  Strands    │    │ CloudWatch  │              │
│  │  - Chat     │    │  Agent +    │    │ Metrics/    │              │
│  │  - Observ.  │    │  MCP Tools  │    │ Logs        │              │
│  │  - Security │    └─────────────┘    └─────────────┘              │
│  └─────────────┘                                                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Core Workflow

### Step 1: Account & Region Selection
```
User: "帮我扫描 AWS 资源"
Agent: 
  1. GET /api/scanner/account → 获取账号信息
  2. GET /api/scanner/regions → 列出可用 Region
  3. 询问用户选择 Region
```

### Step 2: Full Cloud Scan
```
User: "扫描 ap-southeast-1"
Agent:
  1. POST /api/scanner/region → 设置 Region
  2. GET /api/scanner/scan → 全量扫描
  3. 返回资源概览:
     - EC2: 5 instances
     - Lambda: 8 functions
     - S3: 23 buckets
     - RDS: 2 databases
     - 潜在问题: 2 个 S3 桶公开
```

### Step 3: Service Selection & Monitoring
```
User: "监控所有 EC2 和 RDS"
Agent:
  1. POST /api/scanner/monitor → 添加资源到监控列表
  2. 开始收集 CloudWatch Metrics
  3. 定期检查异常
```

### Step 4: Continuous Monitoring
```
Agent (主动):
  - 每 5 分钟: Heartbeat 检查
  - 每 24 小时: 日报生成
  - 事件触发: CloudWatch Alarm → 立即分析
  
  发现异常时:
  1. GET /api/cloudwatch/metrics/ec2/{id} → 获取指标
  2. POST /api/cloudwatch/logs → 检查日志
  3. POST /api/kb/rca → 根因分析
  4. 推送告警到 Chat
```

## API Endpoints

### Scanner APIs
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scanner/account` | GET | 获取 AWS 账号信息 |
| `/api/scanner/regions` | GET | 列出可用 Region |
| `/api/scanner/region` | POST | 设置当前 Region |
| `/api/scanner/scan` | GET | 全量扫描 |
| `/api/scanner/service/{service}` | GET | 扫描指定服务 |
| `/api/scanner/monitor` | POST | 添加资源到监控 |
| `/api/scanner/monitor/{id}` | DELETE | 移除监控 |
| `/api/scanner/monitored` | GET | 列出监控资源 |

### CloudWatch APIs
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/cloudwatch/metrics/ec2/{id}` | GET | EC2 指标 |
| `/api/cloudwatch/metrics/rds/{id}` | GET | RDS 指标 |
| `/api/cloudwatch/metrics/lambda/{name}` | GET | Lambda 指标 |
| `/api/cloudwatch/logs` | POST | 获取日志 |

### Proactive APIs
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/proactive/status` | GET | 系统状态 |
| `/api/proactive/toggle` | POST | 开关任务 |
| `/api/proactive/trigger` | POST | 手动触发 |

### Knowledge Base APIs
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/kb/stats` | GET | KB 统计 |
| `/api/kb/patterns` | GET/POST | Pattern CRUD |
| `/api/kb/rca` | POST | 根因分析 |

## IAM Permissions

后端需要以下 IAM 权限:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "lambda:List*",
        "lambda:Get*",
        "s3:List*",
        "s3:GetBucket*",
        "rds:Describe*",
        "eks:List*",
        "eks:Describe*",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:DescribeAlarms",
        "logs:FilterLogEvents",
        "logs:GetLogEvents",
        "logs:DescribeLogGroups",
        "iam:List*",
        "sts:GetCallerIdentity",
        "sts:AssumeRole"
      ],
      "Resource": "*"
    }
  ]
}
```

## Frontend Pages

### 1. AI Assistant (Chat)
- 主页面，用户与 Agent 交互
- 支持主动式通知
- Proactive ON/OFF 开关

### 2. Observability List
- 异常检测列表
- RCA 结果展示
- 问题统计

### 3. Security Dashboard
- 按 AWS 服务分类的安全发现
- IAM、S3、EC2、RDS 等服务的安全检查

## Proactive Design (参考 OpenClaw)

```
核心理念: "无事不扰，有事报告"

Heartbeat (5 分钟):
- 快速扫描监控资源
- 无异常: 静默
- 有异常: 推送告警

Daily Report (24 小时):
- 完整资源报告
- 成本分析
- 安全摘要

Security Scan (12 小时):
- IAM 检查
- S3 公开访问
- Security Group 规则
```

## Branch: v2-agent-first

```
Commits:
├── 588b182: 简化前端 (3 页面)
├── 7e7202f: Proactive Agent System
├── ac39fcd: S3 Knowledge Base
├── 067262c: Fix API URL
└── [pending]: AWS Scanner + CloudWatch 集成
```

## Next Steps

1. ✅ 简化前端 (3 页面)
2. ✅ Proactive Agent System
3. ✅ S3 Knowledge Base
4. ✅ AWS Scanner API
5. ⏳ CloudWatch 深度集成
6. ⏳ 多账号支持 (Assume Role)
7. ⏳ 前端 Scan/Monitor 页面

---

*Last Updated: 2026-02-04*
