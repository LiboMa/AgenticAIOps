# AgenticAIOps IaC Resources

## Resource Summary

| Resource | Type | ID/ARN |
|----------|------|--------|
| IAM Role | IAM | AgenticAIOps-KB-Role |
| S3 Bucket | S3 | agentic-aiops-kb-1769960769 |
| AOSS Collection | OpenSearch Serverless | pfa6wvl941lbwaihiz54 |
| AOSS Index | OpenSearch Index | agentic-aiops-index |
| Knowledge Base | Bedrock | BUE4YPV3JD |
| Data Source | Bedrock | LLPNALBXEC |

## Directory Structure

```
iac/
├── iam/
│   ├── kb-trust-policy.json
│   ├── kb-s3-access-policy.json
│   ├── kb-aoss-access-policy.json
│   └── kb-bedrock-embedding-policy.json
├── aoss/
│   ├── encryption-policy.json
│   ├── network-policy.json
│   └── data-access-policy.json
├── bedrock/
│   ├── knowledge-base.json
│   └── data-source.json
└── README.md
```

## AWS CLI Commands

### Create IAM Role
```bash
aws iam create-role --role-name AgenticAIOps-KB-Role \
    --assume-role-policy-document file://iac/iam/kb-trust-policy.json

aws iam put-role-policy --role-name AgenticAIOps-KB-Role \
    --policy-name S3Access --policy-document file://iac/iam/kb-s3-access-policy.json

aws iam put-role-policy --role-name AgenticAIOps-KB-Role \
    --policy-name AOSSAccess --policy-document file://iac/iam/kb-aoss-access-policy.json

aws iam put-role-policy --role-name AgenticAIOps-KB-Role \
    --policy-name BedrockEmbedding --policy-document file://iac/iam/kb-bedrock-embedding-policy.json
```

### Create OpenSearch Serverless
```bash
# See aoss/*.json for policy definitions
aws opensearchserverless create-security-policy --name agentic-aiops-kb-encryption --type encryption ...
aws opensearchserverless create-security-policy --name agentic-aiops-kb-network --type network ...
aws opensearchserverless create-access-policy --name agentic-aiops-kb-data --type data ...
aws opensearchserverless create-collection --name agentic-aiops-kb --type VECTORSEARCH
```

### Create Knowledge Base
```bash
aws bedrock-agent create-knowledge-base --cli-input-json file://iac/bedrock/knowledge-base.json
aws bedrock-agent create-data-source --cli-input-json file://iac/bedrock/data-source.json
aws bedrock-agent start-ingestion-job --knowledge-base-id BUE4YPV3JD --data-source-id LLPNALBXEC
```
