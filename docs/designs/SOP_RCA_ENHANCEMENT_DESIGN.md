# SOP + RCA 增强设计方案 v2 (研究后修订)

## 研究发现

### AWS 原生能力现状

| AWS 服务 | 当前账号状态 | 能力 | 与我们的关系 |
|----------|-------------|------|-------------|
| **DevOps Guru** | 已启用，0 insights | ML 异常检测 + 自动 insight | 可作为 RCA 数据源 (当前无数据) |
| **CloudWatch Anomaly Detection** | 已有 1 个 detector (EC2 CPU, TRAINED) | ML 基线 + 异常告警 | **直接集成，替代手写阈值** |
| **AWS Health** | 有 open events (VPN/ASG) | 服务健康事件 | 作为 RCA 数据源 |
| **SSM Automation** | 50+ AWS 内置 Runbook | 自动修复 (reboot/snapshot/etc) | **可替代 SOP 自动执行步骤** |
| **EventBridge** | 可用 | 事件路由 | 告警→RCA 触发 |

### 关键决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 异常检测 | CloudWatch Anomaly Detection + 自定义阈值 | CW 已有训练好的模型，混合使用更可靠 |
| 自动执行 | 自研 (aws_ops.py) + SSM Runbook | SSM 有成熟 Runbook，自研覆盖自定义场景 |
| RCA 推理 | Bedrock Claude + RAG | LLM 做关联分析最灵活 |
| SOP 存储 | S3 (已有) | 无需新增资源 |

---

## 安全边界设计

### SOP 执行分级

```
Level 0 - 只读 (自动执行，无需审批):
├── 查询指标/日志
├── 健康检查
├── 生成报告
└── 发送通知

Level 1 - 低风险 (自动执行，事后通知):
├── 创建快照/备份
├── 扩容 (scale up)
├── 添加 CloudWatch Alarm
└── 启用增强监控

Level 2 - 中风险 (执行前 Slack 通知，10 秒等待):
├── EC2 reboot
├── Lambda 重新部署
├── 清理日志/缓存
└── 调整 Auto Scaling

Level 3 - 高风险 (必须人工审批):
├── EC2 stop/terminate
├── RDS failover
├── 安全组变更
├── IAM 权限变更
└── 数据删除
```

### 误判保护机制

```
1. 置信度门槛
   ├── RCA confidence < 0.6 → 只建议，不触发 SOP
   ├── RCA confidence 0.6-0.8 → 触发 Level 0-1 SOP
   └── RCA confidence > 0.8 → 可触发 Level 0-2 SOP

2. 冷却期 (Cooldown)
   ├── 同一资源同一 SOP → 30 分钟内不重复执行
   └── 全局 SOP 执行 → 5 分钟内最多 3 次

3. 干跑模式 (Dry-Run)
   ├── 新 SOP 首次执行 → 强制 dry-run
   ├── 显示将要执行的操作，不实际执行
   └── 用户确认后切换为真实执行

4. 回滚机制
   ├── 每个 auto 步骤执行前记录当前状态
   ├── 执行失败 → 自动回滚到记录状态
   └── 回滚失败 → 升级到 Level 3 人工处理
```

---

## 数据流设计

```
告警源                           RCA Engine                    SOP System
┌─────────────┐
│ CloudWatch  │──┐
│ Alarm       │  │
└─────────────┘  │
┌─────────────┐  │    ┌──────────────────────┐    ┌──────────────────────┐
│ CW Anomaly  │──┼───▶│ IncidentOrchestrator │───▶│ SOP Matcher          │
│ Detection   │  │    │                      │    │                      │
└─────────────┘  │    │ 1. 聚合告警数据       │    │ 1. 规则匹配           │
┌─────────────┐  │    │ 2. 查询关联指标       │    │ 2. 历史成功率          │
│ AWS Health  │──┤    │ 3. 查询 CloudTrail   │    │ 3. Claude 推荐        │
│ Events      │  │    │ 4. 查询知识库 (RAG)   │    │                      │
└─────────────┘  │    │ 5. Claude 推理       │    │ 输出:                 │
┌─────────────┐  │    │ 6. 生成 RCA Report   │    │ - matched SOPs       │
│ Proactive   │──┘    │                      │    │ - confidence         │
│ Agent       │       └──────────┬───────────┘    │ - execution_level    │
└─────────────┘                  │                 └──────────┬───────────┘
                                 │                            │
                                 ▼                            ▼
                    ┌──────────────────────┐    ┌──────────────────────┐
                    │ RCA Report (S3)      │    │ SOP Executor         │
                    │                      │    │                      │
                    │ - anomalies          │    │ Level 0-1: auto      │
                    │ - root_cause         │    │ Level 2: notify+wait │
                    │ - evidence           │    │ Level 3: approval    │
                    │ - timeline           │    │                      │
                    │ - confidence         │    │ 执行结果 → Knowledge │
                    └──────────────────────┘    └──────────────────────┘
```

---

## RCA Engine 核心设计

### 输入数据结构

```python
@dataclass
class IncidentContext:
    """RCA 分析所需的上下文数据"""
    trigger_type: str          # alarm / anomaly / health_event / manual
    trigger_data: Dict         # 原始告警数据
    
    # 自动采集
    metrics: Dict              # 最近 1h CloudWatch 指标
    recent_changes: List[Dict] # 最近 24h CloudTrail API 调用
    health_events: List[Dict]  # AWS Health 相关事件
    related_alarms: List[Dict] # 同一资源的其他告警
    
    # 知识库
    similar_patterns: List[Dict]  # 向量搜索匹配的历史 Pattern
    relevant_sops: List[Dict]     # 相关 SOP
```

### RCA 分析流程

```
Step 1: 数据采集 (并行，<5s)
├── CloudWatch: get_metric_data (最近 1h)
├── CloudTrail: lookup_events (最近 24h)
├── Health: describe_events
└── Knowledge: vector_search (RAG)

Step 2: 关联分析 (Claude, <15s)
├── 输入: IncidentContext (结构化数据)
├── 提示: "基于以下数据分析根因..."
├── 输出: 结构化 JSON (root_cause, evidence, severity, confidence)
└── 约束: 必须基于证据推理，不能凭空猜测

Step 3: SOP 匹配 (<2s)
├── 规则匹配: anomaly_type → SOP 映射表
├── 历史匹配: 相似 Pattern 上次用的 SOP
├── AI 推荐: Claude 基于 RCA 推荐 SOP
└── 排序: confidence × 历史成功率

Step 4: 输出 (<1s)
├── RCA Report → S3 持久化
├── SOP 推荐 → Chat 展示
├── 通知 → Slack
└── Level 0-1 SOP → 自动执行
```

### 性能目标

| 阶段 | 目标延迟 | 备注 |
|------|----------|------|
| 数据采集 | < 5s | 并行请求 |
| Claude 推理 | < 15s | Sonnet 用于常规，Opus 用于复杂 |
| SOP 匹配 | < 2s | 规则+缓存 |
| **总延迟** | **< 25s** | 从告警到推荐 |

---

## 新增 SOP 设计 (3→10)

| # | SOP ID | 触发条件 | 执行级别 | 自动步骤 |
|---|--------|----------|----------|----------|
| 1 | `ec2-high-cpu` | CPU > 90% (5min) | Level 1-2 | 查指标→扩容/重启 |
| 2 | `rds-failover` | RDS 不可用 | Level 3 | 快照→failover (需审批) |
| 3 | `lambda-error` | 错误率 > 5% | Level 1 | 查日志→重新部署 |
| **4** | **`ec2-disk-full`** | 磁盘 > 90% | Level 1 | 清理日志→扩容EBS |
| **5** | **`rds-storage-low`** | 存储 < 10GB | Level 2 | 快照→扩容存储 |
| **6** | **`elb-5xx-spike`** | 5xx > 10/min | Level 1 | 查后端健康→重启unhealthy |
| **7** | **`ec2-unreachable`** | 状态检查失败 | Level 2 | reboot→检查SG→恢复 |
| **8** | **`dynamodb-throttle`** | 节流事件 | Level 1 | 查容量→调整RCU/WCU |
| **9** | **`eks-pod-crash`** | CrashLoopBackOff | Level 1 | 查日志→重启pod |
| **10** | **`security-alert`** | 异常API调用 | Level 3 | 记录→隔离→通知 (需审批) |

---

## 不需要新增的 AWS 资源

```
✅ 全部使用已有资源:
├── S3: RCA 报告 + SOP 定义存储
├── OpenSearch: Pattern 向量搜索 (已有)
├── Bedrock: Claude 推理 (已有)
├── CloudWatch: 指标/日志/异常检测 (已有，1个detector)
├── CloudTrail: API 调用记录 (默认启用)
└── AWS Health: 健康事件 (免费)

⚠️ 建议后续新增:
├── 更多 CloudWatch Anomaly Detector (EC2/RDS/Lambda 关键指标)
└── EventBridge Rule (告警自动触发)
```

---

## 实施计划 (修订)

| Phase | 内容 | 前置条件 | 工作量 |
|-------|------|----------|--------|
| **研究** | 全员评审此设计 | — | 1 次会议 |
| **P0-A** | RCA Engine (数据采集+Claude推理) | 设计评审通过 | 2-3 天 |
| **P0-B** | SOP Matcher (规则+AI匹配) | P0-A 完成 | 1-2 天 |
| **P0-C** | 新增 7 个 SOP 定义 | 独立 | 1 天 |
| **P0-D** | IncidentOrchestrator 闭环 | P0-A + P0-B | 2 天 |
| **P0-E** | 安全机制 (分级+冷却+dry-run) | P0-D | 1 天 |
| **P1-A** | CW Anomaly Detection 集成 | 新增 detector | 1 天 |
| **P1-B** | EventBridge 自动触发 | IAM 配置 | 1 天 |

---

**作者**: Architect  
**日期**: 2026-02-12  
**版本**: 2.0 (研究后修订)  
**状态**: 待全员评审
