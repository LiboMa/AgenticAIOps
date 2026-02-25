# 设计方案: VPC 网络拓扑分析模块

**作者:** Architect  
**日期:** 2026-02-25  
**状态:** Draft → Review  
**参考:** `agenticops-chat/src/agenticops/graph/`  

---

## 背景

agenticops-chat 项目包含一个成熟的网络拓扑模块 (`graph/engine.py` + `algorithms.py`，约 950 行)，
基于 NetworkX 构建 VPC 有向图，支持可达性分析、影响半径评估、路径追踪和结构异常检测。

当前 agentic-aiops-mvp 完全缺少网络拓扑能力。RCA 分析时无法理解网络上下文，
例如 "这个子网是否能访问互联网" "修改这个 NAT 网关会影响哪些资源" 等问题无法回答。

---

## 目标

1. 在 `src/aci/topology/` 下引入网络拓扑模块，融入现有 ACI 体系
2. 从 AWS 实时数据构建 VPC 有向图 (NetworkX)
3. 支持 4 类拓扑查询：可达性、影响半径、路径分析、异常检测
4. 为 RCA 提供网络上下文增强
5. 为 WebUI 提供拓扑可视化数据 API

---

## 方案

### 方案 A: ACI 子模块 (推荐)

将 Topology 作为 ACI 的第四个子系统 (与 telemetry/operations/security 并列)。

```
src/aci/
├── topology/
│   ├── __init__.py        # 导出 TopologyProvider
│   ├── models.py          # Pydantic 数据模型 (~80 行)
│   ├── engine.py          # NetworkX 图引擎 (~300 行)
│   ├── algorithms.py      # 图算法 (可达性/影响/路径/异常) (~350 行)
│   └── collector.py       # AWS VPC 数据采集 (~200 行)
├── telemetry/
├── operations/
├── security/
└── interface.py           # 新增 topology 方法
```

**优点:**
- 融入现有 ACI 架构，Agent 通过统一接口访问
- collector 独立，可复用 aws_scanner.py 的 boto3 session
- 与 agenticops-chat 的 graph/ 设计高度对齐，迁移成本低

**缺点:**
- ACI 当前主要面向 K8s，VPC 拓扑是 AWS 层面的扩展

### 方案 B: 独立顶层模块

在 `src/topology/` 下独立存在，不归属 ACI。

```
src/
├── topology/
│   ├── __init__.py
│   ├── models.py
│   ├── engine.py
│   ├── algorithms.py
│   └── collector.py
```

**优点:**
- 独立性强，不依赖 ACI

**缺点:**
- 与现有架构割裂，Agent 需要单独导入
- 未来多个拓扑来源 (K8s + AWS) 需要再次整合

---

## 推荐: 方案 A (ACI 子模块)

理由：ACI 的定位是 "Agent-Cloud Interface"，VPC 拓扑正是 Cloud 的核心上下文。
ACI interface.py 已有 telemetry/operations/security 三个子系统，topology 是自然扩展。

---

## 详细设计

### 1. 数据模型 (`models.py`)

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Optional


class NodeType(str, Enum):
    VPC = "vpc"
    SUBNET = "subnet"
    INTERNET_GATEWAY = "igw"
    NAT_GATEWAY = "nat"
    ROUTE_TABLE = "rtb"
    SECURITY_GROUP = "sg"
    TRANSIT_GATEWAY = "tgw"
    VPC_PEERING = "pcx"
    VPC_ENDPOINT = "vpce"
    LOAD_BALANCER = "elb"
    EC2_INSTANCE = "ec2"


class NodeStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class EdgeType(str, Enum):
    CONTAINS = "contains"          # VPC -> Subnet
    ROUTES_TO = "routes_to"        # RouteTable -> target
    ATTACHED_TO = "attached_to"    # IGW/NAT -> VPC/Subnet
    PEERS_WITH = "peers_with"      # VPC <-> VPC
    REFERENCES = "references"      # SG -> SG
    HOSTED_IN = "hosted_in"        # NAT/Endpoint -> Subnet
    ASSOCIATED_WITH = "associated_with"  # Subnet -> RouteTable


class NodeAttrs(BaseModel):
    node_type: NodeType
    label: str = ""
    status: NodeStatus = NodeStatus.HEALTHY
    resource_type: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class EdgeAttrs(BaseModel):
    edge_type: EdgeType
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Algorithm Results ──

class ReachabilityResult(BaseModel):
    subnet_id: str
    can_reach_internet: bool
    path: list[str] = Field(default_factory=list)
    path_details: list[dict[str, str]] = Field(default_factory=list)
    blocking_reason: Optional[str] = None


class ImpactResult(BaseModel):
    failed_node_id: str
    failed_node_type: str = ""
    affected_nodes: list[dict[str, Any]] = Field(default_factory=list)
    lost_connections: list[dict[str, str]] = Field(default_factory=list)
    isolated_subnets: list[str] = Field(default_factory=list)
    severity: str = "low"  # low/medium/high/critical


class PathResult(BaseModel):
    source: str
    target: str
    paths_found: int = 0
    paths: list[list[str]] = Field(default_factory=list)
    path_details: list[list[dict[str, str]]] = Field(default_factory=list)


class TopologyAnomaly(BaseModel):
    type: str              # orphan_node, blackhole_route, routing_loop, unreachable_subnet
    severity: str          # low/medium/high/critical
    node_id: str
    node_type: str = ""
    description: str
    details: dict[str, Any] = Field(default_factory=dict)
```

### 2. 图引擎 (`engine.py`)

核心类 `InfraGraph`，从 AWS 拓扑数据构建 NetworkX 有向图：

```python
class InfraGraph:
    """NetworkX-backed infrastructure graph."""
    
    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
    
    def build_from_vpc_data(self, vpc_data: dict) -> "InfraGraph":
        """从 collector 采集的 VPC 数据构建图。
        
        映射规则:
        - VPC → 根节点
        - Subnet → CONTAINS edge from VPC
        - IGW → ATTACHED_TO edge to VPC
        - NAT → HOSTED_IN edge to Subnet
        - RouteTable → ASSOCIATED_WITH edge from Subnet
        - Route entries → ROUTES_TO edges
        - SG → REFERENCES edges (sg-to-sg)
        - TGW/Peering → PEERS_WITH edges
        """
        ...
    
    def build_from_region_data(self, region_data: dict) -> "InfraGraph":
        """从 region 级数据构建跨 VPC 图 (TGW + Peering)。"""
        ...
    
    def to_react_flow(self) -> dict:
        """导出 React Flow 格式 (nodes + edges) 供前端渲染。"""
        ...
    
    def to_dict(self) -> dict:
        """序列化为 JSON (用于 API 返回)。"""
        ...
```

### 3. 图算法 (`algorithms.py`)

4 类核心算法：

| 算法 | 方法 | 描述 | RCA 用途 |
|------|------|------|---------|
| **可达性** | `check_reachability(graph, subnet_id)` | 子网是否能到达 IGW | 诊断网络不通 |
| **影响半径** | `assess_impact(graph, node_id)` | 节点故障影响范围 | 评估修复风险 |
| **路径分析** | `find_path(graph, source, target)` | 两点间流量路径 | 定位路由断点 |
| **异常检测** | `detect_anomalies(graph)` | 孤立节点/黑洞路由/路由循环 | 主动发现隐患 |

### 4. 数据采集 (`collector.py`)

```python
class TopologyCollector:
    """从 AWS API 采集 VPC 拓扑数据。"""
    
    async def collect_vpc(self, vpc_id: str, region: str) -> dict:
        """采集单个 VPC 完整拓扑:
        - describe_vpcs
        - describe_subnets  
        - describe_internet_gateways
        - describe_nat_gateways
        - describe_route_tables
        - describe_security_groups
        - describe_vpc_endpoints
        - describe_transit_gateway_attachments
        - describe_vpc_peering_connections
        """
        ...
    
    async def collect_region(self, region: str) -> dict:
        """采集 region 级跨 VPC 拓扑 (TGW + Peering)。"""
        ...
```

### 5. ACI 集成

在 `interface.py` 新增 topology 方法：

```python
class AgentCloudInterface:
    def __init__(self, ...):
        ...
        self.topology = TopologyProvider(region=region)
    
    def get_vpc_topology(self, vpc_id: str) -> dict:
        """获取 VPC 拓扑图 + 异常检测结果。"""
        ...
    
    def check_subnet_reachability(self, subnet_id: str) -> ReachabilityResult:
        """检查子网互联网可达性。"""
        ...
    
    def assess_change_impact(self, node_id: str) -> ImpactResult:
        """评估变更影响半径。"""
        ...
```

### 6. API 端点

在 api_server.py (或未来拆分的 topology_router.py) 新增：

| Method | Path | 描述 |
|--------|------|------|
| GET | `/api/topology/vpc/{vpc_id}` | 获取 VPC 拓扑 |
| GET | `/api/topology/region/{region}` | 获取 region 级拓扑 |
| GET | `/api/topology/vpc/{vpc_id}/reachability/{subnet_id}` | 子网可达性 |
| GET | `/api/topology/vpc/{vpc_id}/impact/{node_id}` | 影响半径 |
| GET | `/api/topology/vpc/{vpc_id}/path` | 路径分析 (query: source, target) |
| GET | `/api/topology/vpc/{vpc_id}/anomalies` | 拓扑异常 |
| GET | `/api/topology/vpc/{vpc_id}/react-flow` | React Flow 渲染数据 |

### 7. RCA 集成

在 `rca_inference.py` 的分析 prompt 中注入网络上下文：

```python
# Before RCA analysis, if issue involves network:
if "network" in issue_type or "connectivity" in symptoms:
    topology = aci.get_vpc_topology(vpc_id)
    anomalies = topology.get("anomalies", [])
    reachability = aci.check_subnet_reachability(subnet_id)
    
    context += f"\n## Network Topology Context\n"
    context += f"Anomalies: {anomalies}\n"
    context += f"Reachability: {reachability}\n"
```

---

## 从 agenticops-chat 的借鉴与差异

| 维度 | agenticops-chat | 我们的设计 | 差异原因 |
|------|----------------|-----------|---------|
| 位置 | 独立 `graph/` 包 | `src/aci/topology/` | 融入 ACI 体系 |
| 数据源 | Strands tool 输入 | 独立 collector + boto3 | 我们需要自采集 |
| 图算法 | 4 类 (相同) | 4 类 (相同) | 核心算法直接复用 |
| 序列化 | 自定义 JSON | Pydantic + React Flow | 更规范 |
| 与 RCA 集成 | Agent 手动调用 | 自动注入 prompt | 更自动化 |

---

## 实施计划

| 阶段 | 任务 | 负责人 | 预估 |
|------|------|--------|------|
| **Day 1** | models.py + engine.py + collector.py | Developer | 1 天 |
| **Day 1** | 单测计划 + collector mock | Tester | 0.5 天 |
| **Day 2** | algorithms.py + ACI interface 集成 | Developer | 1 天 |
| **Day 2** | algorithms 单测 (4 类算法) | Tester | 0.5 天 |
| **Day 2** | 代码 Review | Reviewer | 0.5 天 |
| **Day 3** | API 端点 + React Flow 导出 | Developer | 0.5 天 |
| **Day 3** | RCA 上下文注入 + 集成测试 | Developer + Tester | 0.5 天 |
| **Day 3** | 架构 Review + 文档更新 | Architect | 0.5 天 |

**预计总工时:** 3 天并行
**预计新增代码:** ~930 行 Python + ~150 行测试
**依赖:** `networkx>=3.0` (需加入 requirements.txt)

---

## 风险 & 缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| AWS API 限流 (多个 describe 调用) | 中 | 采集慢 | collector 并发 + 缓存 |
| NetworkX 内存 (大 VPC 1000+ 资源) | 低 | OOM | 限制单 VPC 最大节点数 |
| 与现有 aws_scanner.py 重复 | 中 | 代码冗余 | collector 复用 scanner 的 session |

---

## 验收标准

- [ ] `src/aci/topology/` 4 个文件 + `__init__.py`
- [ ] 4 类图算法单测覆盖 ≥80%
- [ ] 7 个 API 端点可用
- [ ] RCA 可自动获取网络上下文
- [ ] React Flow 格式导出可用
- [ ] 回归测试 888+ passed, 0 failed
- [ ] networkx 在 requirements.txt
