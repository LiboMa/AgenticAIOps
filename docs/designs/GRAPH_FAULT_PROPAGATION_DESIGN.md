# Graph Fault Propagation & Topology Delta Design

**Author**: Architect  
**Date**: 2026-02-26  
**Status**: PROPOSED  
**Sprint**: agenticops-chat Integration Phase 2

---

## 1. Background

The current Graph module (`src/aci/topology/`) models infrastructure topology as a static NetworkX DiGraph with 5 basic algorithms (reachability, impact, path, anomaly detection, segmentation). Two critical gaps prevent it from being an effective SRE diagnostic tool:

1. **No fault propagation model** — `impact_analysis()` uses simple BFS, treating all edges equally. A NAT Gateway failure and an optional cache failure are scored the same.
2. **No temporal awareness** — Each `build_from_*` call creates a full snapshot. No way to answer "what changed?" or "when did this route become a blackhole?"

This design addresses both gaps and defines the alarm→topology→RCA integration pipeline.

---

## 2. Fault Propagation Engine

### 2.1 Dual-Mode API

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

class PropagationMode(str, Enum):
    PESSIMISTIC = "pessimistic"   # Assume all paths propagate (blast radius)
    REALISTIC = "realistic"       # Account for redundancy/degradation

@dataclass
class PropagationEdge:
    """Propagation metadata for a single edge."""
    source: str
    target: str
    weight: float              # 0.0 = fully isolated, 1.0 = fully propagates
    reason: str                # e.g. "multi-az", "asg-healthy", "circuit-breaker-open"

@dataclass  
class PropagationResult:
    """Result of fault propagation analysis."""
    origin_node: str
    mode: PropagationMode
    affected_nodes: list[str]                      # Ordered by propagation depth
    propagation_tree: dict[str, list[str]]         # parent → [children]
    edge_weights: dict[tuple[str, str], float]     # (src, dst) → weight
    total_impact_score: float                      # 0.0-1.0 normalized
    critical_path: list[str]                       # Highest-weight path
    isolated_by: list[PropagationEdge]             # Edges that blocked propagation (realistic only)

def fault_propagation(
    graph: InfraGraph,
    failed_node_id: str,
    mode: PropagationMode = PropagationMode.PESSIMISTIC,
    max_depth: int = 10,
    min_weight: float = 0.1,   # Edges below this weight are ignored in realistic mode
) -> PropagationResult:
    """
    Compute fault propagation from a failed node.
    
    Pessimistic: All reachable downstream nodes are affected (weight=1.0 for all edges).
    Realistic:   Edge weights are computed from redundancy/degradation metadata.
    """
    ...
```

### 2.2 Edge Weight Inference Rules (Convention over Configuration)

Edge weights are **automatically inferred** from node/edge attributes. No manual annotation required for common patterns.

| Pattern | Detection Method | Weight Adjustment |
|---------|-----------------|-------------------|
| **Multi-AZ redundancy** | Target node has siblings in ≥2 AZs with same role | 0.3 (70% resilient) |
| **ASG with healthy instances** | ASG node has `desired_count > 1` and `healthy_count >= desired_count` | 0.2 (80% resilient) |
| **Load balancer with multi-target** | ALB/NLB has ≥2 healthy targets | 0.3 |
| **NAT Gateway (single)** | Subnet has exactly 1 NAT in its route table | 1.0 (SPOF) |
| **NAT Gateway (multi-AZ)** | Subnet has NAT in ≥2 AZs | 0.4 |
| **Circuit breaker open** | Node tagged `circuit_breaker: open` or Envoy metadata | 0.0 (fully isolated) |
| **K8s ReplicaSet healthy** | Deployment has `ready_replicas >= desired_replicas` | 0.2 |
| **K8s single-pod** | Deployment has `replicas: 1` | 1.0 (SPOF) |
| **Default (no metadata)** | No redundancy signals detected | 1.0 (pessimistic default) |

```python
def _infer_edge_weight(
    graph: InfraGraph, 
    source: str, 
    target: str
) -> tuple[float, str]:
    """
    Infer propagation weight for an edge based on target node's redundancy.
    
    Returns:
        (weight, reason) — weight 0.0-1.0, reason for audit log
    """
    target_attrs = graph.get_node(target)
    if not target_attrs:
        return 1.0, "unknown-node"
    
    node_type = target_attrs.get("node_type")
    
    # Check Multi-AZ siblings
    siblings = graph.get_nodes_by_type(node_type)
    azs = {graph.get_node(s).get("availability_zone") for s in siblings 
           if graph.get_node(s) and s != target}
    target_az = target_attrs.get("availability_zone")
    if target_az and len(azs) >= 1:
        return 0.3, f"multi-az: {len(azs)+1} AZs"
    
    # Check ASG
    if node_type == NodeType.ASG:
        healthy = target_attrs.get("healthy_count", 0)
        desired = target_attrs.get("desired_count", 1)
        if healthy >= desired and desired > 1:
            return 0.2, f"asg-healthy: {healthy}/{desired}"
    
    # Check circuit breaker
    tags = target_attrs.get("tags", {})
    if tags.get("circuit_breaker") == "open":
        return 0.0, "circuit-breaker-open"
    
    # Check K8s replica count
    if node_type == NodeType.K8S_DEPLOYMENT:
        replicas = target_attrs.get("ready_replicas", 0)
        desired = target_attrs.get("desired_replicas", 1)
        if replicas >= desired and desired > 1:
            return 0.2, f"k8s-replicas: {replicas}/{desired}"
        if desired == 1:
            return 1.0, "k8s-single-pod"
    
    return 1.0, "default-no-redundancy"
```

### 2.3 Algorithm

```python
def fault_propagation(graph, failed_node_id, mode, max_depth, min_weight):
    visited = {}          # node_id → depth
    queue = [(failed_node_id, 0)]
    tree = {}             # parent → [children]
    weights = {}          # (src, dst) → weight
    isolated = []         # edges that blocked propagation
    
    while queue:
        node, depth = queue.pop(0)
        if node in visited or depth > max_depth:
            continue
        visited[node] = depth
        
        for neighbor in graph.get_neighbors(node, direction="outgoing"):
            if mode == PropagationMode.PESSIMISTIC:
                w, reason = 1.0, "pessimistic"
            else:
                w, reason = _infer_edge_weight(graph, node, neighbor)
            
            weights[(node, neighbor)] = w
            
            if w < min_weight:
                isolated.append(PropagationEdge(node, neighbor, w, reason))
                continue
            
            tree.setdefault(node, []).append(neighbor)
            queue.append((neighbor, depth + 1))
    
    # Compute critical path (highest cumulative weight)
    critical_path = _find_critical_path(tree, weights, failed_node_id)
    
    # Normalize impact score
    total_nodes = len(graph.graph.nodes)
    impact_score = len(visited) / total_nodes if total_nodes > 0 else 0.0
    
    return PropagationResult(
        origin_node=failed_node_id,
        mode=mode,
        affected_nodes=sorted(visited.keys(), key=lambda n: visited[n]),
        propagation_tree=tree,
        edge_weights=weights,
        total_impact_score=impact_score,
        critical_path=critical_path,
        isolated_by=isolated,
    )
```

---

## 3. Topology Delta Storage

### 3.1 Schema (`topology_changes` table)

```sql
CREATE TABLE topology_changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,              -- ISO 8601
    change_type TEXT NOT NULL,              -- 'node_added' | 'node_removed' | 'node_updated' | 'edge_added' | 'edge_removed'
    entity_id   TEXT NOT NULL,              -- Node ID or "src->dst" for edges
    entity_type TEXT,                       -- NodeType enum value
    old_value   TEXT,                       -- JSON: previous attributes (NULL for additions)
    new_value   TEXT,                       -- JSON: new attributes (NULL for removals)
    source      TEXT NOT NULL DEFAULT 'discovery',  -- 'cloudtrail' | 'discovery' | 'manual'
    source_detail TEXT,                     -- CloudTrail: event_id + principal; discovery: scan_id
    region      TEXT,
    account_id  TEXT
);

CREATE INDEX idx_topo_changes_time ON topology_changes(timestamp);
CREATE INDEX idx_topo_changes_entity ON topology_changes(entity_id);
CREATE INDEX idx_topo_changes_source ON topology_changes(source);
```

### 3.2 Retention Policy

- **7 days** of deltas retained (configurable via `TOPO_DELTA_RETENTION_DAYS`)
- Cleanup runs daily at 02:00 UTC (piggyback on existing cron)
- For longer history: aggregate daily summaries before purging

### 3.3 Delta Capture

```python
def capture_delta(
    old_graph: InfraGraph | None,
    new_graph: InfraGraph,
    source: str = "discovery",
    source_detail: str | None = None,
) -> list[TopologyChange]:
    """
    Compare two graph snapshots and record deltas.
    Called after each graph rebuild (60s poll cycle).
    """
    changes = []
    
    old_nodes = set(old_graph.graph.nodes) if old_graph else set()
    new_nodes = set(new_graph.graph.nodes)
    
    # Added nodes
    for node_id in new_nodes - old_nodes:
        changes.append(TopologyChange(
            change_type="node_added",
            entity_id=node_id,
            new_value=new_graph.get_node(node_id),
            source=source,
        ))
    
    # Removed nodes
    for node_id in old_nodes - new_nodes:
        changes.append(TopologyChange(
            change_type="node_removed",
            entity_id=node_id,
            old_value=old_graph.get_node(node_id),
            source=source,
        ))
    
    # Updated nodes (status/attribute changes)
    for node_id in old_nodes & new_nodes:
        old_attrs = old_graph.get_node(node_id)
        new_attrs = new_graph.get_node(node_id)
        if old_attrs != new_attrs:
            changes.append(TopologyChange(
                change_type="node_updated",
                entity_id=node_id,
                old_value=old_attrs,
                new_value=new_attrs,
                source=source,
            ))
    
    # Edge diffs (same pattern)
    # ...
    
    return changes
```

### 3.4 Time-Travel Query

```python
def rebuild_at(timestamp: datetime) -> InfraGraph:
    """
    Rebuild the graph as it was at a given timestamp.
    Uses current graph - applies reverse deltas back to target time.
    """
    current = graph_cache.get_current()
    deltas = db.query(TopologyChange)\
        .filter(TopologyChange.timestamp > timestamp)\
        .order_by(TopologyChange.timestamp.desc())\
        .all()
    
    graph = current.copy()
    for delta in deltas:
        _reverse_apply(graph, delta)
    
    return graph
```

---

## 4. Alarm → Topology → RCA Integration Pipeline

### 4.1 Data Flow

```
CloudWatch Alarm (EventBridge / 60s poll)
    │
    ▼
detect_agent.on_alarm(alarm)
    │
    ├─→ graph_cache.get_current()           # O(1), in-memory
    │       │
    │       ▼
    │   fault_propagation(graph, resource_id, PESSIMISTIC)
    │       │
    │       ▼
    │   PropagationResult {
    │       affected_nodes: ["subnet-abc", "nat-xyz", "pod-123"],
    │       impact_score: 0.35,
    │       critical_path: ["i-abc" → "subnet-abc" → "nat-xyz"],
    │   }
    │
    ├─→ detect_network_anomalies(graph)     # ~20ms
    │       │
    │       ▼
    │   AnomalyReport { blackhole_routes: [...], orphan_nodes: [...] }
    │
    └─→ build_topo_context(propagation, anomalies)
            │
            ▼
        rca_agent.analyze(
            issue_id="HI-001",
            topology_context=topo_context    # Injected into RCA prompt
        )
```

### 4.2 RCA Prompt Topology Section (Template)

```python
TOPO_CONTEXT_TEMPLATE = """
## Network Topology Context

### Fault Propagation (from {origin_node})
- Mode: {mode}
- Impact Score: {impact_score:.0%} of infrastructure
- Affected nodes ({affected_count}): {affected_summary}
- Critical path: {critical_path}
- Isolated by redundancy: {isolated_summary}

### Network Anomalies
{anomaly_summary}

### Recent Topology Changes (last 1h)
{recent_changes_summary}
"""
```

### 4.3 Graceful Degradation

```python
def build_topo_context(resource_id: str) -> str | None:
    """Build topology context for RCA. Returns None if graph unavailable."""
    graph = graph_cache.get_current()
    if graph is None:
        logger.warning("Graph cache empty, skipping topology context")
        return None
    
    try:
        propagation = fault_propagation(graph, resource_id, PropagationMode.REALISTIC)
        anomalies = detect_network_anomalies(graph)
        changes = get_recent_changes(timedelta(hours=1))
        return format_topo_context(propagation, anomalies, changes)
    except Exception:
        logger.exception("Topology context generation failed")
        return None
```

RCA prompt template uses conditional section:
```python
if topo_context:
    prompt += topo_context
# If None, RCA proceeds with metrics + logs only (graceful degrade)
```

---

## 5. Interface Stubs for Developer

### 5.1 Graph Cache (Developer to implement)

```python
class GraphCache:
    """In-memory graph cache with periodic refresh."""
    
    def __init__(self, refresh_interval_s: int = 60):
        self._graph: InfraGraph | None = None
        self._previous: InfraGraph | None = None
        self._last_refresh: datetime | None = None
        self._lock = asyncio.Lock()
    
    async def refresh(self) -> None:
        """Called by background task every refresh_interval_s."""
        async with self._lock:
            new_graph = await build_graph_from_aws()  # collector.py
            if self._graph:
                deltas = capture_delta(self._graph, new_graph, source="discovery")
                await store_deltas(deltas)
            self._previous = self._graph
            self._graph = new_graph
            self._last_refresh = datetime.utcnow()
    
    def get_current(self) -> InfraGraph | None:
        return self._graph
    
    def is_available(self) -> bool:
        return self._graph is not None
    
    async def inject_alarm(self, resource_id: str, alarm_state: str) -> None:
        """Update node status from alarm (between full refreshes)."""
        if self._graph:
            self._graph.update_node_status(resource_id, alarm_state)

# Singleton
graph_cache = GraphCache()
```

### 5.2 detect_agent Integration Point

```python
# In detect_agent.py or rca/network_context.py
async def enrich_with_topology(issue_id: str, resource_id: str) -> str | None:
    """
    Called by RCA pipeline to get topology context.
    Returns formatted string for prompt injection, or None.
    """
    return build_topo_context(resource_id)
```

---

## 6. File Layout

```
src/aci/topology/
├── types.py              # NodeType, EdgeType (existing)
├── engine.py             # InfraGraph + builders (existing)
├── algorithms.py         # reachability, impact, path, anomaly (existing)
├── propagation.py        # NEW: fault_propagation() + edge weight inference
├── delta.py              # NEW: capture_delta() + TopologyChange model
├── cache.py              # NEW: GraphCache singleton
├── serializers.py        # ReactFlow export (existing)
└── tools.py              # Strands tools (existing)
```

---

## 7. Estimates

| Component | Lines (est.) | Days | Owner |
|-----------|-------------|------|-------|
| `propagation.py` | ~250 | 2 | Architect (design) → Developer (impl) |
| `delta.py` + migration | ~180 | 1.5 | Developer |
| `cache.py` | ~100 | 1 | Developer |
| RCA prompt integration | ~80 | 0.5 | Developer |
| Tests | ~300 | 2 | Tester |
| **Total** | **~910** | **~7 days** | |

---

## 8. Open Questions

1. **CloudTrail integration for `source` field** — Do we have CloudTrail events flowing into the system? If not, all deltas will be `source=discovery` initially.
2. **Envoy/Istio metrics for circuit breaker** — Requires service mesh. Start with static tags, upgrade later.
3. **Multi-account topology** — Current `collector.py` is single-account. Cross-account assume_role chain needed for TGW topology.
