# 统一管道设计文档 — Pipeline Consolidation

**作者**: Architect  
**日期**: 2026-02-13  
**版本**: 1.0  
**状态**: Approved by Orchestrator  
**关联文档**: `UNIFIED_SEARCH_DESIGN.md`, `DETECT_AGENT_DATA_REUSE_DESIGN.md`

---

## 1. 问题陈述

当前系统存在两条独立管道，完全不交汇：

```
管道 A (现有框架):
  ProactiveAgent → aws_scanner → s3_knowledge_base → vector_search
                                      ↓
                              pattern_rag (Bedrock KB)

管道 B (Step 1-4 Pipeline):
  Alarm/Manual → event_correlator → rca_inference → sop_safety → orchestrator
                                          ↓
                              PatternMatcher (本地YAML) + Claude
```

**Researcher 验证的代码级证据** (2026-02-13):
- `incident_orchestrator.py` — 0 次引用 s3_knowledge_base / vector_search / pattern_rag
- `rca_inference.py` — 0 次引用 s3_knowledge_base / vector_search / pattern_rag
- `rca_sop_bridge.py` — 0 次引用 s3_knowledge_base / vector_search / pattern_rag
- 反馈闭环只更新内存中的置信度，不写回持久化存储

---

## 2. 目标架构

Ma Ronnie 确认的正确流程：

```
Detect Agent (主动采集) → Pattern 匹配 → Vectorize (嵌入) → 存储 (S3+OpenSearch)
                                                                    ↓
RCA Agent ← 直接从存储读取 → 分析 → 修补/告警
```

### 2.1 合并后的统一管道

```
┌─────────────────────────────────────────────────────────────┐
│                    统一闭环管道                                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ProactiveAgent (心跳/Cron/Event 触发)                       │
│       │                                                      │
│       ▼                                                      │
│  ┌──────────────────────────────────────┐                   │
│  │ 采集层 (互补，不重复)                    │                   │
│  │  aws_scanner ── 资源发现 + CW Metrics │                   │
│  │  event_correlator ── 事件关联 + Trail  │                   │
│  └──────────┬───────────────────────────┘                   │
│             │ CollectedData / CorrelatedEvent                │
│             ▼                                                │
│  ┌──────────────────────────────────────┐                   │
│  │ 匹配+向量化层 (统一入口)                 │                   │
│  │  KnowledgeSearchService (NEW)         │                   │
│  │    L1: s3_knowledge_base (本地缓存)    │                   │
│  │    L2: vector_search (OpenSearch kNN) │                   │
│  │    L3: pattern_rag (Bedrock KB, P2)   │                   │
│  │  入库: 双写 S3 + OpenSearch             │                   │
│  └──────────┬───────────────────────────┘                   │
│             │ DetectResult (含 matched patterns)             │
│             ▼                                                │
│  ┌──────────────────────────────────────┐                   │
│  │ RCA 层 (消费存储，不重新采集)              │                   │
│  │  rca_inference.py                     │                   │
│  │    1. PatternMatcher (YAML规则, 快速)  │                   │
│  │    2. KnowledgeSearchService.search() │                   │
│  │    3. Claude Sonnet → Opus (深度推理)   │                   │
│  └──────────┬───────────────────────────┘                   │
│             │ RCAResult                                      │
│             ▼                                                │
│  ┌──────────────────────────────────────┐                   │
│  │ 安全+执行层                             │                   │
│  │  sop_safety.py ── L0-L3 风险分级        │                   │
│  │  incident_orchestrator.py ── 编排      │                   │
│  └──────────┬───────────────────────────┘                   │
│             │ ActionResult                                   │
│             ▼                                                │
│  ┌──────────────────────────────────────┐                   │
│  │ 反馈层 (闭环写回)                        │                   │
│  │  KnowledgeSearchService.index()       │                   │
│  │  → S3 (权威源) + OpenSearch (向量索引)   │                   │
│  │  → 置信度更新 → 重新 Embed → 同步        │                   │
│  └──────────────────────────────────────┘                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 模块职责矩阵

### 3.1 保留模块 (不改代码)

| 模块 | 职责 | 说明 |
|------|------|------|
| `aws_scanner.py` | 资源发现 + CW Metrics/Logs | 被 ProactiveAgent 调用 |
| `event_correlator.py` | 事件关联 + CloudTrail + Alarms + Health | 被 ProactiveAgent 调用 |
| `vector_search.py` | L2 引擎: Titan Embedding → OpenSearch kNN | 被 KnowledgeSearchService 调用 |
| `pattern_rag.py` | L3 备选引擎: Bedrock KB RAG | P2 阶段接入 |
| `rca/pattern_matcher.py` | 确定性 YAML 规则匹配 | RCA 快速路径 |
| `sop_safety.py` | L0-L3 安全分级 + cooldown + circuit breaker | 无变更 |

### 3.2 改造模块

| 模块 | 改动内容 | 改动量 |
|------|---------|-------|
| `proactive_agent.py` | mock → 调用 EventCorrelator + aws_scanner | S ✅ Done (4333a5e) |
| `s3_knowledge_base.py` | add_pattern() 增加双写 OpenSearch | S ✅ Done (4333a5e) |
| `rca_inference.py` | analyze() 增加 KnowledgeSearchService.search() + prompt 注入 | M (P1-1) |
| `incident_orchestrator.py` | _learn_from_incident() 写回 KnowledgeSearchService.index() | M (P1-2) |

### 3.3 新增模块

| 模块 | 职责 | 详见 |
|------|------|------|
| `knowledge_search.py` | 统一检索入口 + 分层策略 + 统一入库 | `UNIFIED_SEARCH_DESIGN.md` |

### 3.4 合并/降级模块

| 模块 | 处置 |
|------|------|
| `operations_knowledge.py` | 合并入 `s3_knowledge_base.py`，去重 Pattern 管理 |

---

## 4. 采集层设计

### 4.1 aws_scanner vs event_correlator — 互补关系

| 维度 | `aws_scanner.py` | `event_correlator.py` |
|------|-----------------|----------------------|
| 目标 | 资源发现 ("有什么") | 事件关联 ("发生了什么") |
| 数据 | 资源列表 + 状态 + 安全检查 | Metrics + Alarms + CloudTrail + Health Events |
| 场景 | scan 命令 / 资产盘点 / 日报 | RCA 管道 / 异常诊断 / 心跳检测 |
| 输出 | `Dict[str, Any]` (scan results) | `CorrelatedEvent` (结构化事件) |

**设计决策**: 两者不合并，ProactiveAgent 根据任务类型选择调用:
- `quick_scan` (心跳) → `event_correlator.collect()` (异常检测优先)
- `full_report` (日报) → `aws_scanner.scan_all_resources()` (全量资产)
- `security_check` → `aws_scanner._scan_iam()` + `_scan_s3()` (安全聚焦)

### 4.2 DetectResult 缓存复用

详见 `DETECT_AGENT_DATA_REUSE_DESIGN.md`。核心设计:

```python
# ProactiveAgent 检测到异常后:
self._last_correlated_event = event  # 缓存

# 传给 Orchestrator，跳过 Stage 1:
orchestrator.handle_incident(pre_collected_event=self._last_correlated_event)
```

---

## 5. 统一检索层设计

详见 `UNIFIED_SEARCH_DESIGN.md`。核心要点:

### 5.1 分层检索策略

```
L1: s3_knowledge_base.search_patterns()  → 本地缓存 + 关键词 (<50ms)
L2: vector_search.semantic_search()      → OpenSearch kNN (<500ms)
L3: pattern_rag.search()                 → Bedrock KB RAG (<1s, P2)
```

自动升级: L1 ≥0.85 → 停; 否则 L2; L2 ≥0.70 → 停; 否则 L3

### 5.2 统一入库 — 双写

```
KnowledgeSearchService.index()
  → 质量门控 (≥0.7)
  → S3 写入 (权威源, 必须成功)
  → OpenSearch 索引 (尽力而为, 失败不阻塞)
```

---

## 6. RCA 引擎改造

### 6.1 当前流程 (改造前)

```
PatternMatcher.match(telemetry)     ← 本地 YAML 规则
  → if confidence < 0.85:
    → _build_analysis_prompt()      ← 纯 telemetry 数据
    → Claude Sonnet inference
    → if confidence < 0.7:
      → Claude Opus inference
```

### 6.2 改造后流程

```
PatternMatcher.match(telemetry)     ← 本地 YAML 规则 (不变)
  → if confidence < 0.85:
    → KnowledgeSearchService.search(     ← NEW: 向量知识检索
        query=build_search_query(event),
        strategy="semantic",
        limit=3,
      )
    → _build_analysis_prompt(
        correlated_event,
        knowledge_context=kb_results,    ← NEW: 注入历史知识
      )
    → Claude Sonnet inference
    → if confidence < 0.7:
      → Claude Opus inference
```

### 6.3 Prompt 改造

在现有 prompt 末尾增加 `## Historical Patterns` section:

```python
if knowledge_context and knowledge_context.hits:
    sections.append("\n## Historical Patterns (from Knowledge Base)")
    for hit in knowledge_context.hits[:3]:
        sections.append(f"- {hit.title} (score: {hit.score:.2f}): {hit.description}")
    sections.append("Use these historical patterns as reference.")
```

---

## 7. 反馈闭环修复

### 7.1 当前问题 (Researcher 验证)

```
incident_orchestrator._auto_feedback()
  → bridge.submit_feedback()
  → rca/engine.py 内存更新
  → 止步于此 ❌ 不写 S3，不写 OpenSearch
```

### 7.2 修复后

```
incident_orchestrator._learn_from_incident()
  → KnowledgeSearchService.index(pattern, quality_score)
  → S3 写入 (权威源) ✅
  → OpenSearch 索引 (向量) ✅
  → bridge.submit_feedback() (内存更新，兼容) ✅
```

---

## 8. 配置管理

```python
# src/config.py 新增
EMBEDDING_REGION = os.getenv("BEDROCK_EMBEDDING_REGION", "us-east-1")
OPENSEARCH_REGION = os.getenv("OPENSEARCH_REGION", "ap-southeast-1")
OPENSEARCH_ENDPOINT = os.getenv("OPENSEARCH_ENDPOINT", "search-os2-...")
```

- Bedrock Embedding 和 OpenSearch 集群在不同 region，需分离配置
- Developer 已在 commit `9162328` 中实现

---

## 9. 实施计划

### 9.1 已完成

| 任务 | Commit | 状态 |
|------|--------|------|
| P0-0: OpenSearch 权限配通 | — (Researcher 验证: 已配好) | ✅ Done |
| P0-1: ProactiveAgent 接真实采集 | `4333a5e` | ✅ Done |
| P0-2: handle_incident 跳过重采 | `4333a5e` | ✅ Done |
| P0-3: add_pattern() 双写 | `4333a5e` | ✅ Done |
| Bug: Bedrock region fix | `9162328` | ✅ Done |
| Bug: Replicas 2 for 3-AZ | `9162328` | ✅ Done |
| Bug: opensearch-py 依赖 | `9162328` | ✅ Done |

### 9.2 进行中

| 任务 | 负责人 | 状态 |
|------|--------|------|
| P1 统一检索设计文档 | Architect | ✅ Done (`UNIFIED_SEARCH_DESIGN.md`) |
| P2 单元测试 (proactive_agent, s3_kb, vector_search) | Tester | 🔄 In Progress |

### 9.3 待执行

| 优先级 | 任务 | 负责人 | 前置依赖 | 改动量 |
|--------|------|--------|---------|-------|
| P0-4 | Feedback 闭环写回持久化存储 | Developer | P0-3 | S |
| P1-1 | 创建 `src/knowledge_search.py` | Developer | 设计文档 | M |
| P1-2 | `rca_inference.py` 接入统一检索 | Developer | P1-1 | M |
| P1-3 | `operations_knowledge.py` 合并入 s3_kb | Developer | P1-1 | S |
| P1-4 | API 层切换到统一入口 | Developer | P1-1 | S |
| P2-1 | Bedrock KB 创建 + L3 接入 | 后续 | S3 数据就绪 | M |
| P2-2 | `rebuild_index()` 批量重建工具 | Developer | P1-1 | S |

---

## 10. 调用关系图 (最终态)

```
                        ┌─── Alarm / SNS Webhook
                        │
                        ├─── ProactiveAgent (heartbeat/cron)
                        │       ├── event_correlator.collect()
                        │       └── aws_scanner.scan_all_resources()
                        │
                        └─── Manual /chat command
                                │
                                ▼
                    incident_orchestrator.handle_incident()
                                │
                    ┌───────────┼───────────────┐
                    │           │               │
                    ▼           ▼               ▼
              Stage 1:    Stage 2:        Stage 3:
              Collect     RCA             Safety
              (skip if    rca_inference   sop_safety
              detect_     .analyze()      .check()
              result)         │
                              │
                    ┌─────────┼─────────┐
                    │         │         │
                    ▼         ▼         ▼
              PatternMatcher  Knowledge  Claude
              (YAML rules)    Search     Sonnet/
                              Service    Opus
                              .search()
                              │
                    ┌─────────┤
                    │         │
                    ▼         ▼
                   L1:       L2:
                   s3_kb     vector_
                   (cache)   search
                             (OpenSearch)
                                │
                                ▼
                    Stage 4: Learn
                    KnowledgeSearchService.index()
                    → S3 (权威) + OpenSearch (向量)
```

---

## 11. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| OpenSearch 不可用 | 中 | L2 检索失效 | L1 本地缓存兜底 + graceful degradation |
| Embedding 调用延迟 | 低 | 检索变慢 | 超时 3s 降级到 L1 |
| S3 与 OS 数据不一致 | 低 | 检索结果缺失 | S3 为权威源 + rebuild_index() 同步 |
| CloudTrail ThrottlingException | 中 | 采集不完整 | event_correlator 已有 graceful degradation |

---

**文档版本历史**

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-02-13 | 初版，整合四份理解报告 + 统一检索设计 + Researcher 验证结论 |
