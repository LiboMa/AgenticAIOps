# 统一检索入口设计文档

**作者**: Architect  
**日期**: 2026-02-13  
**版本**: 1.0  
**状态**: Draft — 待 Reviewer 评审

---

## 1. 背景

### 1.1 问题

当前系统存在**三套独立的知识检索路径**，互不相通：

| # | 路径 | 模块 | 检索方式 | 消费者 |
|---|------|------|---------|--------|
| A | OpenSearch kNN | `vector_search.py` | Titan Embedding → cosine similarity | 无（未被 RCA 调用） |
| B | Bedrock KB | `pattern_rag.py` | Bedrock KB retrieve API | 无（需 KB ID 配置） |
| C | 本地关键词 | `s3_knowledge_base.py` | 字符串匹配 + 症状评分 | `match_pattern()` 被间接使用 |

此外，`rca/pattern_matcher.py` 是第四套匹配逻辑（YAML 规则匹配），与上述三套完全独立。

**结果**: RCA 管道只用了本地规则 + Claude 推理，完全没消费向量化的历史知识。

### 1.2 目标

1. **统一检索入口** — 一个 `KnowledgeSearchService` 供所有消费者调用
2. **分层检索策略** — L1 快速 → L2 语义 → L3 深度，按需升级
3. **明确职责边界** — 每个模块做一件事，不重叠
4. **最小改动** — 不重写模块，只增加统一层

---

## 2. 设计方案

### 2.1 统一检索服务 (`KnowledgeSearchService`)

```python
# 新文件: src/knowledge_search.py

class KnowledgeSearchService:
    """
    统一知识检索入口。
    
    分层策略:
      L1 (快速预筛): 本地缓存 + 关键词匹配 (<50ms)
      L2 (语义搜索): OpenSearch kNN 向量检索 (<500ms)
      L3 (RAG 增强): Bedrock KB 检索 (备选，<1s)
    """
    
    def __init__(
        self,
        s3_kb: S3KnowledgeBase,
        vector_search: VectorKnowledgeSearch,
        pattern_rag: Optional[PatternRAG] = None,  # P2 阶段接入
    ):
        self.s3_kb = s3_kb
        self.vector_search = vector_search
        self.pattern_rag = pattern_rag
    
    async def search(
        self,
        query: str,
        strategy: str = "auto",  # "fast" | "semantic" | "deep" | "auto"
        doc_type: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 5,
        min_score: float = 0.5,
    ) -> SearchResult:
        """
        统一检索接口。
        
        Args:
            query: 搜索文本
            strategy: 检索策略
              - "fast": 仅 L1 本地缓存
              - "semantic": L1 + L2 OpenSearch
              - "deep": L1 + L2 + L3 Bedrock KB
              - "auto": L1 → 不够则 L2 → 仍不够则 L3
            doc_type: 文档类型过滤 (pattern/sop/runbook)
            service: 服务过滤 (ec2/rds/lambda...)
            limit: 最大返回数
            min_score: 最低置信度阈值
            
        Returns:
            SearchResult 统一结果
        """
        ...
    
    async def index(
        self,
        pattern: AnomalyPattern,
        quality_score: float,
    ) -> bool:
        """
        统一入库接口 — 自动双写 S3 + OpenSearch。
        
        流程:
          1. 质量门控 (quality_score ≥ 0.7)
          2. S3 存储 (原始 JSON)
          3. Titan Embedding → OpenSearch 索引
        """
        ...
```

### 2.2 统一数据模型

```python
@dataclass
class SearchHit:
    """单条检索结果"""
    pattern_id: str
    title: str
    description: str
    score: float           # 0.0 - 1.0 归一化置信度
    source: str            # "local_cache" | "opensearch" | "bedrock_kb"
    search_level: str      # "L1" | "L2" | "L3"
    content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """检索结果集"""
    query: str
    hits: List[SearchHit]
    strategy_used: str     # 实际使用的策略
    levels_tried: List[str]  # 尝试过的层级 ["L1", "L2"]
    duration_ms: float
    total_hits: int
    
    @property
    def best_hit(self) -> Optional[SearchHit]:
        return self.hits[0] if self.hits else None
    
    @property
    def has_high_confidence(self) -> bool:
        return any(h.score >= 0.85 for h in self.hits)
```

### 2.3 分层检索策略 (`auto` 模式)

```
┌─────────────────────────────────────────────────┐
│                   query 进入                      │
│                      │                            │
│                      ▼                            │
│            ┌──── L1: 本地缓存 ────┐               │
│            │  s3_kb.search_patterns()  │           │
│            │  + 关键词匹配              │           │
│            └──────────┬───────────────┘           │
│                       │                           │
│              best_score ≥ 0.85?                   │
│              ┌──yes──┐  ┌──no──┐                  │
│              ▼        │  ▼      │                  │
│         return hits   │  │      │                  │
│                       │  ▼      │                  │
│            ┌──── L2: OpenSearch ──┐               │
│            │  vector_search          │             │
│            │  .semantic_search()     │             │
│            └──────────┬──────────────┘            │
│                       │                           │
│              best_score ≥ 0.7?                    │
│              ┌──yes──┐  ┌──no──┐                  │
│              ▼        │  ▼      │                  │
│       merge & return  │  │      │                  │
│                       │  ▼      │                  │
│            ┌──── L3: Bedrock KB ──┐   (P2 阶段)  │
│            │  pattern_rag.search()    │            │
│            └──────────┬──────────────┘            │
│                       │                           │
│              merge all → sort by score → return   │
└─────────────────────────────────────────────────┘
```

**阈值配置**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `L1_SUFFICIENT_SCORE` | 0.85 | L1 命中此分数即停止 |
| `L2_SUFFICIENT_SCORE` | 0.70 | L2 命中此分数即停止 |
| `QUALITY_GATE_MIN` | 0.70 | 入库最低质量分 |
| `SCORE_NORMALIZE_FACTOR` | 1.0 | 各引擎分数归一化系数 |

---

## 3. 模块职责边界

### 3.1 改动后的职责矩阵

| 模块 | 改动前职责 | 改动后职责 | 变更 |
|------|---------|---------|------|
| **`knowledge_search.py`** *(新)* | — | 统一检索入口 + 分层策略 + 统一入库 | **新增** |
| **`vector_search.py`** | 独立的 OpenSearch 搜索 | L2 引擎：Embedding + kNN 搜索 | 无代码改动，被 KnowledgeSearchService 调用 |
| **`pattern_rag.py`** | 独立的 Bedrock KB 搜索 | L3 备选引擎 (P2 阶段接入) | 无代码改动，P1 不涉及 |
| **`s3_knowledge_base.py`** | Pattern CRUD + 本地匹配 + S3 存储 | L1 引擎：本地缓存 + S3 CRUD | `add_pattern()` 需改为通过 `KnowledgeSearchService.index()` 触发双写 |
| **`rca/pattern_matcher.py`** | YAML 规则匹配 | **保留**：快速规则匹配 (与 L1 不同，这是确定性规则) | 无变更 |
| **`rca_inference.py`** | PatternMatcher + Claude | RCA 主引擎：规则匹配 + `KnowledgeSearchService.search()` + Claude | 需改动 `analyze()` |

### 3.2 调用关系图

```
incident_orchestrator.py
  │
  ├── event_correlator.py  (Stage 1: 采集)
  │
  ├── rca_inference.py     (Stage 2: 分析)
  │     ├── rca/pattern_matcher.py       ← 确定性规则 (YAML)
  │     ├── KnowledgeSearchService.search()  ← 历史知识 (NEW)
  │     └── Claude Sonnet/Opus           ← 深度推理
  │
  ├── sop_safety.py        (Stage 3: 安全)
  │
  └── _learn_from_incident  (Stage 4: 反馈)
        └── KnowledgeSearchService.index()   ← 双写 S3+OS (NEW)


KnowledgeSearchService
  ├── L1: s3_knowledge_base.search_patterns()
  ├── L2: vector_search.semantic_search()
  └── L3: pattern_rag.search()  [P2]
```

---

## 4. RCA 引擎改造方案

### 4.1 当前 `rca_inference.py` 的 `analyze()` 流程

```
1. PatternMatcher.match(telemetry)     ← 本地 YAML 规则
2. if confidence < 0.85:
3.   _build_analysis_prompt()           ← 纯 telemetry 数据
4.   Claude Sonnet inference
5.   if confidence < 0.7:
6.     Claude Opus inference
```

### 4.2 改造后的 `analyze()` 流程

```
1. PatternMatcher.match(telemetry)     ← 本地 YAML 规则 (不变)
2. if confidence < 0.85:
3.   # ---- NEW: 向量知识检索 ----
4.   kb_results = KnowledgeSearchService.search(
5.       query=_build_search_query(correlated_event),
6.       strategy="semantic",
7.       limit=3,
8.   )
9.   # ---- NEW: 注入知识到 prompt ----
10.  prompt = _build_analysis_prompt(
11.      correlated_event,
12.      knowledge_context=kb_results,  # NEW 参数
13.  )
14.  Claude Sonnet inference
15.  if confidence < 0.7:
16.    Claude Opus inference
```

### 4.3 `_build_analysis_prompt()` 改造

在现有 prompt 末尾增加一个 `## Historical Patterns` section:

```python
def _build_analysis_prompt(correlated_event, knowledge_context=None) -> str:
    sections = []
    # ... 现有 sections 不变 ...
    
    # NEW: 注入历史知识
    if knowledge_context and knowledge_context.hits:
        sections.append("\n## Historical Patterns (from Knowledge Base)")
        for i, hit in enumerate(knowledge_context.hits[:3], 1):
            sections.append(f"\n### Reference Pattern {i} (score: {hit.score:.2f})")
            sections.append(f"- Title: {hit.title}")
            sections.append(f"- Description: {hit.description}")
            if hit.content:
                sections.append(f"- Details: {hit.content[:500]}")
        sections.append(
            "\nUse these historical patterns as reference. "
            "If the current issue matches a known pattern, cite it."
        )
    
    return "\n".join(sections)
```

---

## 5. 入库双写方案

### 5.1 当前问题

- `s3_knowledge_base.add_pattern()` → 只写 S3
- `vector_search.index_knowledge()` → 只写 OpenSearch
- 两者从未在同一流程中被调用

### 5.2 统一入库流程

```python
async def index(self, pattern: AnomalyPattern, quality_score: float) -> bool:
    """统一入库 — 双写 S3 + OpenSearch"""
    
    # 1. 质量门控
    if quality_score < QUALITY_GATE_MIN:
        logger.info(f"Pattern rejected: quality {quality_score} < {QUALITY_GATE_MIN}")
        return False
    
    # 2. S3 存储 (权威源)
    s3_ok = await self.s3_kb.add_pattern(pattern, quality_score)
    if not s3_ok:
        return False
    
    # 3. OpenSearch 索引 (尽力而为，失败不阻塞)
    try:
        combined_text = f"{pattern.title}\n{pattern.description}\n{pattern.root_cause}"
        os_ok = self.vector_search.index_knowledge(
            doc_id=pattern.pattern_id,
            title=pattern.title,
            description=pattern.description,
            content=f"Symptoms: {', '.join(pattern.symptoms)}\n"
                    f"Root cause: {pattern.root_cause}\n"
                    f"Remediation: {pattern.remediation}",
            doc_type="pattern",
            category=pattern.resource_type,
            service=pattern.resource_type,
            severity=pattern.severity,
            tags=pattern.tags,
        )
        if not os_ok:
            logger.warning(f"OpenSearch indexing failed for {pattern.pattern_id}, S3 write succeeded")
    except Exception as e:
        logger.warning(f"OpenSearch indexing error: {e}, S3 write succeeded")
    
    return True
```

**设计决策**:
- S3 为权威存储 (write-ahead)，OpenSearch 为加速索引
- OpenSearch 写入失败不阻塞，后续可批量重建索引
- 避免分布式事务复杂性

---

## 6. 接口定义汇总

### 6.1 KnowledgeSearchService 公开接口

```python
class KnowledgeSearchService:
    async def search(query, strategy, doc_type, service, limit, min_score) -> SearchResult
    async def index(pattern, quality_score) -> bool
    async def rebuild_index() -> Dict[str, Any]  # 从 S3 重建 OpenSearch 索引
    def get_stats() -> Dict[str, Any]  # 统一统计
```

### 6.2 消费者改动

| 消费者 | 改动 |
|--------|------|
| `rca_inference.py` `analyze()` | 增加 `KnowledgeSearchService.search()` 调用 + prompt 注入 |
| `incident_orchestrator.py` `_learn_from_incident()` | 改为调用 `KnowledgeSearchService.index()` |
| `api_server.py` `/api/knowledge/search` | 改为调用 `KnowledgeSearchService.search()` |
| `api_server.py` `/api/knowledge/learn` | 改为调用 `KnowledgeSearchService.index()` |

### 6.3 不改动的模块

| 模块 | 原因 |
|------|------|
| `vector_search.py` | 作为 L2 引擎被调用，接口不变 |
| `pattern_rag.py` | P2 阶段才接入，当前不涉及 |
| `s3_knowledge_base.py` | 作为 L1 引擎被调用，接口不变 |
| `rca/pattern_matcher.py` | 确定性规则引擎，与知识检索互补 |
| `sop_safety.py` | 纯安全层，不涉及检索 |

---

## 7. 实施计划

| 阶段 | 任务 | 前置依赖 | 交付物 |
|------|------|---------|--------|
| P1-1 | 创建 `src/knowledge_search.py` | 无 | 新文件 + 单元测试 |
| P1-2 | `rca_inference.py` 接入 `search()` | P1-1 | 改动 `analyze()` + `_build_analysis_prompt()` |
| P1-3 | `incident_orchestrator.py` 接入 `index()` | P1-1 | 改动 `_learn_from_incident()` |
| P1-4 | `api_server.py` API 切换 | P1-1 | `/api/knowledge/*` 走统一入口 |
| P2-1 | OpenSearch 权限配通 | Researcher 输出 | 基础设施 |
| P2-2 | Bedrock KB 创建 + L3 接入 | P2-1 | `pattern_rag` 作为 L3 |
| P2-3 | `rebuild_index()` 批量重建工具 | P2-1 | 从 S3 重建 OS 索引 |

---

## 8. 配置管理

Embedding 模型的 region 需要与 OpenSearch 集群 region 分离配置：

```python
# src/config.py 新增
EMBEDDING_REGION = os.getenv("EMBEDDING_REGION", "us-east-1")  # Titan Embed v2 可用区
OPENSEARCH_REGION = os.getenv("OPENSEARCH_REGION", "ap-southeast-1")  # OS 集群所在区
```

`vector_search.py` 中 Bedrock client 需改为:
```python
self.bedrock = boto3.client('bedrock-runtime', region_name=EMBEDDING_REGION)
```

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| OpenSearch 不可用 | 中 | L2 检索失效 | L1 本地缓存兜底 + graceful degradation |
| Embedding 调用延迟 | 低 | 检索变慢 | 缓存热门 embedding + 超时 3s 降级到 L1 |
| S3 与 OS 数据不一致 | 低 | 检索结果缺失 | S3 为权威源，定期 `rebuild_index()` 同步 |
| 分数归一化不准 | 中 | L1/L2 结果排序混乱 | 各层独立排序，不跨层混排 |

---

**等待 Reviewer (@cloud-mbot-researcher-1) 评审。**
