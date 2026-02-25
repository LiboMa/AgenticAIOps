# 设计方案: Topology Module — ACI 第四子系统

> **Author**: Architect  
> **Date**: 2026-02-25  
> **Status**: Draft → Pending Review  
> **Sprint**: agenticops-chat 整合 Sprint Day 1  

---

## 1. 背景

`agenticops-chat` 仓库包含一个成熟的 `graph/` 模块 (1,636 行)，基于 NetworkX 实现 VPC 拓扑图构建、算法分析和 ReactFlow 可视化。我们的 `src/aci/interface.py` 有两个 TODO 方法 (`get_topology`, `get_dependencies`) 一直未实现。

**目标**: 将 `agenticops-chat/src/agenticops/graph/` 适配搬入 `src/aci/topology/`，作为 ACI 的第四个子系统 (alongside telemetry, operations, security)。

### 源码清单 (agenticops-chat)

| 文件 | 行数 | 职责 |
|------|------|------|
| `types.py` | 95 | Pydantic 数据模型 (NodeType, EdgeType, GraphNode, etc.) |
| `engine.py` | 440 | InfraGraph — NetworkX DiGraph 构建器 |
| `algorithms.py` | 509 | 4 类算法: 可达性/影响分析/路径/异常检测 + 分段 |
| `serializers.py` | 243 | ReactFlow JSON 导出 + Agent 文本摘要 |
| `api.py` | 152 | FastAPI Router (7 端点) |
| `tools.py` | 170 | Strands Agent tools (5 个) |
| **合计** | **1,636** | |

---

## 2. 目标

1. **P0**: 搬入 graph engine + algorithms + types，适配 import 路径
2. **P0**: 新建 `collector.py` 替代 `network_tools.py` 依赖
3. **P1**: 对接 `interface.py` TODO，让 ACI tools 能用 topology
4. **P1**: 注册 FastAPI Router (`/api/topology/*`)
5. **P2**: RCA 上下文注入 — topology 异常自动送入 incident_orchestrator
6. **P2**: Strands Agent tools 集成 (等 Issue 状态机设计后)

---

## 3. 架构设计

### 3.1 目录结构

```
src/aci/topology/
├── __init__.py          # 公开 API: InfraGraph, collect_*, algorithms
├── types.py             # Pydantic models (从 agenticops 直接搬入，改 import)
├── engine.py            # InfraGraph (从 agenticops 搬入，改 import)
├── algorithms.py        # 4+1 算法 (从 agenticops 搬入，改 import)
├── serializers.py       # ReactFlow + Agent summary (从 agenticops 搬入)
├── collector.py          # 🆕 替代 network_tools.py，用 boto3 直调
├── api.py               # FastAPI Router /api/topology/* (从 agenticops 适配)
└── tools.py             # Strands Agent tools (搬入，暂不注册)
```

### 3.2 模块依赖图

```
collector.py ──→ boto3 (VPC describe-* APIs)
     │
     ▼
engine.py ──→ types.py ──→ pydantic
     │
     ├──→ algorithms.py ──→ networkx
     │
     └──→ serializers.py ──→ types.py
              │
              ▼
         api.py ──→ FastAPI Router
              │
              ▼
    interface.py ──→ ACI Agent tools
```

### 3.3 与现有模块的集成点

| 集成点 | 方向 | 说明 |
|--------|------|------|
| `aci/interface.py` | topology → ACI | `get_topology()` / `get_dependencies()` 委托 engine |
| `incident_orchestrator.py` | topology → RCA | 异常检测结果注入 RCA context (P2) |
| `api_server.py` (或 `routers/`) | topology → API | `include_router(topology_router)` |
| `aws_scanner.py` | collector ← AWS | collector 复用 scanner 的 boto3 session |
| ReactFlow 前端 | serializers → UI | `SerializedGraph` JSON 直接喂给 React Flow |

---

## 4. 详细设计

### 4.1 collector.py (新建 ~150 行)

替代 `agenticops.tools.network_tools`，用 boto3 直调 AWS VPC APIs。

```python
"""Topology data collector — fetches VPC/region topology via boto3."""

import boto3
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 默认 region，和 api_server.py 的 _current_region 保持一致
_DEFAULT_REGION = "ap-southeast-1"


def _get_ec2_client(region: str = None):
    """Get boto3 EC2 client, 复用全局 session。"""
    return boto3.client("ec2", region_name=region or _DEFAULT_REGION)


def collect_vpc_topology(region: str, vpc_id: str) -> dict[str, Any]:
    """采集单 VPC 拓扑数据。
    
    输出 schema 对齐 agenticops 的 analyze_vpc_topology() 格式：
    {
        "vpc_id": "vpc-xxx",
        "vpc_cidr": "10.0.0.0/16",
        "igws": [...],
        "subnets": [...],
        "route_tables": [...],
        "nat_gateways": [...],
        "transit_gateway_attachments": [...],
        "peering_connections": [...],
        "vpc_endpoints": [...],
        "security_groups": [...]
    }
    """
    ec2 = _get_ec2_client(region)
    
    # VPC info
    vpc_resp = ec2.describe_vpcs(VpcIds=[vpc_id])
    vpc = vpc_resp["Vpcs"][0] if vpc_resp["Vpcs"] else {}
    
    topo = {
        "vpc_id": vpc_id,
        "vpc_cidr": vpc.get("CidrBlock", ""),
        "igws": _collect_igws(ec2, vpc_id),
        "subnets": _collect_subnets(ec2, vpc_id),
        "route_tables": _collect_route_tables(ec2, vpc_id),
        "nat_gateways": _collect_nat_gateways(ec2, vpc_id),
        "transit_gateway_attachments": _collect_tgw_attachments(ec2, vpc_id),
        "peering_connections": _collect_peering(ec2, vpc_id),
        "vpc_endpoints": _collect_endpoints(ec2, vpc_id),
        "security_groups": _collect_security_groups(ec2, vpc_id),
    }
    return topo


def collect_region_topology(region: str) -> dict[str, Any]:
    """采集整个 region 的多 VPC 拓扑。
    
    输出 schema 对齐 agenticops 的 describe_region_topology() 格式：
    {
        "region": "ap-southeast-1",
        "vpcs": [...],
        "transit_gateways": [...],
        "peering_connections": [...]
    }
    """
    ec2 = _get_ec2_client(region)
    # ... describe_vpcs + describe_transit_gateways + describe_vpc_peering_connections
    pass


# --- 内部采集函数 ---

def _collect_igws(ec2, vpc_id) -> list[dict]:
    """采集 Internet Gateways。"""
    resp = ec2.describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
    )
    return resp.get("InternetGateways", [])


def _collect_subnets(ec2, vpc_id) -> list[dict]:
    """采集子网。"""
    resp = ec2.describe_subnets(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )
    subnets = resp.get("Subnets", [])
    # 标注 public/private (MapPublicIpOnLaunch)
    for s in subnets:
        s["_type"] = "public" if s.get("MapPublicIpOnLaunch") else "private"
    return subnets


def _collect_route_tables(ec2, vpc_id) -> list[dict]:
    resp = ec2.describe_route_tables(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )
    return resp.get("RouteTables", [])


def _collect_nat_gateways(ec2, vpc_id) -> list[dict]:
    resp = ec2.describe_nat_gateways(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )
    return resp.get("NatGateways", [])


def _collect_tgw_attachments(ec2, vpc_id) -> list[dict]:
    try:
        resp = ec2.describe_transit_gateway_attachments(
            Filters=[{"Name": "resource-id", "Values": [vpc_id]}]
        )
        return resp.get("TransitGatewayAttachments", [])
    except Exception:
        return []


def _collect_peering(ec2, vpc_id) -> list[dict]:
    resp = ec2.describe_vpc_peering_connections(
        Filters=[{"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]}]
    )
    # Also check accepter side
    resp2 = ec2.describe_vpc_peering_connections(
        Filters=[{"Name": "accepter-vpc-info.vpc-id", "Values": [vpc_id]}]
    )
    seen = set()
    result = []
    for pcx in resp.get("VpcPeeringConnections", []) + resp2.get("VpcPeeringConnections", []):
        pcx_id = pcx.get("VpcPeeringConnectionId", "")
        if pcx_id not in seen:
            seen.add(pcx_id)
            result.append(pcx)
    return result


def _collect_endpoints(ec2, vpc_id) -> list[dict]:
    resp = ec2.describe_vpc_endpoints(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )
    return resp.get("VpcEndpoints", [])


def _collect_security_groups(ec2, vpc_id) -> list[dict]:
    resp = ec2.describe_security_groups(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )
    return resp.get("SecurityGroups", [])
```

**关键适配**: `engine.py` 的 `build_from_vpc_topology()` 期望特定 JSON schema。`collector.py` 的输出必须精确对齐这个 schema。差异主要在字段名映射 (AWS API 的 PascalCase → agenticops 的 snake_case)。

### 4.2 engine.py 适配 (搬入 ~440 行)

**types.py 新增 Topology Schema Models** (Reviewer 建议):

```python
class VpcTopology(BaseModel):
    """collector.py 输出 → engine.py 输入的 schema 契约。"""
    vpc_id: str
    vpc_cidr: str
    vpc_name: str = ""
    region: str = ""
    internet_gateways: list[dict[str, Any]] = Field(default_factory=list)
    subnets: list[dict[str, Any]] = Field(default_factory=list)
    route_tables: list[dict[str, Any]] = Field(default_factory=list)
    nat_gateways: list[dict[str, Any]] = Field(default_factory=list)
    transit_gateway_attachments: list[dict[str, Any]] = Field(default_factory=list)
    vpc_peering_connections: list[dict[str, Any]] = Field(default_factory=list)
    vpc_endpoints: list[dict[str, Any]] = Field(default_factory=list)
    security_group_dependency_map: dict[str, dict[str, Any]] = Field(default_factory=dict)
    blackhole_routes: list[dict[str, Any]] = Field(default_factory=list)

class RegionTopology(BaseModel):
    """Region 级拓扑 schema。"""
    region: str
    vpcs: list[dict[str, Any]] = Field(default_factory=list)
    transit_gateways: list[dict[str, Any]] = Field(default_factory=list)
    peering_connections: list[dict[str, Any]] = Field(default_factory=list)
```

collector 返回 `VpcTopology` / `RegionTopology`，engine 消费 `.model_dump()`。

**engine.py 改动量极小** — 仅改 import 路径：

```diff
- from agenticops.graph.types import (
+ from src.aci.topology.types import (
      EdgeAttrs, EdgeType, NodeAttrs, NodeStatus, NodeType,
  )
```

`build_from_vpc_topology()` 内部消费的 topo dict schema 不动。`collector.py` 负责对齐输出格式。

### 4.3 algorithms.py 适配 (搬入 ~509 行)

同样仅改 import：

```diff
- from agenticops.graph.engine import InfraGraph
- from agenticops.graph.types import EdgeType, NodeStatus, NodeType
+ from src.aci.topology.engine import InfraGraph
+ from src.aci.topology.types import EdgeType, NodeStatus, NodeType
```

5 个算法函数 + 6 个 Result models 全部保留：
- `can_reach_internet()` → 子网到 IGW 可达性
- `impact_analysis()` → 故障爆炸半径
- `find_traffic_path()` → 路径追踪
- `detect_anomalies()` → 结构异常检测 (orphan/blackhole/cycle/unreachable)
- `network_segments()` → 网络分段分析

### 4.4 api.py 适配 (搬入 ~152 行)

**三处改动**：

1. **prefix**: `/api/graph/` → `/api/topology/`
2. **graph 构建**: 删除 `_ensure_aws_session()`，改用 `collector.py`
3. **import 路径**: 全部改为 `src.aci.topology.*`

```python
router = APIRouter(prefix="/api/topology", tags=["topology"])

def _build_vpc_graph(region: str, vpc_id: str) -> InfraGraph:
    from src.aci.topology.collector import collect_vpc_topology
    topo = collect_vpc_topology(region, vpc_id)
    return InfraGraph().build_from_vpc_topology(topo)

def _build_region_graph(region: str) -> InfraGraph:
    from src.aci.topology.collector import collect_region_topology
    topo = collect_region_topology(region)
    return InfraGraph().build_from_region_topology(topo)
```

### 4.5 API 端点清单

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/topology/vpc/{vpc_id}` | 单 VPC ReactFlow 图 |
| GET | `/api/topology/region` | Region 多 VPC 图 |
| GET | `/api/topology/vpc/{vpc_id}/reachability/{subnet_id}` | 子网可达性 |
| GET | `/api/topology/vpc/{vpc_id}/impact/{resource_id}` | 故障爆炸半径 |
| GET | `/api/topology/vpc/{vpc_id}/path?source=&target=` | 路径追踪 |
| GET | `/api/topology/vpc/{vpc_id}/anomalies` | 结构异常检测 |
| GET | `/api/topology/region/segments` | 网络分段分析 (新增) |

### 4.6 interface.py 对接

> **⚠️ 重要**: `get_topology()` 和 `get_dependencies()` 已有 K8s 实现 (通过 kubectl + `build_from_k8s_topology`)。
> **不替换**, 而是新增 VPC 拓扑方法。两种拓扑能力并存。

| 方法 | 层级 | 数据源 | 状态 |
|------|------|--------|------|
| `get_topology(namespace)` | K8s 应用层 | kubectl | ✅ 已实现 |
| `get_dependencies(service)` | K8s 应用层 | kubectl | ✅ 已实现 |
| `get_vpc_topology(region, vpc_id)` | VPC 网络层 | boto3 | 🆕 新增 |
| `get_network_dependencies(resource_id)` | VPC 网络层 | boto3 | 🆕 新增 |

```python
# src/aci/interface.py — 新增 VPC 拓扑方法 (保留 K8s 方法不动)

def get_vpc_topology(self, region: str = None, vpc_id: str = None) -> ContextResult:
    """VPC 网络拓扑发现。"""
    try:
        from .topology.collector import collect_vpc_topology, collect_region_topology
        from .topology.engine import InfraGraph
        from .topology.serializers import to_agent_summary
        
        region = region or self.region
        if vpc_id:
            topo = collect_vpc_topology(region, vpc_id)
            graph = InfraGraph().build_from_vpc_topology(topo)
        else:
            topo = collect_region_topology(region)
            graph = InfraGraph().build_from_region_topology(topo)
        
        summary = to_agent_summary(graph)
        
        return ContextResult(
            status=ResultStatus.SUCCESS,
            data={
                "graph_summary": summary,
                "node_count": graph.graph.number_of_nodes(),
                "edge_count": graph.graph.number_of_edges(),
                "region": region,
                "vpc_id": vpc_id,
            },
        )
    except Exception as e:
        return ContextResult(status=ResultStatus.ERROR, data={"error": str(e)})

def get_network_dependencies(self, resource_id: str, region: str = None, vpc_id: str = None) -> ContextResult:
    """VPC 资源网络依赖分析。"""
    try:
        from .topology.collector import collect_vpc_topology
        from .topology.engine import InfraGraph
        
        region = region or self.region
        if not vpc_id:
            return ContextResult(status=ResultStatus.ERROR, data={"error": "vpc_id required"})
        
        topo = collect_vpc_topology(region, vpc_id)
        graph = InfraGraph().build_from_vpc_topology(topo)
        neighbors = graph.get_neighbors(resource_id, direction="both")
        
        return ContextResult(
            status=ResultStatus.SUCCESS,
            data={
                "resource_id": resource_id,
                "dependencies": neighbors,
                "vpc_id": vpc_id,
            },
        )
    except Exception as e:
        return ContextResult(status=ResultStatus.ERROR, data={"error": str(e)})
```

### 4.7 RCA 上下文注入 (P2)

```python
# src/incident_orchestrator.py — Stage 0.5 (P2, 未来 sprint)

async def _enrich_with_topology(detect_result: DetectResult) -> dict:
    """在 RCA 之前，用 topology 异常信息丰富上下文。"""
    from src.aci.topology.collector import collect_vpc_topology
    from src.aci.topology.engine import InfraGraph
    from src.aci.topology.algorithms import detect_anomalies, impact_analysis
    
    # 从 detect_result 中提取 VPC 信息
    vpc_id = detect_result.metadata.get("vpc_id")
    if not vpc_id:
        return {}
    
    topo = collect_vpc_topology(detect_result.region, vpc_id)
    graph = InfraGraph().build_from_vpc_topology(topo)
    anomalies = detect_anomalies(graph)
    
    return {
        "topology_anomalies": anomalies.model_dump(),
        "graph_node_count": graph.graph.number_of_nodes(),
    }
```

---

## 5. collector.py 数据格式映射 (Golden Contract)

> **来源**: `agenticops-chat/tests/test_graph_algorithms.py` 的 `_make_vpc_topology()` fixture
> 是 engine.py 消费的精确 schema。collector.py 的输出必须 100% 匹配此格式。

### 5.1 VPC Topology Schema (`build_from_vpc_topology`)

```python
{
    "vpc_id": "vpc-xxx",
    "vpc_cidr": "10.0.0.0/16",
    "vpc_name": "my-vpc",             # optional, fallback to vpc_id
    "region": "ap-southeast-1",
    
    "internet_gateways": [             # ⚠️ 不是 "igws"
        {"igw_id": "igw-xxx", "name": "...", "attachments": [{"state": "attached"}]}
    ],
    
    "subnets": [
        {
            "subnet_id": "subnet-xxx",
            "name": "public-subnet-1",
            "az": "ap-southeast-1a",
            "cidr": "10.0.1.0/24",     # ⚠️ 不是 "cidr_block"
            "type": "public",           # "public" | "private"
            "available_ips": 250,
            "route_table_id": "rtb-xxx",
            "default_route_target": "igw-xxx"
        }
    ],
    
    "route_tables": [
        {
            "route_table_id": "rtb-xxx",
            "name": "...",
            "associated_subnets": ["subnet-xxx"],   # ⚠️ 不是 "associations"
            "routes": [
                {"destination": "0.0.0.0/0", "target": "igw-xxx", "state": "active"},
                {"destination": "10.0.0.0/16", "target": "local", "state": "active"}
            ]
        }
    ],
    
    "nat_gateways": [
        {"nat_id": "nat-xxx", "name": "...", "state": "available", "subnet_id": "subnet-pub-1"}
    ],
    
    "transit_gateway_attachments": [
        {
            "attachment_id": "tgw-att-xxx",
            "transit_gateway_id": "tgw-xxx",
            "state": "available"
        }
    ],
    
    "vpc_peering_connections": [       # ⚠️ 不是 "peering_connections"
        {
            "pcx_id": "pcx-xxx",
            "requester_vpc": "vpc-001",
            "accepter_vpc": "vpc-002",
            "status": "active"
        }
    ],
    
    "vpc_endpoints": [
        {
            "vpce_id": "vpce-xxx",
            "service_name": "com.amazonaws.s3",
            "type": "Gateway",
            "subnet_ids": ["subnet-xxx"],
            "status": "available"
        }
    ],
    
    "security_group_dependency_map": {  # ⚠️ 不是 "security_groups" list
        "sg-xxx": {
            "name": "web-sg",
            "references": ["sg-yyy"]
        }
    },
    
    "blackhole_routes": [              # optional, supplementary
        {"route_table_id": "rtb-xxx", "destination": "...", "target": "...", "affected_subnets": ["subnet-xxx"]}
    ]
}
```

### 5.2 Region Topology Schema (`build_from_region_topology`)

```python
{
    "region": "ap-southeast-1",
    "vpcs": [
        {"vpc_id": "vpc-xxx", "cidr_block": "...", "is_default": false, "state": "available", "subnet_count": 4}
    ],
    "transit_gateways": [
        {"transit_gateway_id": "tgw-xxx", "state": "available", "attachments": [...]}
    ],
    "peering_connections": [
        {"pcx_id": "pcx-xxx", "requester_vpc": "vpc-001", "accepter_vpc": "vpc-002", "status": "active"}
    ]
}
```

### 5.3 boto3 → Schema 转换要点

| boto3 PascalCase | Schema snake_case | 注意 |
|------------------|-------------------|------|
| `InternetGateways[].InternetGatewayId` | `igw_id` | |
| `Subnets[].SubnetId` | `subnet_id` | |
| `Subnets[].CidrBlock` | `cidr` | **不是** `cidr_block` |
| `Subnets[].MapPublicIpOnLaunch` | `type: "public"/"private"` | 需判断转换 |
| `RouteTables[].RouteTableId` | `route_table_id` | |
| `RouteTables[].Associations[].SubnetId` | `associated_subnets: [...]` | 需聚合为 list |
| `RouteTables[].Routes[].DestinationCidrBlock` | `routes[].destination` | |
| `RouteTables[].Routes[].GatewayId\|NatGatewayId` | `routes[].target` | 需合并多字段 |
| `RouteTables[].Routes[].State` | `routes[].state` | |
| `NatGateways[].NatGatewayId` | `nat_gateway_id` | engine L161 确认 |
| `SecurityGroups` | `security_group_dependency_map` | 需重构为 map + references |

**collector.py 是纯转换层** — engine.py 零改动。

---

## 6. 依赖

| 包 | 版本 | 说明 |
|----|------|------|
| `networkx` | >=3.0 | Graph 引擎核心 |
| `pydantic` | >=2.0 | 已有依赖 |
| `boto3` | >=1.26 | 已有依赖 |

```bash
# requirements.txt 新增
networkx>=3.0
```

---

## 7. 实施计划

| 阶段 | 负责人 | 任务 | 预估 |
|------|--------|------|------|
| 1 | Developer | 搬入 types.py + engine.py + algorithms.py + serializers.py，改 import | 30 min |
| 2 | Developer | 新建 collector.py (PascalCase→snake_case 转换) | 2 hr |
| 3 | Developer | 搬入 api.py，改 prefix + 接 collector | 30 min |
| 4 | Tester | 单测: engine (graph 构建) + algorithms (5 算法) | 2 hr |
| 5 | Developer | 对接 interface.py TODO | 30 min |
| 6 | Tester | 集成测试: API 端点 + ACI 调用 | 1 hr |
| **Total** | | | **~7 hr (并行 3 天内)** |

**预估代码量**: ~930 行搬入 + ~150 行新 collector = ~1,080 行  
**预估测试**: ~150 行 (engine 7 cases + algorithms 12 cases + collector 5 cases + API 4 cases)

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| collector.py schema 不对齐 engine | engine 解析失败 | 写 schema 对比测试，用 agenticops 的 mock data 做 golden test |
| boto3 VPC API throttling | 采集慢 | 加 cache (5min TTL)，复用 DetectAgent 的缓存模式 |
| networkx import 增加启动时间 | API 启动变慢 | lazy import (仅在 topology 端点被调用时 import) |
| engine.py 内部 dict key 不完全已知 | 运行时 KeyError | 阶段 1 后立即跑 agenticops 的原始测试确认 |

---

## 9. 验收标准

- [ ] `src/aci/topology/` 目录包含 7 个 .py 文件
- [ ] `pytest tests/ -k topology` — 全部通过
- [ ] `GET /api/topology/vpc/{vpc_id}` 返回 SerializedGraph JSON
- [ ] `interface.py` 的 `get_topology()` 返回 SUCCESS
- [ ] 全量回归 888+ tests, 0 failed
- [ ] `networkx` 在 requirements.txt 中

---

## 10. 开放问题

1. **collector.py cache**: 是否复用 DetectAgent 的 `DetectResult` 缓存模式？还是 topology 自己管 TTL？
   - **建议**: 独立 LRU cache，5min TTL，因为 topology 变化频率低于 telemetry
   
2. **前端集成**: ReactFlow 组件是否在这个 sprint 搬入？
   - **建议**: 不在此 sprint，先只出 API JSON，前端留 P2

3. **`network_segments` 端点**: agenticops 的 `api.py` 没暴露这个算法，是否新增？
   - **建议**: 新增 `GET /api/topology/region/segments`，有现成算法直接用
