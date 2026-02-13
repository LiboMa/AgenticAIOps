# 闭环智能运维系统设计

## 1. 系统愿景

构建一个闭环智能运维系统，通过 Agent 协作实现：
- 数据收集 → Pattern 识别 → 向量存储 → 异常检测 → 根因分析 → 自动修复 → 反馈优化

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         闭环智能运维系统                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌────────────┐     ┌────────────┐     ┌────────────────────────┐      │
│   │  Collect   │────▶│  Pattern   │────▶│   Bedrock Knowledge    │      │
│   │   Agent    │     │   Agent    │     │   Base (向量数据库)     │      │
│   └────────────┘     └────────────┘     └───────────┬────────────┘      │
│         │                                           │                    │
│         │  CloudWatch                               │ 向量检索           │
│         │  Logs                          ┌──────────┴──────────┐        │
│         │  Metrics                       │                     │        │
│         ▼                                ▼                     ▼        │
│   ┌────────────┐                  ┌────────────┐       ┌────────────┐  │
│   │  告警/事件  │────────────────▶│   Detect   │       │    RCA     │  │
│   │            │                  │   Agent    │──────▶│   Agent    │  │
│   └────────────┘                  └─────┬──────┘       └─────┬──────┘  │
│                                         │                     │         │
│                                         │ 异常检测             │ 根因分析 │
│                                         ▼                     ▼         │
│                                  ┌──────────────────────────────┐       │
│                                  │         Action Agent         │       │
│                                  │    (自动修复 / 人工审批)      │       │
│                                  └──────────────┬───────────────┘       │
│                                                 │                        │
│                                                 │ 执行结果               │
│                                                 ▼                        │
│                                  ┌──────────────────────────────┐       │
│                                  │      Feedback System         │       │
│                                  │   (反馈 → Pattern 优化)       │       │
│                                  └──────────────────────────────┘       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## 3. Agent 职责定义

### 3.1 Collect Agent (数据收集)

**职责**: 从各数据源收集运维数据

```python
class CollectAgent:
    """数据收集 Agent"""
    
    def collect_metrics(self) -> List[MetricData]:
        """收集 CloudWatch 指标"""
        # EC2 CPU/Memory/Disk
        # RDS Connections/IOPS
        # Lambda Duration/Errors
        # ELB RequestCount/Latency
        
    def collect_logs(self) -> List[LogEvent]:
        """收集日志事件"""
        # CloudWatch Logs
        # Application Logs
        # Error Logs
        
    def collect_events(self) -> List[Event]:
        """收集 AWS 事件"""
        # CloudTrail
        # EventBridge
        # Config Changes
        
    def collect_alerts(self) -> List[Alert]:
        """收集告警"""
        # CloudWatch Alarms
        # SNS Notifications
```

**数据源**:
- CloudWatch Metrics
- CloudWatch Logs
- CloudTrail Events
- AWS Config
- SNS/EventBridge

### 3.2 Pattern Agent (模式识别)

**职责**: 识别和分类运维模式

```python
class PatternAgent:
    """模式识别 Agent"""
    
    def analyze(self, data: CollectedData) -> List[Pattern]:
        """分析数据，识别模式"""
        
    def classify(self, pattern: Pattern) -> PatternCategory:
        """分类模式"""
        # performance - 性能问题
        # availability - 可用性问题  
        # security - 安全问题
        # cost - 成本问题
        # configuration - 配置问题
        
    def extract_features(self, pattern: Pattern) -> Dict:
        """提取特征向量"""
        # 用于向量数据库存储
        
    def save_to_vectordb(self, pattern: Pattern):
        """保存到 Bedrock Knowledge Base"""
```

**模式类型**:
| 类别 | 示例 |
|------|------|
| Performance | CPU 高, 内存泄漏, 响应慢 |
| Availability | 服务不可用, 连接失败, 超时 |
| Security | 异常登录, 权限变更, 端口扫描 |
| Cost | 资源闲置, 超额使用, 预留不足 |
| Configuration | 配置漂移, 参数异常, 版本不匹配 |

### 3.3 Detect Agent (异常检测)

**职责**: 实时检测异常并预警

```python
class DetectAgent:
    """异常检测 Agent"""
    
    def detect_anomaly(self, current_data: MetricData) -> Optional[Anomaly]:
        """检测异常"""
        # 基于阈值
        # 基于历史趋势
        # 基于机器学习
        
    def match_pattern(self, anomaly: Anomaly) -> List[Pattern]:
        """从向量库匹配历史模式"""
        # 查询 Bedrock KB
        # 返回相似 Pattern
        
    def trigger_alert(self, anomaly: Anomaly, patterns: List[Pattern]):
        """触发告警"""
        # 发送 Slack 通知
        # 包含历史模式参考
```

**检测方法**:
- 静态阈值检测
- 动态基线检测
- 时序异常检测
- 关联分析检测

### 3.4 RCA Agent (根因分析)

**职责**: 分析问题根因并推荐解决方案

```python
class RCAAgent:
    """根因分析 Agent"""
    
    def analyze_root_cause(self, anomaly: Anomaly) -> RootCause:
        """分析根因"""
        # 查询向量库历史案例
        # 分析关联关系
        # 推断根本原因
        
    def recommend_solutions(self, root_cause: RootCause) -> List[Solution]:
        """推荐解决方案"""
        # 基于历史成功案例
        # 排序按置信度
        
    def generate_runbook(self, solution: Solution) -> Runbook:
        """生成运维手册"""
```

**分析维度**:
- 时间关联 (What happened before?)
- 资源关联 (What resources are related?)
- 配置变更 (What changed recently?)
- 历史案例 (What solved this before?)

### 3.5 Action Agent (执行动作)

**职责**: 执行修复动作或请求人工审批

```python
class ActionAgent:
    """动作执行 Agent"""
    
    def execute_auto_fix(self, solution: Solution) -> ActionResult:
        """自动修复 (低风险)"""
        # 重启服务
        # 清理日志
        # 扩容资源
        
    def request_approval(self, solution: Solution) -> ApprovalRequest:
        """请求人工审批 (高风险)"""
        # 发送 Slack 审批请求
        # 等待确认
        
    def execute_with_approval(self, solution: Solution, approval: Approval):
        """审批后执行"""
        
    def report_result(self, result: ActionResult):
        """报告执行结果"""
```

**动作分类**:
| 风险级别 | 动作示例 | 审批要求 |
|----------|----------|----------|
| Low | 重启服务, 清理缓存 | 自动执行 |
| Medium | 扩容实例, 切换 AZ | 通知后执行 |
| High | 数据库 Failover, 配置变更 | 需要审批 |
| Critical | 数据删除, 服务下线 | 多人审批 |

## 4. 向量数据库设计 (Bedrock Knowledge Base)

### 4.1 数据模型

```json
{
  "pattern_id": "PAT-001",
  "category": "performance",
  "title": "EC2 High CPU Usage",
  "description": "EC2 instance experiencing sustained high CPU utilization",
  "symptoms": [
    "CPU > 90% for 5+ minutes",
    "Response time increased",
    "Process queue growing"
  ],
  "root_causes": [
    "Application memory leak",
    "Insufficient instance size",
    "Runaway process"
  ],
  "solutions": [
    {
      "action": "restart_service",
      "confidence": 0.8,
      "risk": "low"
    },
    {
      "action": "scale_up",
      "confidence": 0.7,
      "risk": "medium"
    }
  ],
  "metadata": {
    "occurrence_count": 42,
    "last_seen": "2026-02-10",
    "success_rate": 0.85,
    "avg_resolution_time": "15min"
  },
  "embedding": [0.1, 0.2, ...]  // 向量表示
}
```

### 4.2 S3 存储结构

```
s3://aiops-knowledge-base/
├── patterns/
│   ├── performance/
│   │   ├── ec2-high-cpu.json
│   │   └── rds-slow-query.json
│   ├── availability/
│   │   ├── service-unavailable.json
│   │   └── connection-timeout.json
│   └── security/
│       └── unusual-api-activity.json
├── runbooks/
│   ├── ec2-high-cpu-runbook.md
│   └── rds-failover-runbook.md
├── sops/
│   └── emergency-rollback.yaml
└── feedback/
    └── 2026-02/
        └── feedback-log.jsonl
```

### 4.3 向量检索流程

```
用户/系统输入 → 文本 Embedding → 向量检索 → 返回相似 Pattern
      ↓
"EC2 CPU 很高，响应变慢"
      ↓
[0.2, 0.5, 0.3, ...] (向量)
      ↓
Bedrock KB 查询 (相似度 > 0.7)
      ↓
返回: PAT-001 (EC2 High CPU) - 相似度 0.92
```

## 5. 闭环工作流

### 5.1 实时检测流程

```
1. Collect Agent 收集指标 (每分钟)
   ↓
2. Detect Agent 检测异常
   ↓
3. 查询向量库匹配历史 Pattern
   ↓
4. RCA Agent 分析根因
   ↓
5. 推荐解决方案
   ↓
6. Action Agent 执行/请求审批
   ↓
7. 记录结果 → 反馈优化 Pattern
```

### 5.2 学习优化流程

```
1. Action 执行结果
   ↓
2. 用户反馈 (good/bad)
   ↓
3. 更新 Pattern 置信度
   ↓
4. 重新生成 Embedding
   ↓
5. 同步到向量库
```

## 6. API 设计

### 6.1 Pattern API

```
POST /api/patterns/detect     # 检测并匹配 Pattern
POST /api/patterns/learn      # 学习新 Pattern
GET  /api/patterns/search     # 搜索 Pattern
POST /api/patterns/feedback   # 提交反馈
```

### 6.2 Agent API

```
POST /api/agents/collect/run  # 触发数据收集
POST /api/agents/detect/run   # 触发异常检测
POST /api/agents/rca/analyze  # 触发根因分析
POST /api/agents/action/exec  # 执行动作
```

### 6.3 Chat 命令

```
# Pattern 相关
detect             # 运行异常检测
rca <incident>     # 根因分析
pattern search xxx # 搜索 Pattern

# 动作相关
fix <issue>        # 自动修复
approve <action>   # 审批动作

# 反馈相关
feedback <id> good/bad  # 提交反馈
```

## 7. 实施计划

### Phase 1: 基础架构 (已完成部分)
- [x] Knowledge Base 模块
- [x] Pattern 数据模型
- [ ] Bedrock KB 集成

### Phase 2: Agent 实现
- [ ] Collect Agent
- [ ] Pattern Agent
- [ ] Detect Agent
- [ ] RCA Agent
- [ ] Action Agent

### Phase 3: 闭环集成
- [ ] Agent 协作流程
- [ ] 向量检索优化
- [ ] 反馈学习系统

### Phase 4: 优化增强
- [ ] 多维度关联分析
- [ ] 预测性检测
- [ ] 自动化程度提升

---

**作者**: Architect  
**日期**: 2026-02-10  
**版本**: 2.0  
**更新**: 根据 Ma Ronnie 指示，调整为闭环智能运维架构
