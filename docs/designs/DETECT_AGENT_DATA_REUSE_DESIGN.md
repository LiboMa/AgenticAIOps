# 设计方案: Detect Agent 数据复用重构

## 背景

当前 `incident_orchestrator.handle_incident()` 在每次触发时都重新调用 `event_correlator.collect()` 进行全量 AWS 数据采集（~17s），但系统已有 `ProactiveAgent`（周期扫描）和 `AWSScanner`（全量采集）的能力。这违反了原始架构设计 (`CLOSED_LOOP_AIOPS_DESIGN.md`) 中 **Detect Agent 持续采集 → RCA Agent 复用数据** 的分工原则。

Ma Ronnie 指出：Detect Agent 主动采集数据 → 自动匹配 Pattern → 向量化存储 → RCA 直接分析，不应重复采集。

## 目标

1. **消除重复采集** — RCA 触发时复用 Detect Agent 已采集的数据
2. **架构对齐** — 回归原设计的 Multi-Agent 职责分工
3. **性能提升** — RCA 响应延迟从 ~18s 降至 <2s
4. **知识积累** — Pattern 匹配结果持久化，支持后续向量检索

## 当前架构 (As-Is)

```
手动触发 / CloudWatch Alarm
         │
         ▼
incident_orchestrator.handle_incident()
  ├── Stage 1: event_correlator.collect()    ← 17s 重复采集
  ├── Stage 2: rca_inference.analyze()       ← ~1s
  ├── Stage 3: rca_sop_bridge.match_sops()   ← <1s  
  └── Stage 4: sop_safety.check()            ← <1s
  总计: ~18s
```

**问题**:
- `collect()` 每次重新调用 CloudWatch/CloudTrail API，耗时 17s+
- `ProactiveAgent` 和 `AWSScanner` 已有采集能力但未被复用
- 多个 agent 并发调用 AWS API 会触发限流 (Bug-013)
- 不符合原设计中 Detect → RCA → Action 的数据流向

## 目标架构 (To-Be)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Detect Agent (持续运行)                       │
│                                                                  │
│  ┌──────────────┐    ┌───────────────┐    ┌──────────────────┐  │
│  │  Collector    │───▶│  Pattern      │───▶│  DetectResult    │  │
│  │  (定时采集)   │    │  Matcher      │    │  Cache           │  │
│  │              │    │  (模式匹配)    │    │  (JSON/内存)     │  │
│  └──────────────┘    └───────────────┘    └────────┬─────────┘  │
│                                                     │            │
│  数据源:                                            │ 异常触发    │
│  - CloudWatch Metrics                               ▼            │
│  - CloudWatch Alarms            ┌────────────────────────┐      │
│  - CloudTrail Events            │  AnomalyTrigger        │      │
│  - Health Events                │  (阈值/趋势/告警)       │      │
│                                 └───────────┬────────────┘      │
└─────────────────────────────────────────────┼────────────────────┘
                                              │ DetectResult
                                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RCA Agent (按需触发)                          │
│                                                                  │
│  Input: DetectResult (已采集数据 + Pattern匹配)                  │
│  ├── rca_inference.analyze(detect_result.correlated_event)       │
│  ├── rca_sop_bridge.match_sops(rca_result)                      │
│  └── sop_safety.check()                                         │
│                                                                  │
│  不再调用 event_correlator.collect()!                            │
└─────────────────────────────────────────────────────────────────┘
```

## 方案

### 方案 A: DetectResult 缓存 + Orchestrator 跳过采集 (渐进式)

**核心思路**: 最小改动，让 `handle_incident()` 支持传入预采集数据。

1. 定义 `DetectResult` 数据结构：
```python
@dataclass
class DetectResult:
    """Detect Agent 的输出，供 RCA 消费"""
    detect_id: str
    timestamp: datetime
    correlated_event: CorrelatedEvent  # 已有类型
    pattern_matches: List[Dict[str, Any]]  # 匹配到的 Pattern
    anomalies_detected: List[Dict[str, Any]]
    data_freshness_seconds: float  # 数据新鲜度
    source: str  # "proactive_scan" | "alarm_trigger" | "manual"
```

2. `DetectAgent` 类封装采集逻辑：
```python
class DetectAgent:
    """统一的检测 Agent，封装采集+缓存+异常检测"""
    
    def __init__(self, region: str = "ap-southeast-1"):
        self._collector = get_correlator(region)
        self._scanner = AWSCloudScanner(region)
        self._cache: Dict[str, DetectResult] = {}
        self._latest: Optional[DetectResult] = None
    
    async def run_detection(self, lookback_minutes: int = 15) -> DetectResult:
        """执行一次完整检测并缓存结果"""
        event = await self._collector.collect(lookback_minutes=lookback_minutes)
        patterns = self._match_patterns(event)
        anomalies = self._detect_anomalies(event)
        
        result = DetectResult(
            detect_id=f"det-{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc),
            correlated_event=event,
            pattern_matches=patterns,
            anomalies_detected=anomalies,
            data_freshness_seconds=0,
            source="proactive_scan",
        )
        self._latest = result
        self._cache[result.detect_id] = result
        return result
    
    def get_latest(self, max_age_seconds: int = 300) -> Optional[DetectResult]:
        """获取最新缓存数据（5分钟内有效）"""
        if self._latest and self._latest.data_freshness_seconds < max_age_seconds:
            return self._latest
        return None
```

3. `incident_orchestrator` 修改：
```python
async def handle_incident(
    self,
    trigger_type: str = "manual",
    trigger_data: Dict[str, Any] = None,
    detect_result: Optional[DetectResult] = None,  # ← 新增
    ...
) -> IncidentRecord:
    # Stage 1: 如果有预采集数据，直接用
    if detect_result and detect_result.data_freshness_seconds < 300:
        event = detect_result.correlated_event
        logger.info(f"Using pre-collected data from {detect_result.detect_id}")
    else:
        event = await correlator.collect(...)  # fallback
```

**优点**: 
- 改动最小，向后兼容
- 手动触发仍可 fallback 到实时采集
- 分阶段迁移，不影响现有功能

**缺点**:
- DetectAgent 需要独立的运行循环（daemon）
- 缓存过期策略需要额外考虑

### 方案 B: Event-Driven 全重构 (理想态)

**核心思路**: DetectAgent 作为事件源，通过 EventBus 驱动后续 Agent。

```python
class DetectAgent:
    """事件驱动的检测 Agent"""
    
    async def start(self, interval_seconds: int = 300):
        """启动持续检测循环"""
        while True:
            result = await self.run_detection()
            if result.anomalies_detected:
                await self._publish_event(result)  # → EventBus
            await asyncio.sleep(interval_seconds)
    
    async def _publish_event(self, result: DetectResult):
        """发布检测事件到 EventBus"""
        await event_bus.publish("detect.anomaly", result)

class RCAAgent:
    """订阅检测事件的 RCA Agent"""
    
    async def start(self):
        await event_bus.subscribe("detect.anomaly", self.on_anomaly)
    
    async def on_anomaly(self, detect_result: DetectResult):
        rca = await rca_inference.analyze(detect_result.correlated_event)
        await event_bus.publish("rca.complete", rca)
```

**优点**:
- 完全符合原设计的 Multi-Agent 架构
- 松耦合，各 Agent 独立演进
- 天然支持并行和扩展

**缺点**:
- 重构量大，需要 EventBus 基础设施
- 手动触发需要额外适配
- 测试复杂度高

## 对比

| 维度 | 方案 A (渐进式) | 方案 B (全重构) |
|------|-----------------|-----------------|
| 改动范围 | 小：新增 DetectAgent 类 + 改 orchestrator 入口 | 大：EventBus + Agent lifecycle + 全流程 |
| 风险 | 低：向后兼容，fallback 可用 | 中：需要重新集成测试 |
| 性能收益 | ✅ 17s → <1s (复用数据时) | ✅ 17s → <1s + 实时推送 |
| 原设计对齐 | 部分（数据复用但无 EventBus） | 完全对齐 |
| 工期 | 2-3 天 | 1-2 周 |
| 向量化存储 | 后续迭代 | 可同步实现 |
| 手动触发兼容 | ✅ 自动 fallback | 需要额外 adapter |

## 推荐

**方案 A (渐进式)**，理由：

1. **MVP 阶段优先可用性** — 当前 pipeline 已经 E2E 跑通，不应做大规模重构
2. **最小改动解决核心问题** — `handle_incident(detect_result=...)` 一行改动即可跳过重复采集
3. **保持向后兼容** — 手动触发 / API 调用不受影响
4. **为方案 B 铺路** — `DetectResult` 数据结构和 `DetectAgent` 类可直接复用

**分期实施**: 方案 A 本迭代完成 → 方案 B 在 P2 向量化存储阶段同步推进。

## 实施计划

### Phase 1: DetectResult + Orchestrator 适配 (Day 1)

1. 新建 `src/detect_agent.py`
   - `DetectResult` dataclass
   - `DetectAgent` 类（封装 collector + scanner + cache）
   - `get_detect_agent()` 单例

2. 修改 `src/incident_orchestrator.py`
   - `handle_incident()` 新增 `detect_result` 参数
   - 有则跳过 Stage 1，直接进 Stage 2
   - 无则 fallback 到现有逻辑

3. 修改 `api_server.py`
   - `/api/incident/run` 新增可选 `detect_id` 参数
   - 从 DetectAgent 缓存取 DetectResult

### Phase 2: ProactiveAgent 集成 (Day 2)

1. `ProactiveAgent` 改为调用 `DetectAgent.run_detection()`
2. 扫描结果自动缓存到 `DetectAgent`
3. CloudWatch Alarm webhook 触发时，先查缓存

### Phase 3: Pattern 持久化 (Day 3)

1. `DetectResult.pattern_matches` 写入本地 JSON
2. 支持按 pattern_id 查询历史匹配
3. 为后续 Bedrock KB 接入预留接口

### 验证标准

- [ ] `incident run dry` 复用缓存数据时 < 2s
- [ ] `incident run dry` 无缓存时 fallback 正常 (~18s)
- [ ] ProactiveAgent 扫描结果进入 DetectAgent 缓存
- [ ] 现有 24 个单元测试全部通过
- [ ] E2E pipeline 功能不变

---

*Author: Architect | Date: 2026-02-13 | Status: Draft — Pending Review*
