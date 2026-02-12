# OPENPOINTS_FOR_MASTER.md

> 需要 Ma Ronnie 介入解决的问题。请保持简洁。

## 🔴 阻塞项

| # | 问题 | 影响 | 需要 |
|---|------|------|------|
| 1 | OpenSearch Fine-Grained Access Control 未配置 | 向量搜索 (P2) 无法使用 | 配置 os2 集群的 master user 映射到 IAM role |

## 🟡 需确认

| # | 问题 | 当前处理 |
|---|------|----------|
| 1 | CW Anomaly Detector 仅 1 个 (EC2 CPU) | 需批量创建更多 detector，我们可自行用 boto3 执行，请确认 |
| 2 | DevOps Guru 资源覆盖范围为空 | P1 再配置，当前跳过 |

## ✅ 已自行解决

| # | 问题 | 解决方案 |
|---|------|----------|
| 1 | GitHub 认证 | Ma Ronnie 已完成 gh auth |
| 2 | SSM Agent 状态 | 2 台 EC2 均 Online |

---
*最后更新: 2026-02-12 19:49 UTC*
