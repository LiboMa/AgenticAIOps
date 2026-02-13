# L4 AgenticOps 验收测试计划

> 目标: 验证系统从 L3 (人工确认执行) 升级到 L4 (全自动闭环+自学习)

---

## L3 → L4 差距分析

| 能力 | L3 (当前) | L4 (目标) | 差距 |
|------|----------|----------|------|
| 触发 | 手动 `incident run` | EventBridge 自动触发 | 需实现 |
| 数据采集 | ✅ 真实 AWS 数据 | ✅ 已达成 | - |
| RCA 推理 | ✅ Claude Sonnet | + RAG 知识库增强 | 需实现 |
| SOP 匹配 | ❌ 0 results (S3缺失) | 10+ SOP 自动匹配 | 需修复 |
| 安全执行 | ✅ L0-L3 分级 | ✅ 已达成 | - |
| 学习闭环 | ❌ 未实现 | 执行结果→pattern 强化 | 需实现 |
| 预测 | ❌ 未实现 | CW Anomaly → 预警 | P2 |

---

## 测试用例

### T-L4-001: EventBridge 自动触发
```
前置: CloudWatch Alarm → SNS → EventBridge → Lambda/API
步骤:
1. 模拟 CloudWatch Alarm 触发
2. 验证 incident_orchestrator.handle_incident() 自动被调用
3. 验证 trigger_type = "alarm"
4. 验证完整管道执行 < 25s
预期: 告警→闭环自动启动，无人工介入
```

### T-L4-002: SOP 匹配 (Bug-005 修复后)
```
前置: SOP 存储正常工作 (本地或S3)
步骤:
1. 触发 incident run
2. RCA 识别出 "EC2 高 CPU"
3. SOP 匹配返回 sop-ec2-high-cpu
4. Safety 检查返回 L1 NOTIFY
预期: matched_sops ≥ 1, 自动推荐正确 SOP
```

### T-L4-003: L0/L1 自动执行
```
前置: SOP 匹配成功 + L0/L1 SOP
步骤:
1. incident run auto
2. 匹配到 L0 或 L1 SOP
3. 安全检查通过
4. SOP 自动执行
5. 执行结果记录
预期: L0/L1 SOP 无需人工确认，直接执行
```

### T-L4-004: L2/L3 审批流
```
前置: SOP 匹配到 L3 SOP
步骤:
1. incident run → 匹配 sop-rds-failover (L3)
2. 自动创建 approval request
3. Chat 通知: "需要审批: approval-xxx"
4. admin 执行 approve <id>
5. SOP 执行
预期: L3 需审批，审批后自动执行
```

### T-L4-005: Feedback Loop (学习闭环)
```
前置: Feedback loop 已实现
步骤:
1. 执行 SOP 后记录结果 (成功/失败)
2. 成功 → bridge.record_success(pattern_id, sop_id)
3. 下次相同 pattern → 匹配 confidence 提升
4. 失败 → confidence 降低，建议替代 SOP
预期: 系统从执行结果中学习，匹配精度持续提升
```

### T-L4-006: RAG 知识库增强 RCA
```
前置: OpenSearch 向量搜索已集成
步骤:
1. 历史事件存入 OpenSearch (embedding)
2. 新事件触发 → Claude 分析 + RAG 检索相似案例
3. RCA 结果包含历史参考
预期: confidence 提升 5-10%, 根因分析更准确
```

### T-L4-007: 冷却期 + 断路器 端到端
```
步骤:
1. incident run auto → L1 SOP 执行成功
2. 5分钟内再次触发 → 冷却期拦截
3. 连续触发 20 次 → 断路器拦截
预期: 安全机制在真实管道中生效
```

### T-L4-008: Dry-Run 端到端
```
步骤:
1. incident run dry
2. 完整管道执行: 采集→推理→匹配→安全检查
3. 不执行任何 SOP
4. 返回完整预览报告
预期: 零副作用，完整预览
```

### T-L4-009: 错误优雅降级
```
步骤:
1. 断开 AWS 网络 → 采集失败
2. Bedrock 不可用 → RCA 降级为 pattern match
3. S3 不可用 → SOP 匹配用本地缓存
4. 每种失败都应返回部分结果，不崩溃
预期: 单点失败不导致全管道崩溃
```

### T-L4-010: 管道性能
```
步骤:
1. 10 次 incident run
2. 记录每次各阶段耗时
3. 计算 P50/P95/P99
预期:
├── P50 < 20s
├── P95 < 30s
└── P99 < 45s
```

---

## 覆盖率目标

| 模块 | 单元测试 | 集成测试 | E2E 测试 |
|------|---------|---------|---------|
| event_correlator.py | ✅ | ✅ | ✅ |
| rca_inference.py | ✅ | ✅ | ⏳ |
| sop_safety.py | ✅ | ✅ | ⏳ |
| incident_orchestrator.py | ⏳ | ✅ | ⏳ |
| feedback_loop (新) | ⏳ | ⏳ | ⏳ |
| 前端 AgentChat | ✅ 24/24 E2E | - | ✅ |

---

## 当前可执行测试

| ID | 测试 | 状态 | 备注 |
|----|------|------|------|
| T-L4-001 | EventBridge 触发 | ⏳ 待实现 | 需 EventBridge + Lambda |
| T-L4-002 | SOP 匹配 | ⏳ 待 Bug-005 修复 | |
| T-L4-003 | L0/L1 自动执行 | ⏳ 待 SOP 匹配 | |
| T-L4-004 | L2/L3 审批 | ⏳ 待 SOP 匹配 | |
| T-L4-005 | Feedback Loop | ⏳ 待实现 | |
| T-L4-006 | RAG 增强 | ⏳ 待实现 | |
| T-L4-007 | 冷却+断路器 | ✅ 已验证 (单元) | 待端到端 |
| T-L4-008 | Dry-Run | ✅ 已验证 | 20.7s |
| T-L4-009 | 错误降级 | ⏳ 待测 | |
| T-L4-010 | 性能基准 | ⏳ 待测 | |

---

*最后更新: 2026-02-13 00:36 UTC*
*Tester: @cloud-mbot-tester*
