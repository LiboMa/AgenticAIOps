# 设计方案: HealthIssue 7 状态生命周期

**作者:** Architect  
**日期:** 2026-02-25  
**状态:** Draft → Pending Review  
**参考:** `agenticops-chat/src/agenticops/models.py` (HealthIssue + FixPlan)

---

## 背景

当前系统有 **两套独立的状态系统**，互不关联：

### IssueStatus (src/issues/models.py) — K8s 导向
```
DETECTED → ANALYZING → PENDING_FIX → FIXING → FIXED → CLOSED
                                              ↘ FAILED
                              ↘ ACKNOWLEDGED
```
8 个状态，面向 K8s pod 级问题 (OOM/CrashLoop/ImagePull)。

### IncidentStatus (src/incident_orchestrator.py) — Pipeline 导向
```
TRIGGERED → COLLECTING → ANALYZING → SOP_MATCHED → SAFETY_CHECK → EXECUTING → COMPLETED
                                                                  ↘ WAITING_APPROVAL
                                                                              ↘ FAILED
```
9 个状态，面向管道编排的执行阶段。

### agenticops-chat HealthIssueStatus — 业务导向
```
open → investigating → root_cause_identified → fix_planned → fix_approved → fix_executed → resolved
```
7 个状态，面向问题的生命周期（从发现到解决）。

### 问题
1. **Issue 和 Incident 分离** — 同一个问题在两个系统里各有一个生命周期
2. **没有审批门控** — IncidentStatus 的 `WAITING_APPROVAL` 只是暂停，没有结构化审批
3. **没有 FixPlan** — SOP 匹配后直接执行，缺少"修复计划"中间态
4. **Issue 无 RCA 关联** — IssueStatus 不知道 RCA 结果
5. **Incident 无持久化** — IncidentRecord 只在内存和 JSON 中

---

## 目标

1. 统一为 **HealthIssueStatus (7 状态)**，替代 IssueStatus + IncidentStatus
2. 引入 **FixPlan** 独立实体，含 L0-L3 风险分级 + 审批门控
3. 引入 **RCAResult** 独立关联 (1:N，一个 Issue 可有多次 RCA)
4. 保持与现有管道兼容，渐进替换
5. 未来迁移到 SQLAlchemy 时保持 schema 稳定

---

## 方案

### 方案 A: 渐进替换 (推荐)

在现有 dataclass 架构上引入 HealthIssue 统一模型，**不引入 SQLAlchemy**。

**新增文件:**
```
src/health_issue/
├── __init__.py
├── models.py          # HealthIssue + FixPlan + RCAResult (~180 行)
├── lifecycle.py       # 状态转换规则 + 审批门控 (~120 行)
├── store.py           # JSON 持久化 (SQLAlchemy ready 接口) (~100 行)
└── migration.py       # IssueStatus/IncidentStatus → HealthIssueStatus (~60 行)
```

**修改文件:**
```
src/incident_orchestrator.py  — IncidentRecord 关联 HealthIssue
src/issues/models.py          — Issue 关联 HealthIssue (deprecate IssueStatus)
src/rca_inference.py           — RCAResult 回写 HealthIssue
```

**预估:** ~640 行新代码，~80 行修改，1.5 天

### 方案 B: SQLAlchemy 全量迁移

引入 SQLAlchemy + SQLite，全面对齐 agenticops-chat 的数据层。

**预估:** ~2,000 行新代码，~500 行修改，5 天

**缺点:** 风险大，改动多，与现有 JSON 持久化/S3 存储的衔接复杂

---

## 推荐: 方案 A (渐进替换)

理由：
- 最小侵入，保持现有管道稳定
- dataclass → SQLAlchemy 迁移后续可做（store.py 接口已准备）
- 3 天 Sprint 内可完成

---

## 详细设计

### 1. HealthIssueStatus (7 状态)

```python
class HealthIssueStatus(str, Enum):
    """统一的 Issue 生命周期状态。"""
    OPEN = "open"                               # 刚检测到
    INVESTIGATING = "investigating"             # RCA 分析中
    ROOT_CAUSE_IDENTIFIED = "root_cause_identified"  # RCA 完成
    FIX_PLANNED = "fix_planned"                 # FixPlan 已生成
    FIX_APPROVED = "fix_approved"               # FixPlan 已审批
    FIX_EXECUTED = "fix_executed"               # 修复已执行
    RESOLVED = "resolved"                       # 确认解决
```

### 2. 状态转换规则

```
open ──────→ investigating ──────→ root_cause_identified ──────→ fix_planned
  │              │                       │                          │
  └─→ resolved   └─→ open (retry)       └─→ resolved (self-heal)  │
                                                                     ▼
                                          fix_approved ←── (审批通过)
                                              │
                                              ▼
                                         fix_executed ──────→ resolved
                                              │
                                              └─→ fix_planned (rollback + 重新计划)
```

**审批门控规则:**

| FixPlan Risk Level | 审批要求 |
|--------------------|----------|
| L0 (Read-only) | 自动通过 |
| L1 (Low-risk config) | 自动通过 |
| L2 (Service-affecting) | 需人工确认 |
| L3 (High-risk) | 需 senior 确认 + 二次确认 |

### 3. FixPlan 实体

```python
class FixPlanStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"

class FixPlanRiskLevel(str, Enum):
    L0 = "L0"  # Read-only verification
    L1 = "L1"  # Low-risk config change
    L2 = "L2"  # Service-affecting
    L3 = "L3"  # High-risk (restart/failover/migration)

@dataclass
class FixPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    health_issue_id: str = ""
    rca_result_id: str = ""
    title: str = ""
    description: str = ""
    risk_level: FixPlanRiskLevel = FixPlanRiskLevel.L2
    status: FixPlanStatus = FixPlanStatus.DRAFT
    
    # Structured plan
    steps: List[Dict[str, Any]] = field(default_factory=list)
    pre_checks: List[str] = field(default_factory=list)
    post_checks: List[str] = field(default_factory=list)
    rollback_plan: List[str] = field(default_factory=list)
    estimated_impact: str = ""
    
    # SOP reference
    sop_id: Optional[str] = None
    sop_name: Optional[str] = None
    
    # Approval
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_reason: Optional[str] = None
    
    # Timing
    created_at: str = field(default_factory=...)
    executed_at: Optional[str] = None
```

### 4. RCAResult 关联

```python
@dataclass
class RCAResult:
    id: str
    health_issue_id: str
    root_cause: str
    confidence: float = 0.0
    contributing_factors: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    model_id: str = ""
    network_context: Optional[Dict] = None  # 利用 Day 1 的 topology 上下文
    created_at: str = field(default_factory=...)
```

### 5. HealthIssue 统一实体

```python
@dataclass
class HealthIssue:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    resource_id: str = ""
    resource_type: str = ""
    region: str = ""
    
    severity: str = "medium"   # critical/high/medium/low
    source: str = ""           # cloudwatch_alarm/metric_anomaly/detect_agent/manual
    title: str = ""
    description: str = ""
    
    status: HealthIssueStatus = HealthIssueStatus.OPEN
    
    # Related data
    alarm_name: Optional[str] = None
    metric_data: Dict[str, Any] = field(default_factory=dict)
    related_changes: List[Dict] = field(default_factory=list)
    
    # Linked entities (by ID)
    rca_result_ids: List[str] = field(default_factory=list)
    fix_plan_ids: List[str] = field(default_factory=list)
    incident_id: Optional[str] = None  # 关联 IncidentRecord
    issue_id: Optional[str] = None     # 关联旧 Issue (兼容)
    
    # Timing
    detected_at: str = field(default_factory=...)
    resolved_at: Optional[str] = None
    
    # Feedback
    user_feedback: Optional[str] = None  # 👍/👎
```

### 6. 与 Topology 上下文的集成

HealthIssue 创建时，如果涉及网络资源，自动调用 `NetworkContextEnricher`：

```python
# In lifecycle.py
def on_investigating(health_issue: HealthIssue) -> None:
    """进入 INVESTIGATING 状态时触发 RCA + 网络上下文。"""
    if health_issue.resource_type in ("vpc", "subnet", "ec2", "rds", "elb"):
        enricher = NetworkContextEnricher(region=health_issue.region)
        context = enricher.enrich(vpc_id=..., resource_id=health_issue.resource_id)
        # 注入到 RCA 请求中
```

### 7. 旧状态迁移映射

```python
# IssueStatus → HealthIssueStatus
ISSUE_STATUS_MIGRATION = {
    "detected": "open",
    "analyzing": "investigating",
    "pending_fix": "fix_planned",
    "fixing": "fix_executed",
    "fixed": "resolved",
    "failed": "open",  # 重新开放
    "acknowledged": "investigating",
    "closed": "resolved",
}

# IncidentStatus → HealthIssueStatus
INCIDENT_STATUS_MIGRATION = {
    "triggered": "open",
    "collecting": "investigating",
    "analyzing": "investigating",
    "sop_matched": "root_cause_identified",
    "safety_check": "fix_planned",
    "executing": "fix_executed",
    "waiting_approval": "fix_planned",
    "completed": "resolved",
    "failed": "open",
}
```

---

## API 端点

| Method | Path | 描述 |
|--------|------|------|
| GET | `/api/health-issues` | 列表 (支持 status/severity 过滤) |
| GET | `/api/health-issues/{id}` | 详情 (含 RCA + FixPlan) |
| PATCH | `/api/health-issues/{id}/status` | 状态转换 |
| POST | `/api/health-issues/{id}/fix-plan` | 创建 FixPlan |
| PATCH | `/api/health-issues/{id}/fix-plan/{plan_id}/approve` | 审批 |
| PATCH | `/api/health-issues/{id}/fix-plan/{plan_id}/reject` | 拒绝 |
| POST | `/api/health-issues/{id}/feedback` | 用户反馈 |

---

## 实施计划

| 阶段 | 任务 | 负责人 | 预估 |
|------|------|--------|------|
| Day 2 | models.py + lifecycle.py | Developer | 0.5 天 |
| Day 2 | store.py + migration.py | Developer | 0.5 天 |
| Day 2 | 单测 (状态转换 + 审批) | Tester | 0.5 天 |
| Day 3 | orchestrator 集成 | Developer | 0.5 天 |
| Day 3 | API 端点 | Developer | 0.5 天 |
| Day 3 | 集成测试 + 回归 | Tester | 0.5 天 |

---

## 验收标准

- [ ] `src/health_issue/` 4 个文件 + `__init__.py`
- [ ] 7 个状态转换规则覆盖
- [ ] FixPlan L0-L3 审批门控
- [ ] IncidentOrchestrator 关联 HealthIssue
- [ ] 旧状态值迁移映射测试
- [ ] API 端点 7 个可用
- [ ] 回归 1,062+ passed, 0 failed
