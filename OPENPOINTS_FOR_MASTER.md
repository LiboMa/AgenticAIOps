# OPENPOINTS_FOR_MASTER.md
> 需要 Ma Ronnie 介入的问题。简洁描述，按优先级排列。

---

## P0 (阻塞开发)

*无阻塞项 ✅*

## P1 (不阻塞，团队可自行处理)

| # | 问题 | 影响 | 需要的操作 |
|---|------|------|-----------|
| 1 | CW Anomaly Detector 仅 1 个 | RCA 数据不足 | 团队用 boto3 + Terraform 批量创建 |
| 2 | DevOps Guru 0 insights | 未配置资源覆盖 | P1 阶段再处理 |
| 3 | S3 bucket `agentic-aiops-knowledge-base` 确认 | SOP/Knowledge 持久化 | 团队验证并自行创建 |

## 已解决 ✅

| # | 问题 | 解决方式 |
|---|------|---------|
| - | OpenSearch os2 FGAC 403 | ✅ AWS CLI 设置 IAM role 为 master user |
| - | GitHub 认证 | ✅ Ma Ronnie 完成 |
| - | SSM Agent | ✅ 2 台 EC2 Online |
| - | AWS Admin 权限 | ✅ iam-mbot-role |
| - | Region 确认 | ✅ ap-southeast-1 (Bedrock 除外) |

---
*最后更新: 2026-02-12 19:57 UTC*
