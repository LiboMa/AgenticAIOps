# AgenticAIOps for EKS - MVP Architecture

## Overview

An LLM-powered agent that can understand, diagnose, and remediate issues in Amazon EKS clusters through natural language interaction.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Interface                               │
│                    (Slack / CLI / Web Chat)                         │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      AgenticAIOps Core                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    LLM Agent (Claude/GPT)                    │   │
│  │                                                               │   │
│  │  • Intent Recognition                                        │   │
│  │  • Action Planning                                           │   │
│  │  • Result Interpretation                                     │   │
│  │  • Natural Language Response                                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     Tool Registry                            │   │
│  │                                                               │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │   │
│  │  │ kubectl  │  │ AWS SDK  │  │CloudWatch│  │   Helm   │    │   │
│  │  │  Tools   │  │  Tools   │  │  Tools   │  │  Tools   │    │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         AWS Environment                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │     EKS      │  │  CloudWatch  │  │     EC2      │              │
│  │   Cluster    │  │    Logs &    │  │   (Nodes)    │              │
│  │              │  │   Metrics    │  │              │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. LLM Agent
- Receives natural language requests
- Plans multi-step actions
- Interprets results and provides recommendations
- Maintains conversation context

### 2. Tool Registry
A set of callable tools the agent can use:

#### Kubernetes Tools (kubectl wrapper)
- `get_pods` - List pods with status
- `get_pod_logs` - Fetch pod logs
- `describe_pod` - Get detailed pod info
- `get_events` - Cluster events
- `get_deployments` - Deployment status
- `scale_deployment` - Scale replicas
- `restart_deployment` - Rolling restart
- `rollback_deployment` - Rollback to previous version

#### AWS Tools
- `describe_cluster` - EKS cluster info
- `list_nodegroups` - Node group details
- `get_node_health` - EC2 node status
- `get_cloudwatch_metrics` - Cluster metrics
- `get_cloudwatch_logs` - Application logs

#### Diagnostic Tools
- `analyze_pod_issues` - Automated issue detection
- `check_resource_usage` - CPU/Memory analysis
- `connectivity_test` - Network diagnostics

### 3. Safety Layer
- Read-only mode by default
- Action confirmation for destructive operations
- Audit logging of all actions
- Rollback capability

## MVP Scope

### Phase 1: Read Operations (Day 1)
- [ ] Query cluster state
- [ ] View pod logs and events
- [ ] Basic diagnostics
- [ ] Natural language responses

### Phase 2: Write Operations (Day 2+)
- [ ] Scale deployments
- [ ] Restart pods
- [ ] Rollback deployments
- [ ] With human approval flow

## Technology Stack

- **Language**: Python 3.11+
- **LLM Framework**: LangChain or direct API
- **Kubernetes Client**: kubernetes-client/python
- **AWS SDK**: boto3
- **Interface**: CLI (MVP), Slack (future)

## Security Considerations

1. **RBAC**: Agent uses a dedicated ServiceAccount with minimal permissions
2. **Audit**: All actions logged to CloudWatch
3. **Approval**: Destructive actions require confirmation
4. **Secrets**: No hardcoded credentials, use IAM roles

## Example Interactions

```
User: "Why is my payment-service pod crashing?"

Agent:
1. get_pods(namespace="production", label="app=payment-service")
2. get_pod_logs(pod="payment-service-xyz", tail=100)
3. get_events(namespace="production", field_selector="involvedObject.name=payment-service-xyz")
4. analyze_pod_issues(pod="payment-service-xyz")

Response: "The payment-service pod is in CrashLoopBackOff. Looking at the logs,
I see an OOMKilled error - the container exceeded its memory limit of 512Mi.
The pod has restarted 5 times in the last 10 minutes.

Recommended actions:
1. Increase memory limit to 1Gi
2. Check for memory leaks in recent deployments
3. Review the application's memory usage patterns

Would you like me to increase the memory limit?"
```

## Files Structure

```
agentic-aiops-mvp/
├── src/
│   ├── __init__.py
│   ├── agent.py          # Main agent logic
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── kubernetes.py # kubectl wrappers
│   │   ├── aws.py        # AWS SDK tools
│   │   └── diagnostics.py# Analysis tools
│   ├── prompts/
│   │   └── system.py     # System prompts
│   └── cli.py            # CLI interface
├── docs/
│   └── ARCHITECTURE.md
├── tests/
│   └── test_tools.py
├── requirements.txt
└── README.md
```
