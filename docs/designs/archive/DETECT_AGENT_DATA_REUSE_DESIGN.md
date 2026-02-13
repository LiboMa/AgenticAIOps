# Detect Agent 数据复用设计方案 v2

## 背景
Ma Ronnie 指出：
1. `incident_orchestrator` 每次重复采集数据 (~17s) 违反原设计
2. 原始设计: Detect Agent 主动采集 → Pattern 匹配 → Vectorize → 存储 → RCA 直接消费

## 现有组件清单

| 组件 | 文件 | 职责 | 状态 |
|------|------|------|------|
| EventCorrelator | `event_correlator.py` | AWS 数据采集 | ✅ 可用 |
| PatternMatcher | `rca/pattern_matcher.py` | 规则匹配 (YAML) | ✅ 可用 |
| VectorSearch | `vector_search.py` | OpenSearch + Titan 向量搜索 | ✅ 可用 |
| S3KnowledgeBase | `s3_knowledge_base.py` | S3 + OpenSearch 双写 | ✅ 可用 |
| PatternRAG | `pattern_rag.py` | Pattern RAG 检索 | ✅ 可用 |
| RCAInference | `rca_inference.py` | Claude 推理 (已用 PatternMatcher) | ✅ 可用 |
| **DetectAgent** | `detect_agent.py` | **串联: 采集→匹配→向量化→存储** | ❌ 缺失 |

## 完整数据流

```
ProactiveAgent (调度)
    └── DetectAgent.run_detection() (检测)
            ├── 1. EventCorrelator.collect()         → 采集 AWS 数据
            ├── 2. PatternMatcher.match()             → 规则匹配
            ├── 3. VectorSearch.index()               → 向量化 (Titan Embed)
            └── 4. S3KnowledgeBase.store()            → 持久化 (S3+OpenSearch)
                         │
                         ▼ (检测到异常)
            IncidentOrchestrator.handle_incident(detect_result=...)
                         │ (不再重新采集！)
                         ├── RCAInference.analyze()   → Claude 推理
                         ├── SOPMatch                 → SOP 匹配
                         ├── SafetyCheck              → 安全检查
                         └── Execute/Alert            → 执行/告警
```

## 方案 A: 渐进式 (推荐)

### Phase 1: DetectResult 数据结构

```python
@dataclass
class DetectResult:
    """DetectAgent 产出的检测结果"""
    source: str               # "proactive" | "alarm" | "manual"
    timestamp: datetime
    correlated_event: Optional[CorrelatedEvent] = None
    pattern_matches: List[Dict] = field(default_factory=list)
    anomalies: List[Dict] = field(default_factory=list)
    vectorized: bool = False  # 是否已向量化存储
    ttl_seconds: int = 300    # 5 分钟有效期
    
    def is_stale(self) -> bool:
        age = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return age > self.ttl_seconds
    
    def freshness_label(self) -> str:
        age = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        if age < 60: return "fresh"
        if age < 300: return "warm"
        return "stale"
```

### Phase 2: DetectAgent 类

```python
class DetectAgent:
    """持续检测 Agent — 采集→匹配→向量化→存储"""
    
    def __init__(self, region="ap-southeast-1"):
        self.correlator = get_correlator(region)
        self.pattern_matcher = PatternMatcher()
        self.vector_search = get_vector_search()
        self.kb = get_knowledge_base()
        self._latest_result: Optional[DetectResult] = None
    
    async def run_detection(self, services=None) -> DetectResult:
        """完整检测流程: 采集→匹配→向量化→存储"""
        # 1. 采集
        event = await self.correlator.collect(services=services, lookback_minutes=15)
        
        # 2. Pattern 匹配
        telemetry = event.to_rca_telemetry()
        pattern_result = self.pattern_matcher.match(telemetry)
        
        # 3. 向量化 + 存储
        vectorized = False
        if pattern_result:
            try:
                await self.kb.store_pattern(pattern_result)
                vectorized = True
            except Exception as e:
                logger.warning(f"Vectorize failed: {e}")
        
        # 4. 封装结果
        result = DetectResult(
            source="detect_agent",
            timestamp=datetime.now(timezone.utc),
            correlated_event=event,
            pattern_matches=[pattern_result.to_dict()] if pattern_result else [],
            anomalies=event.anomalies,
            vectorized=vectorized,
        )
        self._latest_result = result
        return result
    
    def get_cached_result(self) -> Optional[DetectResult]:
        """获取缓存的最近检测结果"""
        if self._latest_result and not self._latest_result.is_stale():
            return self._latest_result
        return None
```

### Phase 3: Orchestrator 消费 DetectResult

```python
async def handle_incident(
    self,
    detect_result: Optional[DetectResult] = None,
    ...
) -> IncidentRecord:
    
    if detect_result and not detect_result.is_stale():
        # 直接使用已有数据，跳过 Stage 1
        event = detect_result.correlated_event
        incident.stage_timings["collect"] = 0
    elif trigger_type == "manual":
        # 手动触发: 先检查缓存
        detect_agent = get_detect_agent()
        cached = detect_agent.get_cached_result()
        if cached:
            event = cached.correlated_event
        else:
            event = await self.correlator.collect(...)
    else:
        # Fallback: 采集
        event = await self.correlator.collect(...)
```

### Phase 4: ProactiveAgent 调度 DetectAgent

```python
# proactive_agent.py - 不直接采集，委托给 DetectAgent
async def _action_quick_scan(self, task):
    detect_agent = get_detect_agent()
    result = await detect_agent.run_detection()
    
    if result.anomalies or result.pattern_matches:
        # 自动触发 RCA，传入已有数据
        orch = get_orchestrator()
        await orch.handle_incident(detect_result=result)
    
    return ProactiveResult(status="alert" if result.anomalies else "ok", ...)
```

## 方案 B: EventBus 全重构
留到 P2。

## 预期收益
- RCA 延迟: 17s → <1s (跳过重复采集)
- 符合原设计: Detect Agent 采集 → 向量化 → 存储 → RCA 消费
- Pattern 向量化: OpenSearch 知识库越来越丰富，搜索越来越准

## 实施顺序
1. 新建 `src/detect_agent.py` (DetectResult + DetectAgent)
2. 修改 `incident_orchestrator.py` (接受 detect_result)
3. 连接 `proactive_agent.py` → DetectAgent
4. 测试: 验证 RCA 延迟 < 1s (不含采集)

## 作者
Architect | 2026-02-13 | v2 (含向量化步骤)
