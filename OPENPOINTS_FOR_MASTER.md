# OPENPOINTS_FOR_MASTER.md
> 需要 Ma Ronnie 介入的问题。简洁描述，按优先级排列。

---

## P0 (阻塞开发)

| # | 问题 | 影响 | 需要的操作 |
|---|------|------|-----------|
| 1 | S3 bucket `agentic-aiops-knowledge-base` 不存在 | SOP/Knowledge 持久化失败 (Bug-005) | 确认正确 bucket 名称或创建 |
| 2 | OpenSearch (os2) 权限未配置 | 向量搜索 (P2 Sprint) 阻塞 | IAM Role Mapping 或 Master User 凭证 |

## P1 (不阻塞但需确认)

| # | 问题 | 影响 | 需要的操作 |
|---|------|------|-----------|
| 3 | CloudWatch Anomaly Detector 仅 1 个 (EC2 CPU) | RCA 数据源不足 | 确认是否批量创建更多 detector |
| 4 | DevOps Guru 已启用但 0 insights | 可能未配置资源覆盖范围 | 确认是否配置资源覆盖 |

## P2 (需确认)

| # | 问题 | 影响 | 需要的操作 |
|---|------|------|-----------|
| 5 | Region 确认 | Ma Ronnie 提到 us-east-1，但主资源在 ap-southeast-1 | 确认是否有跨区域资源需覆盖 |

## 已解决 ✅

| # | 问题 | 解决方式 |
|---|------|---------|
| - | GitHub 认证 | ✅ 已完成 (LiboMa) |
| - | 模型/上下文不一致 | ✅ Gateway restart 解决 |
| - | AWS Admin 权限 | ✅ 已确认有 admin role |

---
*最后更新: 2026-02-12 19:53 UTC*
