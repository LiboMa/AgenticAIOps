# SOP ↔ RCA 闭环增强 - 测试计划

## 测试目标
验证 SOP 与 RCA 之间的闭环: 告警 → RCA → SOP 推荐 → 执行 → 验证 → 知识库学习

---

## 1. RCA → SOP 自动推荐

| 测试编号 | 测试用例 | 预期结果 | 优先级 |
|---------|---------|---------|-------|
| RS-001 | RCA 检测到 EC2 High CPU | 自动推荐 "EC2 High CPU" SOP | P0 |
| RS-002 | RCA 检测到 RDS 连接异常 | 自动推荐 "RDS Failover" SOP | P0 |
| RS-003 | RCA 检测到 Lambda 错误率升高 | 自动推荐 "Lambda Error" SOP | P0 |
| RS-004 | RCA 无匹配 SOP | 返回 "无匹配SOP，建议创建" | P0 |
| RS-005 | RCA 多问题同时检测 | 按严重性排序推荐多个 SOP | P1 |
| RS-006 | RCA 置信度低 (<50%) | 标注 "低置信度"，仍推荐但需人工确认 | P1 |

## 2. SOP 执行结果 → Knowledge 反馈

| 测试编号 | 测试用例 | 预期结果 | 优先级 |
|---------|---------|---------|-------|
| SK-001 | SOP 执行成功 | 结果写入 Knowledge (pattern 强化) | P0 |
| SK-002 | SOP 执行失败 | 失败原因写入 Knowledge (pattern 更新) | P0 |
| SK-003 | SOP 部分步骤成功 | 记录到达哪一步 + 失败原因 | P0 |
| SK-004 | 相同 SOP 多次执行 | Knowledge 中 occurrence_count 递增 | P1 |
| SK-005 | SOP 执行后再次发生相同告警 | Knowledge 检索到历史执行记录 | P1 |

## 3. RCA 功能增强

| 测试编号 | 测试用例 | 预期结果 | 优先级 |
|---------|---------|---------|-------|
| RC-001 | "analyze high cpu on i-xxx" | 查询 CloudWatch 指标 + 分析 | P0 |
| RC-002 | RCA 结合 Knowledge 历史模式 | 返回历史相似事件 + 解决方案 | P0 |
| RC-003 | RCA 报告持久化到 S3 | 重启后报告不丢失 | P0 |
| RC-004 | RCA 多数据源关联分析 | CloudWatch + 日志 + 指标 综合 | P1 |
| RC-005 | RCA 结果包含置信度评分 | response 中有 confidence 字段 | P1 |
| RC-006 | RCA 时间线生成 | 按时间排列事件链 | P1 |

## 4. 闭环集成测试

| 测试编号 | 测试用例 | 预期结果 | 优先级 |
|---------|---------|---------|-------|
| CL-001 | 完整闭环: 告警→RCA→SOP→执行→学习 | 端到端完整流程 | P0 |
| CL-002 | 告警触发 → 自动 RCA | 无需人工输入 chat 命令 | P1 |
| CL-003 | RCA→SOP 推荐→用户确认→执行 | 危险操作需确认 | P0 |
| CL-004 | 闭环速度: 告警→SOP 推荐 < 30s | 性能要求 | P1 |
| CL-005 | 第二次相同告警 → 更快解决 | 从知识库直接匹配，跳过深度 RCA | P1 |

## 5. SOP 扩展测试

| 测试编号 | 测试用例 | 预期结果 | 优先级 |
|---------|---------|---------|-------|
| SE-001 | 验证现有 3 个 SOP 完整性 | EC2/RDS/Lambda SOP 可执行 | P0 |
| SE-002 | 新增 SOP: ELB 5xx 错误 | 可创建并执行 | P1 |
| SE-003 | 新增 SOP: S3 权限异常 | 可创建并执行 | P1 |
| SE-004 | 自定义 SOP (用户创建) | 通过 chat 创建自定义 SOP | P1 |
| SE-005 | SOP 步骤回滚 | 执行失败后自动回滚 | P2 |

---

## 测试策略
1. **P0 先行**: 先测 RCA→SOP 推荐 + 执行结果反馈 + 持久化
2. **闭环验证**: CL-001 是核心验收标准
3. **回归测试**: 确保现有 SOP/RCA 命令不受影响
4. **性能**: 闭环响应 < 30s

## 当前代码基线
```
src/sop_system.py (584行) - SOP 存储/执行
src/operations_knowledge.py (419行) - Pattern 学习
src/vector_search.py (436行) - 向量搜索
api_server.py - RCA API + Chat 路由
```

---
*Tester | 2026-02-12*
