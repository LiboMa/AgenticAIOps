# AgenticAIOps - AI-Powered Kubernetes Operations

An intelligent AIOps agent for Amazon EKS clusters, powered by AWS Bedrock and Strands SDK.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    AgenticAIOps Architecture                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│  │   React     │     │  FastAPI    │     │   Strands   │       │
│  │  Dashboard  │────▶│   Backend   │────▶│    Agent    │       │
│  │  (Vite+MUI) │     │  (uvicorn)  │     │  (Bedrock)  │       │
│  └─────────────┘     └─────────────┘     └─────────────┘       │
│        :5173              :8000                 │               │
│                                                 │               │
│                                    ┌────────────┴────────────┐ │
│                                    │                         │ │
│                              ┌─────▼─────┐           ┌───────▼───────┐
│                              │  Intent   │           │   AWS MCP     │
│                              │ Classifier│           │   Server      │
│                              └───────────┘           │  (16 tools)   │
│                                    │                 └───────────────┘
│                              ┌─────▼─────┐                   │
│                              │Multi-Agent│           ┌───────▼───────┐
│                              │  Voting   │           │    kubectl    │
│                              └───────────┘           │   wrapper     │
│                                                      └───────────────┘
│                                                              │
│                                                      ┌───────▼───────┐
│                                                      │  Amazon EKS   │
│                                                      │   Cluster     │
│                                                      └───────────────┘
└─────────────────────────────────────────────────────────────────┘
```

## 📦 Modules

| Module | Description | Status |
|--------|-------------|--------|
| `src/intent_classifier.py` | Query intent classification (5 categories) | ✅ |
| `src/multi_agent_voting.py` | Multi-agent voting for reduced hallucination | ✅ |
| `src/kubectl_wrapper.py` | Fast kubectl subprocess wrapper with caching | ✅ |
| `mcp_agent.py` | Strands Agent with AWS MCP Server | ✅ |
| `api_server.py` | FastAPI backend for Dashboard | ✅ |
| `dashboard/` | React frontend (Vite + MUI) | ✅ |
| `eks-patterns/` | EKS troubleshooting patterns for GraphRAG | ✅ |

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- AWS CLI configured
- kubectl configured for EKS cluster
- AWS Bedrock access (Claude models)

### Installation

```bash
# Clone repository
git clone https://github.com/LiboMa/AgenticAIOps.git
cd AgenticAIOps

# Checkout MCP branch
git checkout agent-mcp

# Setup Python environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup React dashboard
cd dashboard
npm install
cd ..
```

### Running the Services

**1. Start Backend API**
```bash
source venv/bin/activate
python api_server.py
# Running on http://localhost:8000
```

**2. Start Dashboard**
```bash
cd dashboard
npm run dev -- --host 0.0.0.0
# Running on http://localhost:5173
```

**3. Access Dashboard**
Open browser: `http://localhost:5173`

## 📊 Features

### Dashboard Tabs

| Tab | Function |
|-----|----------|
| 💬 Chat | Conversational interface with AI agent |
| 📊 EKS Status | Real-time cluster, node, pod status |
| 🚨 Anomalies | Automated anomaly detection with AI suggestions |
| 📝 RCA Reports | Root cause analysis history and reports |

### Intent Categories

| Intent | Keywords | Recommended Tools |
|--------|----------|-------------------|
| `diagnose` | issue, error, crash, why | get_pods, get_events, get_pod_logs |
| `monitor` | status, health, check | get_cluster_health, get_pods, get_nodes |
| `scale` | scale, replica, increase | scale_deployment, get_hpa |
| `info` | what, list, show | get_cluster_info, get_pods |
| `recover` | restart, rollback, fix | scale_deployment |

### Supported Diagnoses

- OOM (Out of Memory)
- CrashLoopBackOff
- ImagePullBackOff
- Pending pods
- Network issues
- Configuration errors

## 📁 Project Structure

```
AgenticAIOps/
├── api_server.py           # FastAPI backend
├── mcp_agent.py            # Strands + MCP Agent
├── strands_agent.py        # Standalone Strands Agent
├── src/
│   ├── intent_classifier.py
│   ├── multi_agent_voting.py
│   ├── kubectl_wrapper.py
│   └── tools/
│       ├── kubernetes.py
│       └── aws.py
├── dashboard/              # React frontend
│   ├── src/
│   │   ├── App.jsx
│   │   └── components/
│   │       ├── ChatPanel.jsx
│   │       ├── EKSStatus.jsx
│   │       ├── Anomalies.jsx
│   │       └── RCAReports.jsx
│   └── package.json
├── eks-patterns/           # GraphRAG patterns
│   ├── troubleshooting/
│   │   ├── oom-killed.md
│   │   ├── crashloop-backoff.md
│   │   ├── image-pull-fail.md
│   │   └── pending-pods.md
│   └── best-practices/
│       └── resource-limits.md
├── samples/                # K8s sample workloads
└── docs/
    ├── TESTING.md
    └── ROADMAP.md
```

## 🔧 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/cluster/info` | GET | Cluster information |
| `/api/pods` | GET | List all pods |
| `/api/nodes` | GET | List all nodes |
| `/api/deployments` | GET | List deployments |
| `/api/events` | GET | Recent events |
| `/api/anomalies` | GET | Detected anomalies |
| `/api/chat` | POST | Chat with agent |
| `/api/rca/reports` | GET | RCA reports |

## 🛣️ Roadmap

- [x] Strands SDK integration
- [x] AWS MCP Server integration
- [x] Intent classification
- [x] Multi-agent voting
- [x] React Dashboard
- [x] Real-time anomaly detection
- [ ] GraphRAG Knowledge Base
- [ ] Bedrock Agents integration
- [ ] Auto-remediation actions
- [ ] ALB deployment

## 📄 License

MIT

## 🤝 Contributors

- Ma Ronnie (Project Lead)
- Worker1 (豆腐脑) - Development
- Worker2 - Research
- Myboat - Coordination
