# OPENPOINTS_FOR_MASTER.md

> 需要 Ma Ronnie 介入解决的问题。请保持简洁。

---

## 🔴 阻塞项

_无_

## 🟡 待确认

| # | 问题 | 背景 | 选项 |
|---|------|------|------|
| 3 | DevOps Guru 资源覆盖 | 已启用但 0 insights，需配置覆盖范围 | 团队可自行配置 |
| 4 | CloudWatch Anomaly Detector 扩展 | 当前仅 1 个 (EC2 CPU)，需更多指标 | 团队可自行创建 |

## ✅ 已解决

| # | 问题 | 解决方式 | 日期 |
|---|------|---------|------|
| 1 | OpenSearch os2 权限 | AWS CLI: iam-mbot-role 设为 master user + sigv4 认证 | 2026-02-12 |
| 2 | DynamoDB 对话持久化 | 降级为 P1，先用 S3/内存 | 2026-02-12 |

## ✅ 已解决

_暂无_

---

*最后更新: 2026-02-12*
