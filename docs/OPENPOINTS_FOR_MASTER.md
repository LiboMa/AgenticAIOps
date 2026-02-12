# OPENPOINTS_FOR_MASTER.md

> 需要 Ma Ronnie 介入解决的问题。请保持简洁。

---

## 🔴 阻塞项

| # | 问题 | 影响 | 需要什么 |
|---|------|------|---------|
| 1 | OpenSearch os2 权限不足 | 无法写入知识库向量数据 | 配置 fine-grained access control 或提供 master user |
| 2 | DynamoDB 对话持久化 | 刷新页面对话丢失 | 批准创建 DynamoDB 表 (或确认用 S3 替代) |

## 🟡 待确认

| # | 问题 | 背景 | 选项 |
|---|------|------|------|
| 3 | DevOps Guru 资源覆盖 | 已启用但 0 insights，需配置覆盖范围 | A) 配置全部资源 B) 仅 EC2+RDS C) P1 再做 |
| 4 | CloudWatch Anomaly Detector 扩展 | 当前仅 1 个 (EC2 CPU)，需更多指标 | 批准批量创建 (~10 个 detector) |

## ✅ 已解决

_暂无_

---

*最后更新: 2026-02-12*
