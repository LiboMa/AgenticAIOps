# AWS MCP Integration Research

## Overview

AWS MCP (Model Context Protocol) is a suite of specialized MCP servers from AWS Labs that enable AI applications to interact with AWS services.

## Available MCP Servers

### Core Servers
| Server | Description | Use Case |
|--------|-------------|----------|
| **AWS MCP Server** | Remote managed server by AWS | All AWS operations |
| **AWS Knowledge MCP** | AWS docs, API references | Documentation |
| **AWS IaC MCP** | CDK/CloudFormation | Infrastructure |
| **CloudWatch Logs MCP** | Log management | Monitoring |
| **Cost Analysis MCP** | Cost Explorer | Cost management |

### Service-Specific Servers
| Server | Service | Capabilities |
|--------|---------|--------------|
| Lambda MCP | AWS Lambda | Function management, invocation |
| EC2 MCP | Amazon EC2 | Instance management |
| S3 MCP | Amazon S3 | Bucket operations |
| RDS MCP | Amazon RDS | Database management |
| EKS MCP | Amazon EKS | Kubernetes cluster management |

## Integration Options

### Option A: AWS Managed MCP Server (Recommended)
```
Endpoint: https://aws-mcp.us-east-1.api.aws/mcp
Features:
- CloudTrail audit logging
- Zero credential exposure
- IAM-based permissions
- All AWS services supported
```

### Option B: Local MCP Servers
```bash
# Install via uvx
uvx awslabs.aws-mcp-server@latest

# Or via pip
pip install mcp-server-aws
```

## Transport Mechanisms
- **stdio** - Supported (primary)
- **SSE** - Removed (May 2025)
- **Streamable HTTP** - Coming soon

## Integration Architecture for AgenticAIOps

```
┌─────────────────────────────────────────────────────────────┐
│                    AgenticAIOps v2                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Chat Interface                                              │
│       │                                                      │
│       ▼                                                      │
│  Agent (Claude)                                              │
│       │                                                      │
│       ▼                                                      │
│  MCP Client                                                  │
│       │                                                      │
│       ├──► AWS MCP Server (remote)                          │
│       │         │                                            │
│       │         ├── EC2 operations                          │
│       │         ├── Lambda operations                       │
│       │         ├── S3 operations                           │
│       │         ├── RDS operations                          │
│       │         └── CloudWatch queries                      │
│       │                                                      │
│       └──► Local MCP Servers (optional)                     │
│                 │                                            │
│                 ├── aws-documentation-mcp                    │
│                 └── aws-iac-mcp                              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Steps

### Phase 1: Basic Integration
1. Install MCP client library
2. Configure AWS credentials
3. Connect to AWS MCP Server
4. Test basic operations (EC2 list, S3 list)

### Phase 2: Chat Integration
1. Register MCP tools with Agent
2. Map chat commands to MCP operations
3. Handle MCP responses in chat UI

### Phase 3: Advanced Features
1. Multi-account support via Assume Role
2. Region switching
3. Operation auditing

## Required IAM Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:StartInstances",
        "ec2:StopInstances",
        "ec2:RebootInstances",
        "lambda:*",
        "s3:*",
        "rds:Describe*",
        "rds:RebootDBInstance",
        "cloudwatch:*",
        "logs:*",
        "sts:AssumeRole"
      ],
      "Resource": "*"
    }
  ]
}
```

## References
- GitHub: https://github.com/awslabs/mcp
- MCP Protocol: https://modelcontextprotocol.io
- AWS Documentation: https://docs.aws.amazon.com/aws-mcp/
