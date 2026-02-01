# AgenticAIOps

AI-powered operations assistant for Amazon EKS using Strands SDK and Amazon Bedrock.

## Features

- 🤖 **Strands SDK** - Modern agentic AI framework with `@tool` decorators
- 🔧 **EKS Operations** - Cluster health, info, nodes, VPC configuration
- ☁️ **Amazon Bedrock** - Claude models via APAC inference profiles
- 🧪 **Tested** - 4/4 test scenarios passing

## Quick Start

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install strands-agents boto3

# Configure AWS credentials
aws configure

# Run tests
python3 test_strands.py

# Interactive mode
python3 strands_agent.py
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Strands Agent SDK                              │
│  ├── @tool decorators for EKS operations        │
│  ├── ReAct loop (built-in)                      │
│  └── Bedrock model integration                  │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Amazon Bedrock (APAC Claude 3 Haiku)           │
│  ├── Natural language understanding             │
│  └── Tool selection & response generation       │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  EKS Cluster (boto3 API)                        │
│  ├── Cluster health & info                      │
│  ├── Node groups & compute config               │
│  └── VPC & networking                           │
└─────────────────────────────────────────────────┘
```

## Available Tools

| Tool | Description |
|------|-------------|
| `get_cluster_health` | Check cluster health status |
| `get_cluster_info` | Get cluster version, endpoint, platform |
| `get_nodes` | View compute/node configuration |
| `get_vpc_config` | Check VPC and networking setup |
| `list_nodegroups` | List managed node groups |
| `get_addons` | List installed add-ons |

## Example Usage

```python
from strands import Agent, tool
from strands.models import BedrockModel

model = BedrockModel(
    model_id="apac.anthropic.claude-3-haiku-20240307-v1:0",
    region_name="ap-southeast-1"
)

agent = Agent(model=model, tools=[get_cluster_health, get_cluster_info])
response = agent("Check the health of my EKS cluster")
print(response)
```

## Sample Workloads

Deploy sample applications for testing:

```bash
kubectl apply -f samples/onlineshop.yaml
kubectl apply -f samples/bookstore.yaml
kubectl apply -f samples/faulty-workloads.yaml  # For testing diagnostics
```

## Roadmap

- [ ] Intent classification layer
- [ ] Multi-agent voting (reduce hallucinations)
- [ ] Operation sequence recommendations
- [ ] Knowledge graph integration
- [ ] AgentCore deployment

## License

MIT
