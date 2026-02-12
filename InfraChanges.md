# InfraChanges.md - 基础设施变更记录

> 所有 AWS 资源变更必须用 Terraform IaC 管理，并记录在此文件。

## 变更记录

| 日期 | 变更 | 资源 | Region | Terraform 文件 | 状态 |
|------|------|------|--------|---------------|------|
| (无变更) | — | — | — | — | — |

## 现有资源 (已存在，非本项目创建)

| 资源 | ID/Name | Region | 说明 |
|------|---------|--------|------|
| EC2 | i-080ab08eefa16b539 | ap-southeast-1 | mbot-sg-1 (运行中) |
| EC2 | i-0e6da7fadd619d0a7 | ap-southeast-1 | jump-ab2-db-proxy (运行中) |
| OpenSearch | os2 | ap-southeast-1 | 向量搜索集群 |
| S3 | agentic-aiops-knowledge-base | ap-southeast-1 | 知识库存储 |

## Terraform 目录

```
infra/
├── main.tf           # Provider + backend
├── variables.tf      # 变量定义
├── outputs.tf        # 输出
├── modules/
│   ├── dynamodb/     # 对话历史表 (待创建)
│   └── s3/           # 知识库 bucket (已有)
└── terraform.tfvars  # 环境变量
```

## 规则

1. **任何 AWS 资源变更必须先写 Terraform**
2. **变更前记录在此文件**
3. **描述简洁清晰**
4. **包含 region、资源类型、变更原因**
