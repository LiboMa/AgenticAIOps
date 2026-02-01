# AgenticAIOps MVP - 优化计划

## 当前状态
- ✅ MVP 本地测试通过 (2026-02-01)
- ✅ Lambda 部署完成
- ✅ Bedrock Agent 创建完成
- ⏳ 等待用户完成 MVP 验收测试

---

## Phase 2 优化点

### 1. Intent 分类层 ⭐⭐⭐ (高优先级)
**来源**: SHREC 论文 (华为)

在工具选择前加入意图识别，提高准确性：

```python
INTENT_TYPES = {
    "diagnose_cluster": {
        "description": "集群健康检查、问题诊断",
        "tools": ["get_cluster_health", "get_pod_status", "describe_pod"]
    },
    "analyze_logs": {
        "description": "日志分析、错误排查", 
        "tools": ["get_pod_logs", "get_events"]
    },
    "scale_resources": {
        "description": "扩缩容操作",
        "tools": ["scale_deployment", "get_node_capacity"]
    },
    "restart_service": {
        "description": "重启、回滚操作",
        "tools": ["restart_deployment", "rollback_deployment"]
    },
    "investigate_alert": {
        "description": "告警调查",
        "tools": ["get_events", "get_metrics", "get_logs"]
    }
}
```

### 2. 多 Agent 投票机制 ⭐⭐ (中优先级)
**来源**: mABC 论文

多个 Agent 诊断同一问题，投票决定最终答案，减少幻觉：

```
问题: "为什么 Pod 一直重启?"

Agent-Diagnostician → OOMKilled (0.8)
Agent-Validator     → OOMKilled (0.9)  
Agent-Investigator  → CrashLoop (0.6)

投票结果 → OOMKilled ✅ (2/3 一致)
```

### 3. 操作序列推荐 ⭐⭐ (中优先级)
**来源**: SHREC 论文

基于历史操作推荐下一步：

```
用户执行: get_pod_status → 发现 CrashLoop
系统推荐: 
  1. get_pod_logs (查看错误日志)
  2. describe_pod (查看详细状态)
  3. restart_deployment (如果需要重启)
```

### 4. 知识图谱 ⭐ (低优先级)
建模 EKS 资源关系：
- Cluster → NodeGroup → Node → Pod → Container
- Service → Deployment → ReplicaSet → Pod

---

## 参考论文

| 论文 | 引用数 | 关键点 |
|------|--------|--------|
| AutoGen: Multi-Agent Conversation | 958 | 多 Agent 对话框架 |
| mABC | - | 投票机制减少幻觉 |
| SHREC | - | SRE 知识图谱 + 序列推荐 |
| AIOpsLab | - | Agent 评估框架 |
| K8sGPT | - | K8s 诊断工具 |

---

## 更新记录
- 2026-02-01: 初始创建，记录 Phase 2 优化点
