# InfraChanges.md
> 所有基础设施变更记录。每次变更必须有 Terraform 代码。

---

## 当前基础设施 (ap-southeast-1)

| 资源 | 名称/ID | 状态 |
|------|---------|------|
| EC2 | i-080ab08eefa16b539 (mbot-sg-1) | ✅ running |
| EC2 | i-0e6da7fadd619d0a7 (jump-ab2-db-proxy) | ✅ running |
| OpenSearch | os2 cluster | ✅ active |
| S3 | agentic-aiops-knowledge-base | ⚠️ 待确认 |

## 变更记录

| 日期 | 变更 | Terraform 文件 | 操作人 | 状态 |
|------|------|---------------|--------|------|
| 2026-02-12 | OpenSearch os2: FGAC master user → iam-mbot-role IAM ARN | infra/opensearch.tf (TODO) | Developer (AWS CLI) | ✅ Applied |

---

## 规则
1. **每次** 创建/修改 AWS 资源必须先写 Terraform
2. Terraform 文件存放: `infra/terraform/`
3. 变更前记录在此文件
4. 描述简洁清晰

---
*最后更新: 2026-02-12 19:53 UTC*
