# AgenticAIOps - AI-Powered Multi-Service Operations

An intelligent AIOps agent for Amazon EKS, EC2, Lambda, and HPC, powered by AWS Bedrock and Strands SDK.

**基于 AIOpsLab 和 mABC 论文实现**

---

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
│                    ┌────────────────────────────┴───────┐      │
│                    │          ACI (Agent-Cloud Interface) ◀────┼──── NEW!
│                    │  ┌─────────────────────────────────┐│      │
│                    │  │ get_logs | get_metrics | kubectl ││     │
│                    │  └─────────────────────────────────┘│      │
│                    └───────────────────────────────────────┘    │
│                                    │                           │
│                    ┌───────────────┴───────────────┐          │
│                    │      Plugin System             │          │
│                    │  ┌─────┐ ┌─────┐ ┌──────┐ ┌─────┐ │      │
│                    │  │ EKS │ │ EC2 │ │Lambda│ │ HPC │ │      │
│                    │  │  ☸️ │ │ 🖥️ │ │  λ   │ │ 🖧  │ │      │
│                    │  └─────┘ └─────┘ └──────┘ └─────┘ │      │
│                    └───────────────────────────────────┘      │
│                                    │                           │
│                    ┌───────────────┴───────────────┐          │
│                    │      Multi-Agent Voting (mABC) ◀──────────┼──── NEW!
│                    │        (加权投票 + 共识检测)    │          │
│                    └───────────────────────────────┘          │
│                                    │                           │
│                    ┌───────────────┴───────────────┐          │
│                    │     EKS MCP Server (16 tools) │          │
│                    │      + Prometheus + Grafana   │          │
│                    └───────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Development Progress

### ✅ Completed Phases

| Phase | Description | Status | Date |
|-------|-------------|--------|------|
| **Phase 1** | Plugin System | ✅ 完成 | 2026-02-01 |
| **Phase 2** | Manifest/Schema | ✅ 完成 | 2026-02-01 |
| **Phase 3** | ACI + Multi-Agent Voting | ✅ 完成 | 2026-02-02 |
| **Phase 4** | 实际场景集成 | ✅ 完成 | 2026-02-02 |

### 📝 Design Documents

| Document | Description |
|----------|-------------|
| [ACI_DESIGN.md](docs/designs/ACI_DESIGN.md) | Agent-Cloud Interface 设计 |
| [VOTING_DESIGN.md](docs/designs/VOTING_DESIGN.md) | Multi-Agent Voting 机制 (mABC) |
| [PHASE4_SCENARIOS.md](docs/designs/PHASE4_SCENARIOS.md) | 故障注入场景设计 |
| [FRONTEND_API_DESIGN.md](docs/designs/FRONTEND_API_DESIGN.md) | 前端 API 接口设计 |
| [MULTI_CLUSTER_DESIGN.md](docs/designs/MULTI_CLUSTER_DESIGN.md) | 多集群架构设计 (Phase 5) |

---

## 🆕 New Features (Phase 3-4)

### Agent-Cloud Interface (ACI)

基于 **AIOpsLab 论文** 实现的统一 Agent-云环境接口。

```python
from src.aci import AgentCloudInterface

aci = AgentCloudInterface()

# 获取 Pod 日志
logs = aci.get_logs(namespace="default", severity="error")

# 获取 Prometheus 指标
metrics = aci.get_metrics(namespace="default", metric_type="cpu")

# 获取 K8s 事件
events = aci.get_events(namespace="default", type="Warning")

# 安全执行 kubectl
result = aci.kubectl(["get", "pods", "-n", "default"])
```

### Multi-Agent Voting (mABC)

基于 **mABC 论文** 实现的区块链启发加权投票机制。

```python
from src.voting import MultiAgentVoting, TaskType

voting = MultiAgentVoting()

result = voting.vote(
    task_type=TaskType.ANALYSIS,
    query="Pod 为什么崩溃？",
    agent_responses={
        "architect": "内存溢出导致 OOM",
        "developer": "应用内存泄漏",
        "tester": "复现了 OOM 问题"
    }
)

print(result.final_answer)  # "oom"
print(result.consensus)     # True
print(result.confidence)    # 0.95
```

### Fault Injection Scripts

```bash
# 注入 OOM 故障
python scripts/fault_injection/inject_oom.py -n stress-test

# 运行 Multi-Agent 诊断
python scripts/diagnosis/run_diagnosis.py -n stress-test

# 清理
python scripts/fault_injection/inject_oom.py --cleanup
```

---

## 🔌 Plugin System

| Plugin | Icon | Description |
|--------|------|-------------|
| EKS | ☸️ | Multi-cluster Kubernetes management |
| EC2 | 🖥️ | Instance monitoring and metrics |
| Lambda | λ | Serverless function management |
| HPC | 🖧 | ParallelCluster/Slurm integration |

---

## 📦 Modules

| Module | Description | Status |
|--------|-------------|--------|
| `src/aci/` | Agent-Cloud Interface | ✅ NEW |
| `src/voting.py` | Multi-Agent Voting (mABC) | ✅ NEW |
| `src/plugins/` | Plugin system (EKS, EC2, Lambda, HPC) | ✅ |
| `src/tools/` | Prometheus + K8s tools | ✅ |
| `src/intent_classifier.py` | Query intent classification | ✅ |
| `scripts/fault_injection/` | 故障注入脚本 | ✅ NEW |
| `scripts/diagnosis/` | 诊断运行器 | ✅ NEW |
| `mcp_agent.py` | Strands Agent with AWS MCP Server | ✅ |
| `api_server.py` | FastAPI backend (+ ACI endpoints) | ✅ |
| `dashboard/` | React frontend (+ ACI Telemetry Tab) | ✅ |

---

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
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

**2. Start Frontend Dashboard**
```bash
cd dashboard
npm run dev
# Running on http://localhost:5173
```

**3. Access Grafana (Monitoring)**
```bash
kubectl port-forward svc/prometheus-grafana 3000:80 -n default
# URL: http://localhost:3000
# User: admin
# Password: 6z752r5CxAKYdV5ef293bT7WvNIwFybQDKv2Uflt
```

---

## 🧪 Testing

```bash
# 运行全量测试
pytest tests/ -v

# 当前测试覆盖
# 99 passed, 2 skipped
```

| Test File | Tests | Status |
|-----------|-------|--------|
| test_aci.py | 14 | ✅ |
| test_voting.py | 19 | ✅ |
| test_plugins.py | 14 | ✅ |
| test_mcp_integration.py | 14 | ✅ |
| test_prometheus_integration.py | 14 | ✅ |
| test_phase4_integration.py | 23 | ✅ |

---

## 📚 References

- [AIOpsLab: A Holistic Framework for AIOps](https://arxiv.org/abs/2501.06706) - Microsoft Research
- [mABC: Multi-Agent Blockchain-Inspired Collaboration](https://arxiv.org/abs/2404.12135)
- [AWS EKS MCP Server](https://awslabs.github.io/mcp/)

---

## 👥 Team (Agentic SDLC)

| Role | Agent |
|------|-------|
| 🎯 Orchestrator | cloud-mbot-worker-1 |
| 📐 Architect | cloud-mbot-architect |
| 💻 Developer | cloud-mbot-developer |
| 🧪 Tester | cloud-mbot-tester |
| 🔍 Reviewer | cloud-mbot-researcher-1 |

---

**Last Updated**: 2026-02-02  
**Branch**: agent-mcp
