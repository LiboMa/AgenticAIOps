# 📐 架构差异报告 — Architecture vs Reality Gap Report

**作者**: Architect  
**日期**: 2026-02-13 15:45 UTC  
**基于**: `docs/ARCHITECTURE.md` v3.0 vs 当前代码库实际状态  
**背景**: Ma Ronnie 指令 — "向我汇报架构差异，做一次大清理，将无用的文档和代码全部清除。"

---

## 0. 总结

| 维度 | 状态 |
|------|------|
| **ARCHITECTURE.md 准确度** | ~85% → 100% (6 处已修正) |
| **Phase 1 清理 (14 孤立模块)** | ✅ 已完成，-5,140 行 |
| **Phase 2 合并 (shims + duplicates)** | ✅ 已完成，-602 行 |
| **Phase 3 根脚本 + 文档** | ✅ 已完成，-2,220 行代码 + 9 个文档 |
| **Phase 4 待决 (aws_ops + rca/engine + papers)** | ❌ 等 Ma Ronnie 确认 |
| **总清理量** | ~7,962 行代码 + 9 文档 + 1 目录 |
| **回归测试** | 555 passed, 2 skipped, 0 failed |

---

## 1. ARCHITECTURE.md 修正记录 (6 处, 均已完成)

| # | 修正 | Commit |
|---|------|--------|
| 1 | 删除 `operations_knowledge.py` 条目 (§3.2 + §6) | 2ba0c42 / 已更新 |
| 2 | `detect_agent.py` 行数 374 → 418 | 已更新 |
| 3 | `knowledge_search.py` 行数 375 → 665 | 已更新 |
| 4 | 已知限制: 移除已完成的 P1 项 (Pattern Match + Vectorize + S3) | 已更新 |
| 5 | 目录结构: 删除不存在的 `config/sops/` `config/patterns/` | 已更新 |
| 6 | 目录结构: 添加 `agents/`, 更新 tests 计数 | 已更新 |

---

## 2. 已执行清理

### Phase 1: 14 孤立模块 (c5f44e5)
- `src/tools/`, `src/analyzers/`, `src/llm/`, `src/prompts/` — 全部删除
- `src/bedrock_agent.py`, `src/mock.py`, `src/agent.py`, `src/cli.py`, etc.
- **-5,140 行**

### Phase 2: 合并 (2ba0c42)
- `operations_knowledge.py` shim → 合并进 `knowledge_search.py`
- `multi_agent_voting.py` → 合并进 `voting/__init__.py`
- **-602 行**

### Phase 3: 根脚本 + 文档 (b639682, 3602839)
- 10 个根目录测试/实验脚本删除 (-2,220 行)
- 8 个已实现设计文档归档到 `docs/designs/archive/`
- 9 个无用文档删除:
  - `AGENT_APPS_SETUP.md`, `ROADMAP.md`, `CLEANUP_GAP_REPORT.md`
  - `CHATBOX_MULTIMODEL_DESIGN.md` + 测试计划
  - `FRONTEND_API_DESIGN.md`, `FRONTEND_DESIGN_SPEC_V2.md`
  - `MULTI_CLUSTER_DESIGN.md`, `BRAINSTORMING_PRODUCTION_MULTIACCOUNTS.md`
- 空目录 `docs/analysis/` 删除
- 1,438 `.pyc` 文件清理

---

## 3. 待 Ma Ronnie 决定

| # | 目标 | 行数 | 问题 |
|---|------|------|------|
| 1 | `src/aws_ops.py` | 1,793 | 核心管道 0 引用，仅 chat bot。Chat 保留？ |
| 2 | `src/rca/` (engine + models + pattern_matcher) | 846 | Voting RCA 路径。只留 Bedrock RCA？ |
| 3 | `docs/papers/` (11 PDF) | 55MB | 移 S3 还是留 repo？ |
| 4 | `src/aci/context/__init__.py` | 3 | 空 placeholder |
| 5 | `src/aci/models.py` | 167 | 0 运行时引用 |

---

## 4. 当前代码库状态

| 指标 | 清理前 | 清理后 |
|------|--------|--------|
| src/ 文件数 | 64 | 46 |
| src/ 总行数 | ~22,000 | ~16,656 |
| 孤立模块 | 14 | 0 |
| 根目录脚本 | 10+ | 1 (api_server.py) |
| 测试 | 455 | 555 passed |
| 文档 (活跃) | 25+ | 16 |

---

*📐 Architect — 清理完成，ARCHITECTURE.md 已与代码库 100% 对齐。等 Ma Ronnie Phase 4 决定。*
