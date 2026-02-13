# Detect Agent 数据复用设计方案

## 背景
Ma Ronnie 指出：Detect Agent 本身就是做数据采集的，`incident_orchestrator` 不应该重复采集。
当前 `handle_incident()` 每次都新建 EventCorrelator 重新采集 (~17s)，违反原设计。

## 现有数据源

| 组件 | 文件 | 职责 | 数据 |
|------|------|------|------|
| ProactiveAgent | `proactive_agent.py` | 周期心跳扫描 | 扫描结果、异常检测 |
| AWSScanner | `aws_ops.py` | AWS 资源扫描 | metrics, alarms, anomalies |
| EventCorrelator | `event_correlator.py` | 事件关联采集 | CorrelatedEvent |

## 问题
`incident_orchestrator.handle_incident()` 的 Stage 1 每次重新调用 `correlator.collect()` (~17s)。
但 ProactiveAgent 已经在持续运行并采集相同的数据。

## 方案 A: 渐进式 (推荐)

### 1. DetectResult 缓存
```python
@dataclass
class DetectResult:
    """ProactiveAgent 或 Alarm Webhook 产生的检测结果"""
    source: str           # "proactive" | "alarm" | "manual"
    timestamp: datetime
    correlated_event: Optional[CorrelatedEvent] = None
    anomalies: List[Dict] = field(default_factory=list)
    alarms: List[Dict] = field(default_factory=list)
    raw_data: Dict = field(default_factory=dict)
```

### 2. Orchestrator 接受已采集数据
```python
async def handle_incident(
    self,
    trigger_type: str = "manual",
    detect_result: Optional[DetectResult] = None,  # 新增
    ...
) -> IncidentRecord:
    
    if detect_result and detect_result.correlated_event:
        # 直接使用已有数据，跳过 Stage 1
        event = detect_result.correlated_event
        incident.stage_timings["collect"] = 0  # 无需采集
    else:
        # 仅在无现有数据时采集
        event = await self.correlator.collect(...)
```

### 3. ProactiveAgent 触发流程
```python
# proactive_agent.py
async def _on_anomaly_detected(self, scan_result):
    """检测到异常时直接触发 Orchestrator"""
    detect_result = DetectResult(
        source="proactive",
        timestamp=datetime.now(timezone.utc),
        anomalies=scan_result.anomalies,
        raw_data=scan_result.to_dict(),
    )
    
    orchestrator = get_orchestrator()
    await orchestrator.handle_incident(
        trigger_type="anomaly",
        detect_result=detect_result,
    )
```

### 4. Alarm Webhook 传递数据
```python
# alarm_webhook.py
async def handle_alarm_webhook(body):
    detect_result = DetectResult(
        source="alarm",
        timestamp=datetime.now(timezone.utc),
        alarms=[parse_cloudwatch_alarm(body)],
    )
    
    await orchestrator.handle_incident(
        trigger_type="alarm",
        detect_result=detect_result,
    )
```

## 方案 B: EventBus 全重构

完整的 pub/sub 事件总线，所有 Agent 通过事件通信。
工作量大，留到 P2 向量化阶段。

## 预期收益
- **性能**: RCA 延迟从 ~17s 降到 <1s (跳过重复采集)
- **架构**: 符合原设计 — Detect Agent 采集 → Orchestrator 消费
- **资源**: 减少重复 AWS API 调用

## 实施步骤
1. 新建 `src/detect_agent.py` — DetectResult 数据结构
2. 修改 `handle_incident()` — 增加 `detect_result` 参数
3. 修改 `alarm_webhook.py` — 传递 DetectResult
4. 连接 ProactiveAgent — 异常时触发 Orchestrator

## 推荐
方案 A (渐进式)，3 天分阶段实施。

---

## 补充: Reviewer 评审反馈 (2026-02-13)

以下 5 点根据 @cloud-mbot-researcher-1 评审意见补充。

### R1. DetectResult 缓存 TTL 和一致性

```python
@dataclass
class DetectResult:
    detect_id: str
    timestamp: datetime
    correlated_event: CorrelatedEvent
    pattern_matches: List[Dict[str, Any]]
    anomalies_detected: List[Dict[str, Any]]
    source: str  # "proactive_scan" | "alarm_trigger" | "manual"

    # ── 新鲜度管理 ──
    ttl_seconds: int = 300  # 默认 5 分钟，对齐 ProactiveAgent 心跳周期

    @property
    def age_seconds(self) -> float:
        """数据年龄 (秒)"""
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    @property
    def is_stale(self) -> bool:
        """数据是否过期"""
        return self.age_seconds > self.ttl_seconds

    @property
    def freshness_label(self) -> str:
        """给 RCA 消费者的新鲜度标签"""
        age = self.age_seconds
        if age < 60:
            return "fresh"       # < 1 分钟
        elif age < self.ttl_seconds:
            return "warm"        # 1-5 分钟
        else:
            return "stale"       # > TTL
```

**Orchestrator 消费时的校验逻辑**:
```python
# Stage 1 判断
if detect_result and not detect_result.is_stale:
    event = detect_result.correlated_event
    logger.info(f"Reusing {detect_result.freshness_label} data ({detect_result.age_seconds:.0f}s old)")
elif detect_result and detect_result.is_stale:
    logger.warning(f"DetectResult stale ({detect_result.age_seconds:.0f}s), falling back to fresh collection")
    event = await correlator.collect(...)  # 降级
else:
    event = await correlator.collect(...)  # 无缓存，正常采集
```

### R2. 手动触发不退化

保证规则:

| 触发类型 | `detect_result` | 行为 |
|----------|----------------|------|
| `manual` (用户 `incident run`) | `None` | **Always fresh collection** — 用户期望最新数据 |
| `manual` | 有值但 stale | Fresh collection (降级) |
| `proactive` / `alarm` | 有值且 fresh | **复用** — 跳过 Stage 1 |
| `proactive` / `alarm` | 有值但 stale | Fresh collection (降级) |
| `proactive` / `alarm` | `None` | Fresh collection (fallback) |

```python
# 手动触发永远不复用缓存（用户期望实时数据）
use_cached = (
    detect_result is not None
    and not detect_result.is_stale
    and trigger_type != "manual"
)
```

### R3. ProactiveAgent → DetectAgent 重构路径

当前 `ProactiveAgentSystem` 是调度框架，检测逻辑是 mock。重构分两步:

```
Phase 2 重构后的职责分离:

ProactiveAgentSystem (调度层 — 不变)
  ├── heartbeat loop: 每 30s 检查任务
  ├── cron: 定时调度
  └── event: 告警触发
        │
        │ 调用
        ▼
DetectAgent (检测层 — 新建)
  ├── run_detection(): 调用 EventCorrelator + AWSScanner
  ├── _match_patterns(): L0 关键词 + 向量匹配
  ├── _detect_anomalies(): 阈值/趋势判定
  ├── _cache: Dict[str, DetectResult] 缓存
  └── get_latest(): 获取最新缓存
        │
        │ 异常 → 触发
        ▼
IncidentOrchestrator.handle_incident(
    detect_result=cached_result  # 复用！
)
```

**迁移规则**:
- `_action_quick_scan()` → 委托给 `DetectAgent.run_detection()`
- `_action_security_check()` → 委托给 `DetectAgent.run_security_scan()`
- `_handle_result()` 异常时 → 调用 Orchestrator 并传入 `detect_result`
- `ProactiveAgentSystem` 本身只负责调度，不做采集

### R4. Pattern 存储渐进路线

明确三个阶段的边界和交付物:

| 阶段 | 存储方式 | 查询方式 | 交付物 | 前置条件 |
|------|----------|----------|--------|----------|
| **P1 (本迭代)** | 本地 JSON 文件 (`data/patterns/`) | `pattern_id` 精确查找 | `PatternStore` 类 + JSON read/write | 无 |
| **P2 (下一迭代)** | 本地向量搜索 | 语义相似度 top-k | 复用 `vector_search.py` | P1 完成 + 10+ Pattern 样本 |
| **P3 (后续)** | Bedrock Knowledge Base | RAG 检索 | KB 配置 + S3 同步 | P2 验证 + AWS 成本审批 |

**P1 → P2 的接口预留**:
```python
class PatternStore:
    """统一的 Pattern 存储接口"""

    def save(self, pattern: Dict) -> str: ...
    def get(self, pattern_id: str) -> Optional[Dict]: ...
    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """P1: keyword match; P2: vector search; P3: Bedrock KB"""
        ...
```

### R5. 并发安全

鉴于之前 4 个 agent 抢端口的事故，`DetectAgent` 需要:

**1. 文件锁 (采集结果写入)**:
```python
import fcntl

def _persist_result(self, result: DetectResult):
    path = f"data/detect_cache/{result.detect_id}.json"
    with open(path, 'w') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(result.to_dict(), f)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

**2. 单例保护 (进程级)**:
```python
_detect_agent: Optional[DetectAgent] = None
_lock = asyncio.Lock()

async def get_detect_agent() -> DetectAgent:
    global _detect_agent
    async with _lock:
        if _detect_agent is None:
            _detect_agent = DetectAgent()
        return _detect_agent
```

**3. 采集互斥 (防止并发 collect)**:
```python
class DetectAgent:
    def __init__(self):
        self._collecting = asyncio.Lock()

    async def run_detection(self, lookback_minutes=15) -> DetectResult:
        async with self._collecting:  # 同一时刻只有一个采集
            event = await self._collector.collect(...)
            ...
```

**4. 健康检查** (让其他组件知道 DetectAgent 状态):
```python
def health(self) -> Dict:
    return {
        "status": "running" if not self._collecting.locked() else "collecting",
        "latest_detect_id": self._latest.detect_id if self._latest else None,
        "latest_age_seconds": self._latest.age_seconds if self._latest else None,
        "cache_size": len(self._cache),
    }
```

---

*Updated: 2026-02-13 | Reviewer feedback incorporated | Status: Approved — Ready for Implementation*
