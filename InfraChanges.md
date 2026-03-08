# InfraChanges.md

> 所有 AWS 资源变更记录。每次变更必须有 Terraform IaC。

---

## 变更记录

| 日期 | 变更 | 资源 | Region | Terraform | 状态 |
|------|------|------|--------|-----------|------|
| 2026-02-12 | OpenSearch os2 FGAC: 设置 iam-mbot-role 为 master user | OpenSearch os2 | ap-southeast-1 | `infra/terraform/opensearch_fgac.tf` | ✅ Applied |

---

## 现有资源 (Baseline)

| 资源 | ID/名称 | Region | 备注 |
|------|---------|--------|------|
| EC2 | i-080ab08eefa16b539 (mbot-sg-1) | ap-southeast-1 | 主服务器 |
| EC2 | i-0e6da7fadd619d0a7 (jump-ab2-db-proxy) | ap-southeast-1 | DB Proxy |
| OpenSearch | os2 (3节点 r7g.large) | ap-southeast-1 | 向量搜索, FGAC enabled |
| S3 | agentic-aiops-knowledge-base | ap-southeast-1 | 知识库 |
| DevOps Guru | 已启用 | ap-southeast-1 | 0 insights |

---

## 区域规则
- **所有资源**: ap-southeast-1
- **Bedrock**: 单独区域 (global endpoint)

---

*最后更新: 2026-02-12 19:56 UTC*
