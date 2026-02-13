# 📐 代码库清理差异报告 — Codebase Cleanup Gap Report

**作者**: Architect  
**日期**: 2026-02-13  
**背景**: Ma Ronnie 指令：大清理。在 Pipeline Consolidation 之后，代码库积累了大量历史模块、重复实现和死代码。本报告识别所有应删除/合并/重构的目标。

---

## 0. 摘要

| 指标 | 数值 |
|------|------|
| **src/ 总文件数** | 64 |
| **src/ 总行数** | 22,054 |
| **api_server.py** | 4,703 行 (132 个函数) |
| **孤立模块 (无人引用)** | 14 个, 5,140 行 |
| **已废弃 shim** | 1 个, 337 行 |
| **重复功能对** | 6 组 |
| **预计可删除行数** | ~6,700 行 (~30%) |

---

## 1. 🔴 立即删除 — Orphan Modules (无任何 import 引用)

以下 14 个模块不被 `src/` 内任何文件或 `api_server.py` 引用（AST 级静态分析确认）：

| 文件 | 行数 | 原用途 | 删除理由 |
|------|------|--------|----------|
| `src/tools/kubernetes.py` | 629 | K8s 工具封装 | `src/kubectl_wrapper.py` + ACI 已替代 |
| `src/analyzers/k8s_analyzers.py` | 581 | K8s 分析器 | 从未接入管道，被 `rca_inference.py` 替代 |
| `src/bedrock_agent.py` | 574 | Bedrock AgentCore | 已改用直接 Bedrock invoke，废弃 |
| `src/mock.py` | 540 | Demo mock 数据 | 全 mock K8s/AWS，测试用 `unittest.mock` |
| `src/tools/aws.py` | 491 | AWS 工具 | `aws_scanner.py` + `event_correlator.py` 已替代 |
| `src/tools/diagnostics.py` | 423 | 诊断工具 | 从未接入管道 |
| `src/lambda_eks_operations.py` | 472 | Lambda EKS handler | 非 EKS 部署，无引用 |
| `src/agent.py` | 330 | 旧 Agent 入口 | 被 `detect_agent.py` + `proactive_agent.py` 替代 |
| `src/pattern_rag.py` | 250 | Bedrock KB RAG | 已封装进 `knowledge_search.py` L3 层 |
| `src/lambda_handler.py` | 217 | Lambda 入口 | 非 Lambda 部署，无引用 |
| `src/llm/bedrock.py` | 199 | Bedrock LLM 封装 | `rca_inference.py` 直接调 Bedrock，无引用 |
| `src/prompts/system_v2.py` | 172 | v2 系统提示词 | 无引用，`system.py` 也无引用 |
| `src/cli.py` | 150 | CLI 入口 | 依赖已删除的 `agent.py`，不可用 |
| `src/prompts/system.py` | 112 | v1 系统提示词 | 无引用 |

**小计: 5,140 行**

### 操作
```bash
# 一次性删除全部孤立模块
rm src/tools/kubernetes.py src/analyzers/k8s_analyzers.py src/bedrock_agent.py \
   src/mock.py src/tools/aws.py src/tools/diagnostics.py src/lambda_eks_operations.py \
   src/agent.py src/pattern_rag.py src/lambda_handler.py src/llm/bedrock.py \
   src/prompts/system_v2.py src/cli.py src/prompts/system.py

# 清理空目录
rmdir src/tools/ src/analyzers/ src/llm/ src/prompts/ 2>/dev/null
```

---

## 2. 🟡 合并/替换 — 重复功能模块

### 2.1 `src/multi_agent_voting.py` (265 行) → 已有 `src/voting/__init__.py` (530 行)

- `voting/__init__.py` 已是正式实现，内部 import `multi_agent_voting` 的 `extract_diagnosis` 和 `simple_vote`
- **操作**: 将 `multi_agent_voting.py` 的 `extract_diagnosis()` 和 `simple_vote()` 移入 `voting/__init__.py`，删除 `multi_agent_voting.py`
- `api_server.py` 有 `from src.multi_agent_voting import ...` 需改为 `from src.voting import ...`

### 2.2 `src/operations_knowledge.py` (337 行) → 已是 shim → `knowledge_search.py`

- 文件头已标注 `DEPRECATED: This module is retained for API compatibility`
- **操作**: 将 `api_server.py` 中引用改为 `knowledge_search.py`，删除 shim
- **风险**: 低。shim 只做委托转发。

### 2.3 `src/aws_ops.py` (1,793 行) → 评估保留/瘦身

- `api_server.py` 第 490 行仍引用 `get_aws_ops()` 用于 chat 命令
- 但 31 个方法中**核心管道只用 0 个** — 全部是 chat bot 的 CRUD 封装 (ec2_health_check, rds_get_logs, etc.)
- **操作**: 
  - 如果 chat bot 功能保留 → aws_ops 保留但标注为 "chat-only, not pipeline"
  - 如果 chat bot 功能砍掉 → 直接删除 (1,793 行)
  - **需 Ma Ronnie 确认**

### 2.4 `src/rca/engine.py` (338 行) vs `src/rca_inference.py` (368 行)

- `rca/engine.py` 是 voting-based RCA wrapper，引用 `src.voting`
- `rca_inference.py` 是 Bedrock Claude RCA，核心管道使用
- **操作**: 如果 multi-agent voting RCA 不再需要，删除 `rca/engine.py` 及 `rca/` 下的 `models.py` + `pattern_matcher.py` (合计 ~846 行)
- **需确认**: voting RCA 路径是否保留？

---

## 3. 🟠 api_server.py 瘦身 — 4,703 行 / 132 函数

`api_server.py` 是最大的单文件。问题：

| 问题 | 详情 |
|------|------|
| 全部 132 个 endpoint 在一个文件 | 无 router 拆分 |
| Chat bot 逻辑 inline | 占 ~800 行（关键词匹配 + 格式化） |
| 静态 mock 数据 | 部分 endpoint 返回硬编码数据 |
| 多处 try/except pass | 错误被吞掉 |

**操作 (分阶段)**:
1. **P0**: 清理对已删除模块的 import (operations_knowledge, multi_agent_voting, 等)
2. **P1**: 拆分 router — `routes/chat.py`, `routes/pipeline.py`, `routes/admin.py`
3. **P2**: Chat bot 逻辑抽出 → `src/chat_handler.py`

---

## 4. 🔵 空 `__init__.py` 和空目录清理

删除孤立模块后，以下目录将为空（仅剩 `__init__.py`）：
- `src/tools/` — 3 个文件全删
- `src/analyzers/` — 1 个文件全删
- `src/llm/` — 1 个文件全删
- `src/prompts/` — 2 个文件全删

---

## 5. 📊 清理后预期代码库

| 变化 | 清理前 | 清理后 |
|------|--------|--------|
| src/ 文件数 | 64 | ~46 |
| src/ 行数 | 22,054 | ~15,300 |
| 孤立模块 | 14 | 0 |
| 重复功能 | 6 组 | 0 |
| api_server.py | 4,703 行 | ~4,500 行 (P0 only) |

---

## 6. 执行清单 (Developer 用)

### Phase 1: 安全删除 (无依赖, 零风险)
- [ ] 删除 14 个孤立模块 (Section 1)
- [ ] 删除空目录 `src/tools/`, `src/analyzers/`, `src/llm/`, `src/prompts/`
- [ ] 跑全量测试确认 0 regression

### Phase 2: 合并 (需改 import)
- [ ] `multi_agent_voting.py` → 移入 `voting/__init__.py`，更新 api_server.py import
- [ ] `operations_knowledge.py` → 删除 shim，更新 api_server.py import
- [ ] 跑全量测试确认

### Phase 3: 待确认 (需 Ma Ronnie/Orchestrator 决定)
- [ ] `aws_ops.py` (1,793 行): chat bot 功能是否保留？
- [ ] `rca/engine.py` + `rca/models.py` + `rca/pattern_matcher.py` (846 行): voting RCA 路径是否保留？
- [ ] api_server.py 拆分 router — P1 还是推迟？

---

## 7. ⚠️ 不要动的文件

以下模块是核心管道的一部分，**不要删除或重构**：

| 模块 | 角色 |
|------|------|
| `detect_agent.py` | 数据采集 + 缓存 |
| `event_correlator.py` | AWS 事件采集 |
| `knowledge_search.py` | 统一检索 (L1/L2/L3) |
| `s3_knowledge_base.py` | S3 存储层 |
| `vector_search.py` | OpenSearch kNN |
| `rca_inference.py` | Bedrock RCA |
| `sop_safety.py` | 安全分级 |
| `sop_system.py` | SOP 管理 |
| `incident_orchestrator.py` | 管道编排 |
| `rca_sop_bridge.py` | RCA→SOP 桥接 |
| `proactive_agent.py` | 主动检测 |
| `alarm_webhook.py` | CloudWatch Alarm |
| `health/` | 健康检查 |
| `config.py` | 配置 |
| `utils/time.py` | 时间工具 |

---

*Architect — 📐 严谨务实，先删再建。*
