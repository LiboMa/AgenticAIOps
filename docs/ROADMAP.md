# AgenticAIOps Roadmap

**更新日期**: 2026-02-02  
**维护者**: Architect

---

## 开发进度总览

```
✅ Phase 1: Plugin System           - 完成 (2026-02-01)
✅ Phase 2: Manifest/Schema         - 完成 (2026-02-01)
✅ Phase 3: ACI + Multi-Agent Voting - 完成 (2026-02-02)
✅ Phase 4: 实际场景集成             - 完成 (2026-02-02)
🔄 Phase 5: 主动式运维 + 自动修复    - 进行中
📋 Phase 6: Knowledge Base 增强     - 计划中
📋 Phase 7: GraphRAG 因果推理       - 计划中
```

---

## Phase 5: 主动式运维 + 自动修复 (当前)

**目标**: 实现主动 Health Check、异常检测、根因分析、自动修复

**技术栈** (团队投票决定):
- 异常检测: 规则引擎 + 基线检测
- Tracing: Jaeger
- Issue Store: SQLite → Redis
- 示例应用: Bookinfo (Istio)
- 定时任务: APScheduler

### 5.1 Health Check 机制
- [ ] 定时巡检 (APScheduler)
- [ ] ACI 数据采集 (Events, Metrics, Logs)
- [ ] 异常模式匹配

### 5.2 Root Cause Pattern 规则库 (MVP)
- [ ] YAML 配置的 Pattern 规则
- [ ] 症状 → 根因 → 修复建议 映射
- [ ] Severity 自动分级 (低/中/高)

```yaml
# 规则库示例
patterns:
  - name: "OOM Chain"
    symptoms: ["OOMKilled", "memory > 90%"]
    root_cause: "内存限制过低或内存泄漏"
    severity: medium
    remediation: "increase_memory_limit"
```

### 5.3 自动修复机制
- [ ] 低风险: 自动执行 (Pod 重启, 清理)
- [ ] 中风险: 自动执行 + 通知 + 可回滚
- [ ] 高风险: 仅建议, 人工确认
- [ ] Runbook 库 (YAML 配置)
- [ ] dry-run 模式 (安全测试)

### 5.4 Issue Center
- [ ] Issue Store (SQLite)
- [ ] Issue API (CRUD)
- [ ] 前端 Issue Center Tab
- [ ] Card 展示 (待确认/已修复/监控中)

### 5.5 Tracing 集成
- [ ] Jaeger 部署
- [ ] Bookinfo 微服务部署
- [ ] Span 异常检测 (慢请求, 错误链路)

**预估工期**: 9-10 天

---

## Phase 6: Knowledge Base 增强 (计划)

**目标**: 引入向量知识库，支持历史案例语义搜索

### 6.1 Vector Knowledge Base
- [ ] Bedrock Knowledge Base 或 FAISS
- [ ] Issue 历史向量化存储
- [ ] 相似案例检索

### 6.2 RAG 增强
- [ ] 历史案例上下文注入
- [ ] 相似问题推荐
- [ ] 修复方案参考

**预估工期**: 3-4 天

---

## Phase 7: GraphRAG 因果推理 (计划)

**目标**: 构建运维知识图谱，支持因果链推理

### 7.1 Knowledge Graph
- [ ] 服务依赖图自动构建 (从 K8s)
- [ ] 故障传播路径分析
- [ ] 因果关系建模

### 7.2 GraphRAG
- [ ] Neptune 或 Neo4j 部署
- [ ] LangChain GraphRAG 集成
- [ ] 多跳因果推理

**预估工期**: 5-7 天

---

## 技术栈总览

| 组件 | Phase 5 (MVP) | Phase 6+ |
|------|---------------|----------|
| 异常检测 | 规则引擎 | + ML 检测 |
| 模式匹配 | YAML 规则库 | + Vector KB |
| 因果推理 | - | GraphRAG |
| Tracing | Jaeger | + OpenTelemetry |
| Issue Store | SQLite | Redis + PostgreSQL |
| 定时任务 | APScheduler | Celery |

---

## 里程碑

| 里程碑 | 目标日期 | 状态 |
|--------|----------|------|
| Phase 5 MVP | 2026-02-12 | 🔄 进行中 |
| Phase 6 KB | 2026-02-16 | 📋 计划 |
| Phase 7 Graph | 2026-02-23 | 📋 计划 |

---

## 参考文档

- [ACI_DESIGN.md](designs/ACI_DESIGN.md) - Agent-Cloud Interface
- [VOTING_DESIGN.md](designs/VOTING_DESIGN.md) - Multi-Agent Voting
- [PHASE4_SCENARIOS.md](designs/PHASE4_SCENARIOS.md) - 故障注入场景
- [FRONTEND_API_DESIGN.md](designs/FRONTEND_API_DESIGN.md) - 前端 API
- [MULTI_CLUSTER_DESIGN.md](designs/MULTI_CLUSTER_DESIGN.md) - 多集群架构

---

**Last Updated**: 2026-02-02 by Architect
