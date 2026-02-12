# InfraChanges.md

> 所有 AWS 资源变更记录。必须有对应 Terraform 代码。保持简洁。

---

## 变更记录

| 日期 | 变更 | Region | Terraform | 状态 |
|------|------|--------|-----------|------|
| 2026-02-12 | OpenSearch os2: master user 从内部用户切换为 IAM role `iam-mbot-role` | ap-southeast-1 | 待补 TF | Processing |

## 已有资源 (非本项目创建)

| 资源 | Region | 说明 |
|------|--------|------|
| EC2 x14 | ap-southeast-1 | 含 mbot-sg-1 |
| OpenSearch os2 | ap-southeast-1 | 3 节点集群 |
| S3 agentic-aiops-* | ap-southeast-1 | 知识库存储 |
| CloudWatch Anomaly x1 | ap-southeast-1 | EC2 CPU detector |
| DevOps Guru | ap-southeast-1 | 已启用，0 insights |
| DynamoDB (FrrSensor, Music) | ap-southeast-1 | 非本项目 |

## Terraform 目录

```
infra/terraform/
├── (待创建)
```

---

*规则: 任何新资源必须先写 Terraform，再 apply。变更记录在此文件。*

*最后更新: 2026-02-12*
