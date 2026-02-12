# SOP + RCA 功能增强设计方案

## 背景

当前 SOP 系统和 RCA (异常检测) 功能是独立运作的：
- SOP: 3 个内置 SOP (EC2 高 CPU / RDS Failover / Lambda 错误)
- RCA: 简单阈值异常检测 (detect_anomalies)，仅支持 EC2/RDS/Lambda
- 知识库: Pattern 学习 + S3 存储
- 两者之间没有自动关联

## 目标

建立 **异常检测 → 根因分析 → SOP 推荐 → 自动执行** 的闭环。

## 方案设计

### 1. RCA 引擎增强

```
当前:
  detect_anomalies() → 简单阈值 → 返回异常列表

增强后:
  detect_anomalies()
    → 多维指标关联分析
    → Bedrock Claude 深度推理
    → 历史 Pattern 匹配 (RAG)
    → 生成结构化 RCA 报告
    → 自动推荐 SOP
```

#### 1.1 RCA 报告结构

```python
@dataclass
class RCAReport:
    report_id: str
    timestamp: str
    trigger: str                    # 什么触发了 RCA
    affected_resources: List[str]   # 受影响资源
    
    # 异常信息
    anomalies: List[Dict]           # 检测到的异常
    
    # 根因分析
    root_cause: str                 # AI 推理的根因
    confidence: float               # 置信度 0-1
    evidence: List[str]             # 支撑证据
    
    # 关联分析
    correlated_events: List[Dict]   # CloudTrail/CloudWatch 关联事件
    timeline: List[Dict]            # 事件时间线
    
    # 推荐行动
    recommended_sops: List[str]     # 推荐的 SOP ID
    suggested_actions: List[str]    # 建议操作
    
    # 历史匹配
    similar_incidents: List[Dict]   # 历史相似事件
    
    severity: str                   # critical/high/medium/low
```

#### 1.2 多维关联分析

| 数据源 | 当前 | 增强后 |
|--------|------|--------|
| CloudWatch Metrics | ✅ CPU/内存 | + 网络/磁盘/自定义指标 |
| CloudWatch Logs | ❌ | ✅ 错误日志分析 |
| CloudTrail | ❌ | ✅ API 调用关联 |
| Health Events | ❌ | ✅ AWS Health Dashboard |
| Config Changes | ❌ | ✅ Config 变更追踪 |
| Knowledge Base | 基础搜索 | ✅ 向量语义匹配 |

### 2. SOP 系统增强

#### 2.1 SOP 自动触发

```
当前:
  用户手动: "sop run ec2-high-cpu"

增强后:
  detect_anomalies()
    → RCA Engine 分析
    → 匹配 SOP (规则 + AI)
    → 自动建议: "检测到 EC2 高 CPU，推荐执行 SOP ec2-high-cpu"
    → 用户确认后执行
    → 执行结果反馈到知识库
```

#### 2.2 SOP 新增内容

| SOP ID | 名称 | 触发条件 | 优先级 |
|--------|------|----------|--------|
| `ec2-high-cpu` | EC2 高 CPU 处理 | CPU > 90% | ✅ 已有 |
| `rds-failover` | RDS 故障转移 | RDS 不可用 | ✅ 已有 |
| `lambda-error` | Lambda 错误处理 | 错误率 > 5% | ✅ 已有 |
| `ec2-disk-full` | EC2 磁盘满 | 磁盘 > 90% | **P0 新增** |
| `rds-storage-low` | RDS 存储不足 | 空间 < 10GB | **P0 新增** |
| `elb-5xx-spike` | ELB 5xx 突增 | 5xx > 阈值 | **P0 新增** |
| `network-connectivity` | 网络连通性故障 | 健康检查失败 | **P1 新增** |
| `security-breach` | 安全事件响应 | 异常 API 调用 | **P1 新增** |
| `cost-anomaly` | 费用异常 | 费用突增 | **P2 新增** |

#### 2.3 SOP 执行增强

```
当前:
  SOPExecutor → 手动逐步完成

增强后:
  SOPExecutor
    ├── 自动执行 auto 类型步骤 (调用 AWS API)
    ├── 条件分支 (根据检查结果走不同路径)
    ├── 审批流程 (危险操作等待确认)
    ├── 回滚机制 (失败时自动回滚)
    ├── 进度通知 (Slack 实时更新)
    └── 执行结果存入知识库
```

### 3. 闭环架构

```
┌──────────────────────────────────────────────────────┐
│                    闭环运维系统                         │
│                                                       │
│  ① 检测                                              │
│  ┌─────────────┐                                     │
│  │ Proactive    │ CloudWatch Alarm                    │
│  │ Agent        │ → detect_anomalies()               │
│  └──────┬──────┘                                     │
│         ▼                                            │
│  ② 分析 (RCA)                                        │
│  ┌─────────────────────────────────────────┐         │
│  │ RCA Engine                               │         │
│  │ ├── 多维指标聚合                          │         │
│  │ ├── CloudTrail 关联                       │         │
│  │ ├── Bedrock Claude 推理                   │         │
│  │ ├── 知识库 Pattern 匹配 (RAG)             │         │
│  │ └── 生成 RCA Report                       │         │
│  └──────┬──────────────────────────────────┘         │
│         ▼                                            │
│  ③ 推荐 SOP                                          │
│  ┌─────────────────────────────────────────┐         │
│  │ SOP Matcher                              │         │
│  │ ├── 规则匹配 (anomaly_type → SOP)         │         │
│  │ ├── AI 推荐 (Claude 分析最佳 SOP)          │         │
│  │ └── 历史成功率排序                         │         │
│  └──────┬──────────────────────────────────┘         │
│         ▼                                            │
│  ④ 执行                                              │
│  ┌─────────────────────────────────────────┐         │
│  │ SOP Executor (增强版)                     │         │
│  │ ├── 自动执行 auto 步骤                     │         │
│  │ ├── 审批等待 (危险操作)                    │         │
│  │ ├── Slack 进度通知                         │         │
│  │ └── 失败回滚                              │         │
│  └──────┬──────────────────────────────────┘         │
│         ▼                                            │
│  ⑤ 反馈学习                                          │
│  ┌─────────────────────────────────────────┐         │
│  │ Knowledge Feedback                       │         │
│  │ ├── 执行结果 → 知识库                     │         │
│  │ ├── Pattern 更新                          │         │
│  │ ├── SOP 效果评分                          │         │
│  │ └── 优化推荐模型                          │         │
│  └─────────────────────────────────────────┘         │
│                                                       │
└──────────────────────────────────────────────────────┘
```

### 4. 新增后端模块

| 模块 | 文件 | 功能 |
|------|------|------|
| **RCA Engine** | `src/rca_engine.py` | 根因分析引擎 |
| **SOP Matcher** | `src/sop_matcher.py` | 异常→SOP 匹配 |
| **Event Correlator** | `src/event_correlator.py` | CloudTrail/CW 事件关联 |
| **Closed Loop Controller** | `src/closed_loop.py` | 闭环流程编排 |

### 5. API 新增

```
POST /api/rca/analyze          # 触发 RCA 分析
GET  /api/rca/reports          # RCA 报告列表
GET  /api/rca/report/{id}      # RCA 报告详情

POST /api/sop/auto-suggest     # 基于异常自动推荐 SOP
POST /api/sop/execute-auto     # 自动执行 SOP (带审批)
GET  /api/sop/execution/{id}/progress  # 执行进度

POST /api/closed-loop/trigger  # 触发闭环流程
GET  /api/closed-loop/status   # 闭环状态
```

### 6. 实施计划

| Phase | 内容 | 工作量 |
|-------|------|--------|
| **P0-A** | RCA Engine (多维分析 + Claude 推理) | 2-3 天 |
| **P0-B** | SOP Matcher (异常→SOP 自动匹配) | 1-2 天 |
| **P0-C** | 新增 3 个 SOP (disk/storage/5xx) | 1 天 |
| **P0-D** | 闭环编排 (detect→RCA→SOP→execute) | 2 天 |
| **P1-A** | CloudTrail 事件关联 | 2 天 |
| **P1-B** | SOP 自动执行 + 审批流 | 2 天 |
| **P1-C** | 执行结果反馈学习 | 1 天 |

---

**作者**: Architect  
**日期**: 2026-02-12  
**版本**: 1.0
