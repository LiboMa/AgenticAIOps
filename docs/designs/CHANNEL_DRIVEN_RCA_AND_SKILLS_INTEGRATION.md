# ADR-009: Channel-Driven RCA + Autonomous Skills Integration

**Status**: DRAFT  
**Author**: Architect  
**Date**: 2026-03-08  
**Supersedes**: N/A  
**References**: ADR-006 (Skills Framework), ADR-007 (Watch-on-Demand), agenticops-chat

---

## 1. Background

Ma Ronnie 指示 (2026-03-08):
1. 报警从 Channel Group 进入 → 自动触发 RCA
2. 完成自主式 Skills 实现
3. 参考 agenticops-chat 优良特性集成
4. 自我监督，完成设计→开发→验证→汇报自闭环

当前缺口:
- Skills 框架 (103 tools) 已建，但 Agent 层未真正调用
- 无 Channel 告警监听入口
- 无 Knowledge Flywheel (RCA 经验不沉淀)
- `src/aci/skills/` (旧) 与 `src/skills/` (新) 未桥接

---

## 2. agenticops-chat 特性提取

### 2.1 已集成 ✅
| 特性 | 来源 | 我们的实现 |
|------|------|----------|
| Graph Engine (BFS propagation) | `graph/` | `aci/topology/propagation.py` |
| Topology Delta | `graph/` | `aci/topology/delta.py` |
| CloudTrail Poller | 启发 | `aci/topology/cloudtrail_poller.py` |

### 2.2 待集成 (本次 ADR 范围)

#### A. AlertPayload 统一告警模型
**来源**: `agenticops-chat/src/agenticops/integrations/base.py`

```python
@dataclass
class AlertPayload:
    source: str          # datadog, pagerduty, grafana, cloudwatch, generic
    external_id: str     # dedup key
    severity: str        # critical, high, medium, low
    title: str
    description: str
    resource_hint: str   # i-xxx, arn:..., pod name
    tags: dict[str, str]
    raw: dict
```

**我们的适配**: 扩展为 `StructuredAlert`，增加 channel 来源信息。

#### B. Severity 标准化
**来源**: `agenticops-chat/src/agenticops/integrations/parsers.py`

完整的 severity 映射表: P1→critical, warning→medium, error→high 等。
直接复用，不重新发明。

#### C. Knowledge Base (KB) — Case Study + Vector Search
**来源**: `agenticops-chat/src/agenticops/kb/`

```
kb/
├── case_study.py     # CaseStudy dataclass (symptom, root_cause, resolution, lessons_learned)
├── embeddings.py     # Bedrock embedding
├── vector_store.py   # SQLiteVectorStore (cosine similarity)
└── search.py         # Hybrid search (vector + keyword fallback + rerank)
```

**这是 Knowledge Flywheel 的基础** — RCA 结果自动转为 CaseStudy，下次检索。

#### D. Pipeline Orchestrator 抽象
**来源**: `agenticops-chat/src/agenticops/pipeline/orchestrator.py`

```python
class PipelineStep(ABC):
    async def execute(self, context: Dict[str, Any]) -> Any: ...

class PipelineResult:
    step_results: List[StepResult]
```

统一的步骤编排，支持依赖、失败处理、计时。

#### E. MonitoringProvider 抽象
**来源**: `agenticops-chat/src/agenticops/integrations/base.py`

```python
class MonitoringProvider(ABC):
    def query_metrics(...) -> list[MetricSeries]: ...
    def list_active_alerts() -> list[AlertPayload]: ...
    def query_logs(...) -> list[LogEntry]: ...
```

统一的监控数据源接口，支持 CloudWatch/Datadog/Grafana 插拔。

---

## 3. 架构设计

### 3.1 StructuredAlert 模型

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Optional

class StructuredAlert(BaseModel):
    """统一告警模型 — 所有入口归一化到此模型."""
    
    # 来源
    source: Literal["channel", "eventbridge", "cloudtrail", "webhook", "manual"]
    provider: str = ""  # cloudwatch, datadog, pagerduty, grafana, generic
    
    # 告警内容
    alert_id: str        # 去重 key
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    description: str
    
    # 资源定位
    resource_hint: str = ""  # i-xxx, arn:..., pod name
    resource_type: str = ""  # ec2, pod, rds, lambda
    region: str = ""
    
    # 元数据
    tags: dict[str, str] = Field(default_factory=dict)
    raw_data: dict = Field(default_factory=dict)
    
    # Channel 来源信息
    channel_id: Optional[str] = None
    message_id: Optional[str] = None
    
    # 时间
    timestamp: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### 3.2 AlertIngressService — 统一入口

```python
class AlertIngressService:
    """统一告警入口 — Channel + Events 双模."""
    
    def __init__(self, detect_agent: DetectAgent, kb_search: HybridSearch):
        self.detect_agent = detect_agent
        self.kb_search = kb_search
        self.parsers: dict[str, AlertParser] = {}  # provider → parser
    
    async def ingest(self, alert: StructuredAlert) -> DetectResult:
        """处理一个告警:
        1. 去重 (alert_id)
        2. 查 KB 是否有历史案例
        3. 创建 DetectResult
        4. 触发 RCA pipeline
        """
        # 去重
        if self._is_duplicate(alert):
            return None
        
        # Knowledge Flywheel: 检索历史案例
        similar_cases = self.kb_search.hybrid_search(
            query_text=f"{alert.title} {alert.description}",
            resource_type=alert.resource_type,
            top_k=3
        )
        
        # 创建 DetectResult
        detect_result = DetectResult(
            source=alert.source,
            severity=alert.severity,
            resource_hint=alert.resource_hint,
            historical_cases=similar_cases,  # NEW: 注入历史案例
        )
        
        # 触发 RCA
        await self.detect_agent.on_anomaly_detected(detect_result)
        return detect_result
    
    async def ingest_from_channel(self, channel_id: str, message: str) -> Optional[StructuredAlert]:
        """从 Channel 消息解析告警."""
        alert = self._parse_channel_message(channel_id, message)
        if alert:
            return await self.ingest(alert)
        return None
```

### 3.3 Channel Alert Parsers

```python
class AlertParser(ABC):
    """告警消息解析器基类."""
    provider: str
    
    @abstractmethod
    def can_parse(self, message: str) -> bool:
        """判断消息是否为该 provider 的告警."""
    
    @abstractmethod
    def parse(self, message: str, channel_id: str) -> StructuredAlert:
        """解析消息为 StructuredAlert."""

class CloudWatchAlertParser(AlertParser):
    """解析 CloudWatch 发到 Slack 的告警消息."""
    provider = "cloudwatch"
    # Pattern: "ALARM: <name> in <region>" or JSON payload from SNS
    
class DatadogAlertParser(AlertParser):
    """解析 Datadog 发到 Slack 的告警消息."""
    provider = "datadog"
    
class PagerDutyAlertParser(AlertParser):
    """解析 PagerDuty 发到 Slack 的告警消息."""
    provider = "pagerduty"
    
class GrafanaAlertParser(AlertParser):
    """解析 Grafana 发到 Slack 的告警消息."""
    provider = "grafana"

class GenericAlertParser(AlertParser):
    """LLM-assisted 通用解析 — 兜底."""
    provider = "generic"
```

复用 agenticops-chat 的 `_normalize_severity()` 映射表。

### 3.4 L1 Skills 桥接

**目标**: `DetectAgent` 和 `RCA` 真正通过 `SkillRegistry` 调用 Skills tools。

```python
# src/skills/bridge.py — 桥接旧 ACI SkillLoader 和新 SkillRegistry

from src.skills import SkillRegistry
from src.skills._models import SecurityTier
from src.skills.agent_binding import AGENT_TIER_BINDINGS

class SkillBridge:
    """为 Agent 提供 Skills 调用能力."""
    
    def __init__(self, agent_name: str):
        self.registry = SkillRegistry.get()
        tier_binding = AGENT_TIER_BINDINGS.get(agent_name, SecurityTier.T0_READONLY)
        self.max_tier = tier_binding
        self.tools = {}
    
    def load_skills_for_context(self, context: dict) -> list[Callable]:
        """根据告警上下文自动选择合适的 Skills."""
        relevant_skills = []
        for skill_name, skill in self.registry.skills.items():
            if skill.manifest and self._skill_matches_context(skill.manifest, context):
                tools = skill.get_tools_by_tier(self.max_tier)
                relevant_skills.extend(tools)
        return relevant_skills[:50]  # Agent 工具上限
    
    def _skill_matches_context(self, manifest, context: dict) -> bool:
        """使用 can_handle() routing 判断 Skill 是否适用."""
        # 基于 manifest.routing.domains + keywords + confidence_boost
        ...

# 在 DetectAgent 中使用:
class DetectAgent:
    def __init__(self, ...):
        self.skill_bridge = SkillBridge("detect")
    
    async def run_detection(self, ...):
        # 根据检测上下文加载 Skills
        context = {"resource_type": "eks", "alert_type": "pod_crash"}
        tools = self.skill_bridge.load_skills_for_context(context)
        # 用 Skills tools 执行检测
        for tool in tools:
            result = tool(...)  # @secure_tool 自动校验 tier
```

### 3.5 Knowledge Flywheel

**直接参考 agenticops-chat 的 `kb/` 模块:**

```python
# src/knowledge/
├── __init__.py
├── case_study.py      # CaseStudy model (Pydantic, symptoms 复数 — 一个 case 多个症状)
├── flywheel.py        # KnowledgeFlywheel class — RCA → CaseStudy 自动转换
├── vector_store.py    # SQLiteVectorStore (从 agenticops-chat 适配)
└── search.py          # hybrid_search() function (无状态, 显式参数, 无 config 依赖)
```

**闭环流程:**
```
RCA 完成 → flywheel.capture(rca_result) → CaseStudy → vector_store.upsert()
                                                              ↓
下次告警 → AlertIngressService → kb_search.hybrid_search() → 历史案例注入 RCA context
```

---

## 4. 实施计划

| Phase | 天数 | 内容 | 负责 | 交付物 |
|-------|------|------|------|--------|
| 1 | 1d | `StructuredAlert` 模型 + severity 标准化 | Architect 设计, Developer 实现 | `src/alert/models.py` |
| 2 | 2d | `AlertIngressService` + 4 Parsers | Developer | `src/alert/ingress.py`, `src/alert/parsers/` |
| 3 | 1d | `SkillBridge` — 桥接 SkillRegistry ↔ Agent | Developer + Architect | `src/skills/bridge.py` |
| 4 | 1d | DetectAgent + RCA 集成 SkillBridge | Developer | 适配 `detect_agent.py`, `rca_inference.py` |
| 5 | 2d | Knowledge Flywheel (CaseStudy + VectorStore + Search) | Developer | `src/knowledge/` |
| 6 | 1d | Channel Listener (Slack channel 监听) | Developer | `src/alert/channel_listener.py` |
| 7 | 1d | E2E 测试 + 回归 | Tester | `tests/test_alert_*`, `tests/test_knowledge_*` |
| **Total** | **9d** | | | |

### 并行度

```
Week 1: Phase 1-4 (StructuredAlert + Parsers + SkillBridge + Agent 集成)
Week 2: Phase 5-7 (Knowledge Flywheel + Channel Listener + E2E)
```

Phase 1-2 和 Phase 3-4 可并行 (不同模块无依赖)。

---

## 5. 安全约束

1. Channel Listener 只监听指定的 `#alerts` channel (配置项)
2. Parsers 不执行任何代码 — 只做文本解析
3. Skills 调用遵循现有 `@secure_tool` + tier 体系
4. Knowledge Flywheel 写入前做敏感信息脱敏 (AWS credentials, IP 地址)
5. CaseStudy 默认 `status=pending_review`，需人工确认才变为 `verified`

---

## 6. 与 agenticops-chat 代码的关系

| 模块 | 策略 | 说明 |
|------|------|------|
| `AlertPayload` | **适配** | 扩展为 StructuredAlert (Pydantic, 加 channel 字段) |
| `_normalize_severity()` | **直接复用** | 映射表完整，无需修改 |
| `CaseStudy` | **适配** | 保持结构，改用 Pydantic |
| `SQLiteVectorStore` | **直接复用** | 接口清晰，后续可换 OpenSearch |
| `HybridSearch` | **直接复用** | vector + keyword + rerank |
| `PipelineStep` | **参考** | 评估是否替换现有 IncidentOrchestrator |
| `MonitoringProvider` | **Phase 2** | 本次不做，现有 CloudWatch 直连够用 |

---

## 7. 成功标准

1. 在 `#alerts` channel 发一条 CloudWatch 告警消息 → Agent 自动识别并触发 RCA
2. RCA 过程中通过 SkillBridge 调用 kubernetes/monitoring Skills
3. RCA 完成后自动生成 CaseStudy 并存入 KB
4. 下次类似告警 → 自动检索历史案例注入 RCA context
5. 全量回归 ≥2,903 passed，覆盖率 ≥86%

---

---

## 8. Module C: Skills 自举式创建/更新 (Harness-Driven)

### 8.1 核心理念

Ma Ronnie 原话: **"自举式完成"** + **"用 Harness 方式"**。

这意味着:
- 不是模板填充 → 是 **ACP Coding Agent (Harness) 自主编写 SKILL.md + tools.py**
- SRE Agent 解决问题后，自动评估是否需要新 Skill 或更新现有 Skill
- 人工 review gate 不可跳过 (安全底线)

### 8.2 触发条件

```python
class SkillGapDetector:
    """检测 Skills 覆盖缺口，触发自举式迭代."""

    # 触发场景
    TRIGGERS = {
        "novel_tool_usage": "SRE 修复过程中用了 Skills 未覆盖的命令/API",
        "detection_miss":   "RCA 发现告警漏报 (false negative)",
        "repeated_manual":  "同类告警 ≥3 次仍需手动处理 (无匹配 Skill)",
        "low_confidence":   "RCA confidence < 0.5 且找不到合适 Skill",
    }

    async def analyze_incident(self, incident: IncidentRecord, rca_result) -> Optional[SkillGap]:
        """分析事件解决过程，检测 Skill 缺口."""
        
        # 1. 提取修复过程中实际使用的命令/工具
        used_commands = self._extract_commands_from_resolution(incident)
        
        # 2. 对比现有 Skills 覆盖范围
        covered = self._check_skill_coverage(used_commands)
        uncovered = [cmd for cmd in used_commands if cmd not in covered]
        
        # 3. 检查重复模式
        repeat_count = self._count_similar_incidents(incident, window_days=30)
        
        if uncovered:
            return SkillGap(
                gap_type="novel_tool_usage",
                uncovered_commands=uncovered,
                suggested_skill_domain=self._infer_domain(uncovered),
                incident_id=incident.incident_id,
            )
        elif repeat_count >= 3:
            return SkillGap(
                gap_type="repeated_manual",
                repeat_count=repeat_count,
                suggested_action="create_runbook_skill",
                incident_id=incident.incident_id,
            )
        return None
```

### 8.3 Harness 自举流程

```
                    ┌────────────────────┐
                    │ SkillGapDetector   │
                    │ (事件解决后触发)      │
                    └─────────┬──────────┘
                              │ SkillGap
                              ▼
                    ┌────────────────────┐
                    │ SkillSpecBuilder   │
                    │ (构建 Harness 任务)  │
                    └─────────┬──────────┘
                              │ HarnessTask
                              ▼
                    ┌────────────────────┐
                    │ ACP Coding Agent   │
                    │ (Harness)          │
                    │ - 生成 SKILL.md     │
                    │ - 生成 tools.py     │
                    │ - 生成 tests        │
                    └─────────┬──────────┘
                              │ SkillDraft
                              ▼
                    ┌────────────────────┐
                    │ SkillValidator     │
                    │ (5层安全校验)        │
                    └─────────┬──────────┘
                              │ pass/fail
                          ┌───┴───┐
                          ▼       ▼
                    ┌──────┐  ┌──────────┐
                    │ PASS │  │ FAIL     │
                    │      │  │ → 日志    │
                    │ ▼    │  │ → 通知人工 │
                    │Review│  └──────────┘
                    │ Gate │
                    └──┬───┘
                       ▼
                ┌──────────────┐
                │ 人工确认后部署  │
                │ SkillRegistry│
                │ .register()  │
                └──────────────┘
```

### 8.4 SkillSpecBuilder — 构建 Harness 任务

```python
class SkillSpecBuilder:
    """将 SkillGap 转换为 Harness (ACP) 可执行的任务."""
    
    SKILL_TEMPLATE_PROMPT = """
    你是一个 SRE Skills 生成器。根据以下 incident 信息生成新的 Skill:
    
    ## 要求
    1. 遵循 agentskills.io 规范
    2. SKILL.md 包含 YAML frontmatter (name, version, tools, tier)
    3. tools.py 中每个函数必须使用 @secure_tool 装饰器
    4. 所有工具默认 tier: T0_READONLY，除非明确需要写操作
    5. 生成对应的 test_*.py 文件
    
    ## 约束 (不可违反)
    - 不可 import os.system / subprocess.Popen (用 ShellExecutor)
    - 不可修改 _security.py / SecurityFilter / approval_token.py
    - 不可使用 eval() / exec() / __import__()
    - 所有外部命令必须通过 ShellExecutor.run() 执行
    
    ## Incident Context
    {incident_context}
    
    ## 现有 Skills 列表 (避免重复)
    {existing_skills}
    
    ## 检测到的覆盖缺口
    {skill_gap}
    """
    
    def build_task(self, gap: SkillGap, incident: IncidentRecord) -> HarnessTask:
        """构建 ACP coding agent 的任务描述."""
        
        existing_skills = self._list_existing_skills()
        
        prompt = self.SKILL_TEMPLATE_PROMPT.format(
            incident_context=self._summarize_incident(incident),
            existing_skills=existing_skills,
            skill_gap=gap.to_dict(),
        )
        
        return HarnessTask(
            task=prompt,
            output_dir=f"src/skills/{gap.suggested_skill_domain}/",
            expected_files=["SKILL.md", "tools.py", f"tests/test_{gap.suggested_skill_domain}.py"],
            timeout_seconds=300,
        )
```

### 8.5 SkillValidator — 5 层安全校验

延续 ADR-006 的安全体系 + ADR-007 的 WatcherCodeAuditor:

```python
class SkillValidator:
    """验证 Harness 生成的 Skill 是否安全且合规."""
    
    async def validate(self, draft: SkillDraft) -> ValidationResult:
        errors = []
        
        # Layer 1: AST 静态扫描 (复用 WatcherCodeAuditor)
        ast_result = self._ast_scan(draft.tools_py_content)
        if ast_result.blocked_calls:
            errors.append(f"Blocked calls: {ast_result.blocked_calls}")
        
        # Layer 2: SKILL.md frontmatter 合规
        manifest = self._parse_and_validate_manifest(draft.skill_md_content)
        if not manifest:
            errors.append("Invalid SKILL.md frontmatter")
        
        # Layer 3: @secure_tool 装饰器检查
        tools_without_decorator = self._check_secure_tool_decorator(draft.tools_py_content)
        if tools_without_decorator:
            errors.append(f"Missing @secure_tool: {tools_without_decorator}")
        
        # Layer 4: Tier 分配检查 (新 Skill 默认 T0_READONLY)
        if manifest and self._has_write_ops_without_tier_upgrade(manifest, draft.tools_py_content):
            errors.append("Write operations detected but tier is T0_READONLY")
        
        # Layer 5: Dry-run (import + 基本调用测试)
        dry_run = await self._dry_run_in_sandbox(draft)
        if not dry_run.success:
            errors.append(f"Dry-run failed: {dry_run.error}")
        
        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            draft=draft,
        )
```

### 8.6 幂等性保障 (Tester 关注点)

```python
class SkillIterationGuard:
    """防止重复迭代 — 同一 gap 不重复生成 Skill."""
    
    # 去重维度: (gap_type, domain, commands_hash)
    DEDUP_WINDOW = timedelta(days=7)
    
    def __init__(self):
        self._recent_iterations: dict[str, datetime] = {}
    
    def should_iterate(self, gap: SkillGap) -> bool:
        key = f"{gap.gap_type}:{gap.suggested_skill_domain}:{gap.commands_hash}"
        last = self._recent_iterations.get(key)
        if last and (datetime.now(timezone.utc) - last) < self.DEDUP_WINDOW:
            return False
        return True
    
    def record_iteration(self, gap: SkillGap):
        key = f"{gap.gap_type}:{gap.suggested_skill_domain}:{gap.commands_hash}"
        self._recent_iterations[key] = datetime.now(timezone.utc)

    # 频率限制: 每个 incident 最多触发 1 次 (Researcher 建议)
    MAX_ITERATIONS_PER_INCIDENT = 1
```

---

## 9. Module D: SOP 自主式更新 (Harness-Driven Knowledge Flywheel)

### 9.1 与 §5 Knowledge Flywheel 的关系

§5 的 Knowledge Flywheel 处理 **CaseStudy 沉淀** (结构化、向量存储)。
Module D 在此基础上增加 **SOP 文档自主生成/更新** — 通过 Harness 编写人可读的 SOP。

```
CaseStudy (§5, 自动)        SOP (Module D, Harness 生成)
────────────────────        ──────────────────────────
结构化数据                   人可读文档
向量检索用                   操作手册用
每次 RCA 后自动生成          满足条件时 Harness 编写
无需 review                 需 review gate
```

### 9.2 SOP 生命周期 (采纳 Researcher 方案)

```
┌───────┐    首次验证    ┌────────┐   累计≥3次成功   ┌────────┐
│ draft │ ──────────→ │ active │ ────────────→ │ stable │
│ low   │             │ medium │               │ high   │
└───────┘             └────────┘               └────────┘
                           │                        │
                     连续失败≥2次               连续失败≥2次
                           │                        │
                           ▼                        ▼
                    ┌──────────────┐         ┌──────────────┐
                    │review_needed │         │review_needed │
                    │ → 人工介入     │         │ → 人工介入     │
                    └──────────────┘         └──────────────┘
```

置信度阈值 (采纳 Researcher 建议): **1/3/5** (draft→active→stable)

### 9.3 SOP 自动生成触发

```python
class SOPAutoWriter:
    """RCA 完成后，通过 Harness 自主编写 SOP."""
    
    # 触发条件
    TRIGGERS = {
        "new_pattern":     "RCA 发现新根因模式，KB 中无匹配 SOP",
        "better_fix":      "现有 SOP 修复步骤不完整，本次修复更好",
        "escalation_path": "本次 incident 暴露了新的升级路径",
    }
    
    async def evaluate_and_write(
        self, incident: IncidentRecord, rca_result, resolution_log: list[str]
    ) -> Optional[SOPDraft]:
        """评估是否需要生成/更新 SOP."""
        
        # 1. 查询现有 SOP
        existing_sop = await self._find_similar_sop(rca_result)
        
        # 2. 判断触发条件
        trigger = self._evaluate_trigger(existing_sop, rca_result, resolution_log)
        if not trigger:
            return None
        
        # 3. 构建 Harness 任务
        if existing_sop and existing_sop.similarity > 0.85:
            # 更新现有 SOP (合并新步骤)
            task = self._build_update_task(existing_sop, rca_result, resolution_log)
        else:
            # 创建新 SOP
            task = self._build_create_task(rca_result, resolution_log)
        
        # 4. 通过 Harness (ACP) 生成
        sop_draft = await self._invoke_harness(task)
        
        # 5. 验证 + 存储
        if self._validate_sop_format(sop_draft):
            await self._store_sop(sop_draft, trigger)
            await self._sync_knowledge_base()  # StartIngestionJob
            return sop_draft
        
        return None
```

### 9.4 SOP 标准格式 (采纳 Researcher 方案)

```python
class SOPDocument(BaseModel):
    """SOP 文档结构 — Harness 生成后必须符合此 schema."""
    
    # 身份
    sop_id: str                  # auto-generated, e.g. "sop-eks-pod-crash-001"
    title: str                   # e.g. "EKS Pod CrashLoopBackOff 处理"
    service: str                 # e.g. "eks", "ec2", "rds"
    alert_type: str              # e.g. "pod_crash_loop", "high_cpu"
    
    # 触发条件
    trigger_conditions: list[str]  # 告警匹配条件
    
    # 诊断步骤
    diagnostic_steps: list[SOPStep]
    
    # 修复方案 (多个)
    remediation_plans: list[RemediationPlan]
    
    # 生命周期
    status: Literal["draft", "active", "stable", "review_needed"] = "draft"
    confidence: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    
    # 溯源
    created_from_incident: str     # 首次创建时的 incident_id
    updated_from_incidents: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    
    # S3 存储路径 (Researcher 建议)
    @property
    def s3_key(self) -> str:
        return f"sop/{self.service}/{self.alert_type}/{self.sop_id}.md"

class SOPStep(BaseModel):
    order: int
    description: str
    command: Optional[str] = None        # 可执行命令
    expected_output: Optional[str] = None
    skill_tool: Optional[str] = None     # 关联的 Skill tool 名称

class RemediationPlan(BaseModel):
    name: str                            # "快速修复" / "根因修复"
    steps: list[SOPStep]
    risk_level: Literal["low", "medium", "high"]
    requires_approval: bool = False
```

### 9.5 Harness SOP 生成 Prompt

```python
SOP_GENERATION_PROMPT = """
你是一个 SRE SOP 编写专家。根据以下 incident 和 RCA 结果，生成标准化 SOP 文档。

## 格式要求
- Markdown 格式
- 必须包含: 触发条件、诊断步骤、修复方案(至少2个: 快速修复+根因修复)
- 每个步骤要有具体的命令/操作
- 命令优先使用已有 Skills tools (列表如下)

## Incident Context
{incident_summary}

## RCA 结论
- Root Cause: {root_cause}
- Confidence: {confidence}
- Affected Service: {service}
- Symptoms: {symptoms}

## 修复过程记录
{resolution_log}

## 现有 Skills Tools (优先引用)
{available_skill_tools}

## 现有相似 SOP (如果是更新，基于此修改)
{existing_sop_content}
"""
```

### 9.6 去重与合并 (Researcher 建议 + Tester 幂等性要求)

```python
class SOPDeduplicator:
    """SOP 去重 — 防止知识库污染."""
    
    SIMILARITY_THRESHOLD = 0.85  # Researcher 建议
    
    async def find_similar(self, rca_result) -> Optional[ExistingSOP]:
        """查询 Bedrock KB 检查是否已有相似 SOP."""
        
        query = f"{rca_result.root_cause} {rca_result.affected_service}"
        
        # 1. 向量检索
        results = await self.kb_search.hybrid_search(
            query_text=query,
            filter={"type": "sop"},
            top_k=5,
        )
        
        # 2. 计算最高相似度
        if results and results[0].score > self.SIMILARITY_THRESHOLD:
            return ExistingSOP(
                sop_id=results[0].metadata["sop_id"],
                similarity=results[0].score,
                content=results[0].content,
                action="update",  # 合并更新
            )
        
        return None  # 无相似 → 创建新 SOP
    
    async def merge_update(self, existing: SOPDocument, new_steps: list[SOPStep]) -> SOPDocument:
        """合并新步骤到现有 SOP (append, 不覆盖)."""
        # Harness 负责智能合并 — 不是简单 append
        task = self._build_merge_task(existing, new_steps)
        merged = await self._invoke_harness(task)
        merged.updated_from_incidents.append(incident_id)
        merged.updated_at = datetime.now(timezone.utc)
        return merged
```

### 9.7 KB Sync 策略

采纳 Researcher + Orchestrator 建议: **实时 sync**

```python
async def _sync_knowledge_base(self, sop_document: SOPDocument):
    """写入 S3 + 触发 Bedrock KB 实时同步."""
    
    # 1. 写入 S3
    s3_key = sop_document.s3_key  # sop/{service}/{alert_type}/{sop_id}.md
    await self.s3_client.put_object(
        Bucket=self.kb_bucket,
        Key=s3_key,
        Body=sop_document.to_markdown().encode("utf-8"),
        ContentType="text/markdown",
    )
    
    # 2. 触发 Bedrock KB ingestion (实时)
    await self.bedrock_client.start_ingestion_job(
        knowledgeBaseId=self.kb_id,
        dataSourceId=self.data_source_id,
    )
    
    logger.info(f"SOP synced to KB: {s3_key}")
```

---

## 10. C + D 统一闭环

### 10.1 完整 Post-RCA 流程

```
RCA 完成 (IncidentOrchestrator Stage 5 之后)
    │
    ├──→ §5 Knowledge Flywheel: CaseStudy 自动存入 (无需 review)
    │
    ├──→ Module C: SkillGapDetector.analyze_incident()
    │        │
    │        └──→ 有 gap → SkillSpecBuilder → Harness → SkillValidator
    │                                                      │
    │                                          ┌───────────┴───────────┐
    │                                          ▼                       ▼
    │                                    Validation PASS          Validation FAIL
    │                                          │                       │
    │                                    Review Gate              Log + Alert
    │                                          │
    │                                    人工确认后部署
    │
    └──→ Module D: SOPAutoWriter.evaluate_and_write()
             │
             ├──→ 无相似 SOP → Harness 生成新 SOP → validate → S3 + KB sync
             │
             └──→ 相似度 >0.85 → Harness 合并更新 → validate → S3 + KB sync
```

### 10.2 在 IncidentOrchestrator 中的接入点

```python
# incident_orchestrator.py — 新增 Stage 6

class IncidentOrchestrator:
    async def handle_incident(self, ...):
        # ... Stage 1-5 (现有) ...
        
        # ── Stage 6: Autonomous Learning Loops ──────────────
        if incident.status == IncidentStatus.COMPLETED:
            await self._autonomous_learning(incident, rca_result)
    
    async def _autonomous_learning(self, incident: IncidentRecord, rca_result):
        """Post-RCA 自主学习闭环."""
        
        # 6a. Knowledge Flywheel (§5) — 自动, 无 review
        await self.knowledge_flywheel.capture(rca_result, incident)
        
        # 6b. SOP 自主更新 (Module D) — Harness + review gate
        sop_draft = await self.sop_auto_writer.evaluate_and_write(
            incident, rca_result, incident.resolution_log
        )
        if sop_draft:
            logger.info(f"SOP draft generated: {sop_draft.sop_id}")
            await self._notify_review_needed("sop", sop_draft)
        
        # 6c. Skills 自举 (Module C) — Harness + review gate
        skill_gap = await self.skill_gap_detector.analyze_incident(incident, rca_result)
        if skill_gap and self.skill_iteration_guard.should_iterate(skill_gap):
            skill_draft = await self.skill_spec_builder.build_and_invoke(skill_gap, incident)
            validation = await self.skill_validator.validate(skill_draft)
            if validation.passed:
                await self._notify_review_needed("skill", skill_draft)
                self.skill_iteration_guard.record_iteration(skill_gap)
            else:
                logger.warning(f"Skill validation failed: {validation.errors}")
```

---

## 11. 更新后的实施计划

| Phase | 天数 | 内容 | 负责 | 前置依赖 |
|-------|------|------|------|----------|
| **1** | 1d | `StructuredAlert` 模型 + severity 标准化 | Developer | 本文档 ✅ |
| **2** | 2d | `AlertIngressService` + 4 Parsers | Developer | Phase 1 |
| **3** | 1d | `SkillBridge` (SkillRegistry ↔ Agent) | Developer | Phase 1 |
| **4** | 1d | DetectAgent + RCA 集成 SkillBridge | Developer | Phase 3 |
| **5** | 2d | Knowledge Flywheel (CaseStudy + VectorStore) | Developer | Phase 1 |
| **6** | 1d | Channel Listener (Slack 监听) | Developer | Phase 2 |
| **7** | 2d | **SOPAutoWriter** (Module D) + Harness 对接 | Developer | Phase 5 |
| **8** | 2d | **SkillGapDetector + SkillSpecBuilder** (Module C) + Harness | Developer | Phase 3 |
| **9** | 1d | **SkillValidator** (5 层安全) + Review Gate | Developer + Architect | Phase 8 |
| **10** | 2d | E2E 测试 + 全量回归 | Tester | Phase 7+9 |
| **Total** | **~12d** | | | |

### 并行度

```
Week 1: Phase 1-6 (Alert Ingress + SkillBridge + Flywheel + Listener)
Week 2: Phase 7-10 (SOPAutoWriter + SkillGapDetector + Validator + E2E)
```

Phase 1-2 // Phase 3-4 // Phase 5 可三路并行。
Phase 7 // Phase 8 可双路并行。

---

## 12. Researcher 调研决议汇总

| # | 问题 | 决议 | 来源 |
|---|------|------|------|
| 1 | S3 prefix | `sop/{service}/{alert_type}/{sop_id}.md` | Researcher 建议 ✅ |
| 2 | Skill 迭代频率 | 每 incident 最多 1 次 | Researcher 建议 ✅ |
| 3 | 置信度阈值 | 1/3/5 (draft/active/stable) | Researcher 建议 ✅ |
| 4 | KB sync | 实时 (StartIngestionJob) | Researcher+Orchestrator ✅ |
| 5 | 自举安全 | 5 层校验 + review gate 不可跳过 | Tester 关注点 ✅ |
| 6 | 幂等性 | SkillIterationGuard + SOPDeduplicator | Tester 关注点 ✅ |
| 7 | SOP 生命周期 | draft→active→stable→review_needed | Researcher 方案 ✅ |

---

## 13. 安全约束 (补充 §5)

8. Harness 生成的 tools.py 在沙箱中 dry-run，不直接在生产环境执行
9. 新 Skill 默认 `safety_tier: T0_READONLY`，需人工批准才能提升到 T1+
10. Harness 不可修改 immutable files: `_security.py`, `SecurityFilter`, `approval_token.py`
11. SOP 默认 `status: draft`，不自动执行，需人工确认后升级为 `active`
12. 单 incident 最多触发 1 次 Skill 迭代 + 1 次 SOP 生成 (防 flapping)

---

## 14. 成功标准 (补充 §7)

6. RCA 完成后，SOPAutoWriter 自动评估并生成 SOP draft (Markdown)
7. 生成的 SOP 写入 S3 并触发 KB sync，下次相似告警可检索到
8. SkillGapDetector 识别覆盖缺口后，Harness 生成 SKILL.md + tools.py
9. 生成的 Skill 通过 5 层 SkillValidator 校验
10. SOP 生命周期正确流转: draft→active→stable / review_needed
11. 全量回归 ≥2,903 passed，覆盖率 ≥86%

---

*Architect — 2026-03-08 03:35 UTC (updated: C/D Harness modules added)*
