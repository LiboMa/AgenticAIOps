# Graph-Based Fault Propagation Design

> **Module**: `src/aci/topology/propagation.py`  
> **Author**: Architect  
> **Date**: 2026-02-26  
> **Status**: DRAFT — Pending Review  
> **Depends on**: topology engine (`engine.py`), algorithms (`algorithms.py`), network_context (`rca/network_context.py`), detect_agent (`detect_agent.py`)

---

## 1. Background & Motivation

### 1.1 Current State

The topology module provides **static** failure analysis:

- `impact_analysis(graph, failed_node_id)` — removes a node, counts affected neighbours
- `detect_anomalies(graph)` — finds structural issues (blackhole routes, orphan nodes)
- `NetworkContextEnricher.enrich()` — wraps both into a dict for RCA

**Gaps**:
1. **No propagation model** — `impact_analysis` only counts direct neighbours + subnets that lose IGW paths. It does not model cascading failures (e.g., NAT failure → private subnets → services → pods).
2. **No degradation awareness** — multi-AZ, ASG, or circuit-breaker protection is ignored; everything is treated as hard failure.
3. **No temporal dimension** — topology is treated as a snapshot; changes (drift, deployments) are not tracked.
4. **Loose coupling with RCA** — Developer confirmed: `detect_agent.py` calls topology tools independently; results are not automatically injected into the RCA agent prompt.

### 1.2 Target State

```
CloudWatch Alarm / DetectAgent anomaly
   │
   ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────────┐
│ DetectResult  │───▶│ fault_propagation│───▶│  PropagationResult   │
│ .anomalies    │    │ (this design)    │    │  .waves[]            │
│ .topology_ctx │    │                  │    │  .blast_radius       │
└──────────────┘    └──────────────────┘    │  .degradation_map    │
                           │                │  .rca_context_block   │
                           │                └──────────────────────┘
                           ▼                           │
                    topology_changes                   ▼
                    delta store                  RCA Agent prompt
                    (CloudTrail /                (auto-injected)
                     drift detect)
```

---

## 2. Goals

| # | Goal | Metric |
|---|------|--------|
| G1 | Multi-hop fault propagation with wave-based simulation | ≥3 hops depth |
| G2 | Dual propagation mode (pessimistic / realistic) | Degradation reduces blast radius by 30-60% |
| G3 | Topology change delta tracking | Changes detected within 5 min of CloudTrail event |
| G4 | Auto-inject propagation context into RCA agent prompt | Zero manual tool calls needed |
| G5 | <500ms propagation on graphs ≤2,000 nodes | P95 latency |
| G6 | 100% backward compatible — no API URL changes | Zero breaking change |

---

## 3. Design

### 3.1 Propagation Model

#### 3.1.1 Data Structures

```python
# src/aci/topology/propagation.py

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

class PropagationMode(str, Enum):
    """How failure spreads through the graph."""
    PESSIMISTIC = "pessimistic"   # Every dependency = hard failure
    REALISTIC = "realistic"       # Degradation-aware (default)

class ImpactLevel(str, Enum):
    """Per-node impact severity after propagation."""
    FAILED = "failed"             # Node is down
    DEGRADED = "degraded"         # Partial functionality loss
    AT_RISK = "at_risk"           # Reachable via single path only
    HEALTHY = "healthy"           # Unaffected

@dataclass
class PropagationWave:
    """One hop of failure spread."""
    depth: int                                        # 0 = root failure
    affected_nodes: list[dict[str, Any]]              # [{node_id, node_type, impact_level, reason}]
    edge_cuts: list[dict[str, str]]                   # [{source, target, edge_type}]

@dataclass
class DegradationFactor:
    """A protective capability that reduces impact."""
    factor_type: str              # "multi_az" | "asg" | "circuit_breaker" | "replica_set" | "multi_path"
    node_id: str
    description: str
    mitigation_weight: float      # 0.0–1.0 (1.0 = fully mitigated)

@dataclass
class PropagationResult:
    """Complete result of fault propagation analysis."""
    root_failure_id: str
    root_failure_type: str
    mode: PropagationMode
    waves: list[PropagationWave] = field(default_factory=list)
    total_affected: int = 0
    total_degraded: int = 0
    total_at_risk: int = 0
    blast_radius_score: float = 0.0                   # 0.0–1.0 (fraction of graph affected)
    degradation_factors: list[DegradationFactor] = field(default_factory=list)
    max_depth_reached: int = 0
    propagation_time_ms: int = 0

    # Pre-rendered for RCA agent injection
    rca_context_block: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API / telemetry."""
        return {
            "root_failure": {"id": self.root_failure_id, "type": self.root_failure_type},
            "mode": self.mode.value,
            "waves": [
                {"depth": w.depth, "affected": w.affected_nodes, "edge_cuts": w.edge_cuts}
                for w in self.waves
            ],
            "summary": {
                "total_affected": self.total_affected,
                "total_degraded": self.total_degraded,
                "total_at_risk": self.total_at_risk,
                "blast_radius_score": round(self.blast_radius_score, 3),
                "max_depth": self.max_depth_reached,
            },
            "degradation_factors": [
                {"type": d.factor_type, "node": d.node_id, "desc": d.description, "weight": d.mitigation_weight}
                for d in self.degradation_factors
            ],
            "propagation_time_ms": self.propagation_time_ms,
            "rca_context_block": self.rca_context_block,
        }
```

#### 3.1.2 Core Algorithm — `fault_propagation()`

```
BFS from root failure node:
  Wave 0: Mark root as FAILED
  Wave N:
    For each FAILED/DEGRADED node in wave N-1:
      For each downstream neighbour (successors + predecessors via undirected for networking):
        If node already visited → skip
        Evaluate degradation factors → decide FAILED vs DEGRADED vs AT_RISK
        Record in wave N
    Stop when:
      - No new nodes affected, OR
      - max_depth reached (default 10), OR
      - graph fully visited

> **Non-destructive**: Unlike `impact_analysis()` which copies the graph and removes nodes, `fault_propagation()` is read-only. It tracks state in an external `visited: dict[str, ImpactLevel]` dict, never modifying the InfraGraph. This means no `InfraGraph.copy()` or `update_node_status()` methods are needed.
```

**Propagation rules by edge type**:

| Edge Type | Propagation Direction | Bidirectional? | Propagation Rule |
|-----------|----------------------|----------------|-----------------|
| `CONTAINS` | parent → child only | No | Parent fails → children DEGRADED (not FAILED, containers may survive); child fail does NOT propagate up |
| `ROUTES_TO` | router → target (single) | No | Router fails → routed targets lose that path; target fail creates blackhole but does not propagate back |
| `ASSOCIATED_WITH` | subnet ↔ RTB | **Yes** | Mutual binding — either side fails → other loses routing capability |
| `ATTACHED_TO` | resource → VPC | **No propagation** | IGW/TGW fail does not kill VPC (VPC is container); VPC fail does not propagate to attachments |
| `HOSTED_IN` | NAT/VPCE → subnet (single) | No | NAT fails → hosted subnet loses egress; subnet fail does not affect NAT entity |
| `PEERS_WITH` | VPC ↔ VPC | **Yes** | Peering failure → cross-VPC traffic broken both directions |
| `EXPOSES` | Service ↔ Deployment | **Yes** | Service fails → external access lost; Deployment fails → service degrades |
| `RUNS_ON` | Node → Pod (reverse) | No | Node fails → all pods on it FAILED; pod fail does NOT affect node |
| `SELECTS` | Pod → Service (reverse, degradation) | No | Pod fails → service DEGRADED (if replicas remain); service fail → pods still run but no traffic |
| `DEPENDS_ON` | downstream → upstream (single) | No | Downstream fail does not affect upstream |

> **Implementation note**: The BFS walker uses the NetworkX graph in both directions (successors + predecessors) but applies the direction rules above as a filter. Only `ASSOCIATED_WITH`, `PEERS_WITH`, and `EXPOSES` propagate bidirectionally.

#### 3.1.3 Interface

```python
def fault_propagation(
    graph: InfraGraph,
    failed_node_id: str,
    *,
    mode: PropagationMode = PropagationMode.REALISTIC,
    max_depth: int = 10,
    custom_degradation: dict[str, float] | None = None,
) -> PropagationResult:
    """
    Simulate fault propagation from a failed node through the infrastructure graph.

    Args:
        graph: InfraGraph instance (already built from VPC/K8s topology).
        failed_node_id: The node that has failed.
        mode: PESSIMISTIC (all dependencies fail) or REALISTIC (degradation-aware).
        max_depth: Maximum BFS depth.
        custom_degradation: Override degradation weights per node_id.

    Returns:
        PropagationResult with wave-by-wave breakdown + RCA context block.
    """
```

### 3.2 Degradation Inference Rules

In `REALISTIC` mode, the algorithm auto-detects protective capabilities from graph structure and node metadata:

| Factor | Detection Rule | Default Weight |
|--------|---------------|----------------|
| **Multi-AZ** | Node has siblings in different AZs (from `raw.availability_zone`) | 0.7 |
| **ASG** | Node type is `EC2_INSTANCE` with ASG parent edge | 0.8 |
| **Replica Set** | K8s Deployment with `raw.replicas > 1` | `1.0 - (1/replicas)` ; replicas ≤ 1 → no factor generated |
| **Multi-Path** | Node has ≥2 independent paths to internet (from `can_reach_internet` via different IGW/NAT) | 0.5 |
| **Circuit Breaker** | Service has annotation `resilience.io/circuit-breaker=true` in raw metadata | 0.6 |
| **NAT Redundancy** | Multiple NAT gateways in different AZs serving same route table | 0.7 |

**Impact downgrade logic**:

```python
def _evaluate_impact(
    mode: PropagationMode,
    node_id: str,
    node_data: dict,
    incoming_impact: ImpactLevel,
    graph: InfraGraph,
    custom_degradation: dict[str, float] | None,
) -> tuple[ImpactLevel, list[DegradationFactor]]:
    """
    Given the incoming impact level from a failed upstream,
    determine this node's actual impact considering degradation.

    Returns:
        (actual_impact, list of factors that applied)
    """
    if mode == PropagationMode.PESSIMISTIC:
        return incoming_impact, []

    factors = _detect_degradation_factors(node_id, node_data, graph)

    # Apply custom overrides
    if custom_degradation and node_id in custom_degradation:
        factors.append(DegradationFactor(
            factor_type="custom",
            node_id=node_id,
            description="Custom override",
            mitigation_weight=custom_degradation[node_id],
        ))

    if not factors:
        return incoming_impact, []

    # Max mitigation wins (not cumulative — conservative)
    max_weight = max(f.mitigation_weight for f in factors)

    if max_weight >= 0.8:
        return ImpactLevel.AT_RISK, factors      # Well-protected
    elif max_weight >= 0.4:
        return ImpactLevel.DEGRADED, factors      # Partially protected
    else:
        return incoming_impact, factors            # Minimal protection
```

### 3.3 Topology Change Delta Tracking

#### 3.3.1 Schema — `TopologyChange`

```python
# src/aci/topology/changes.py

@dataclass
class TopologyChange:
    """A single topology change event."""
    change_id: str                    # uuid
    timestamp: str                    # ISO 8601
    source: str                       # "cloudtrail" | "drift_detect" | "k8s_watch" | "manual"
    change_type: str                  # "node_added" | "node_removed" | "node_updated" | "edge_added" | "edge_removed"
    node_id: str | None = None
    edge_source: str | None = None
    edge_target: str | None = None
    before: dict[str, Any] | None = None   # Previous state (for updates)
    after: dict[str, Any] | None = None    # New state
    metadata: dict[str, Any] = field(default_factory=dict)  # CloudTrail event name, user, etc.

@dataclass
class TopologyDelta:
    """A batch of changes between two snapshots."""
    delta_id: str
    from_timestamp: str
    to_timestamp: str
    changes: list[TopologyChange] = field(default_factory=list)
    summary: str = ""

    @property
    def has_breaking_changes(self) -> bool:
        """True if any change removed a node or edge (potential connectivity loss)."""
        return any(c.change_type in ("node_removed", "edge_removed") for c in self.changes)
```

#### 3.3.2 Delta Detection Methods

| Source | Mechanism | Latency |
|--------|-----------|---------|
| **CloudTrail** | Poll `LookupEvents` with resource type filter (VPC, Subnet, RouteTable, etc.) | ~5 min (CloudTrail delivery delay) |
| **Drift Detect** | Periodic graph snapshot diff (current vs cached) | Configurable (default 15 min) |
| **K8s Watch** | (Phase 2) `kubectl get events --watch` or informer-based | Real-time |

**Drift detection** algorithm:
```
1. Load cached graph snapshot (from last detection cycle)
2. Build fresh graph from collector
3. Diff node sets → detect added/removed
4. Diff edge sets → detect added/removed
5. For common nodes: diff attributes → detect updated
6. Store delta + update cached snapshot
```

#### 3.3.3 Storage

Phase 1: JSON file per delta — `data/topology_deltas/{delta_id}.json`  
Phase 2: SQLite `topology_changes` table (aligns with HealthIssue store pattern)

Retention: 7 days (configurable), auto-purge via detect_agent heartbeat.

### 3.4 Alert → Topology → RCA Auto-Injection

This is the critical data flow that Developer identified as missing.

#### 3.4.1 Current Flow (Broken)

```
DetectAgent.run_detection()
  ├─ EventCorrelator.collect()         → CorrelatedEvent
  ├─ PatternMatcher.match()            → pattern_matches
  └─ KnowledgeBase.add_pattern()       → store

IncidentOrchestrator.handle_incident(detect_result=...)
  ├─ Stage 1: skip (reuse detect_result)
  ├─ Stage 2: RCA inference             ← NO topology context
  ├─ Stage 3: SOP safety
  └─ Stage 4: execute

RCA Agent tools (rca_agent.py):
  ├─ query_reachability()              ← LLM decides to call (unreliable)
  ├─ find_network_path()               ← LLM decides to call (unreliable)
  └─ detect_network_anomalies()        ← LLM decides to call (unreliable)
```

#### 3.4.2 Proposed Flow

```
DetectAgent.run_detection()
  ├─ EventCorrelator.collect()           → CorrelatedEvent
  ├─ PatternMatcher.match()              → pattern_matches
  ├─ [NEW] TopologyContextBuilder.build()→ PropagationResult (if anomalies found)
  ├─ KnowledgeBase.add_pattern()         → store
  └─ DetectResult now includes:
       .topology_context: dict | None     ← NEW field
       .propagation_result: dict | None   ← NEW field

IncidentOrchestrator.handle_incident(detect_result=...)
  ├─ Stage 1: skip (reuse)
  ├─ Stage 2: RCA inference
  │    └─ [NEW] inject detect_result.propagation_result.rca_context_block
  │         into the RCA agent system prompt / telemetry context
  ├─ Stage 3: SOP safety
  └─ Stage 4: execute
```

#### 3.4.3 Integration Point — `DetectResult` Extension

```python
# detect_agent.py — extend DetectResult

@dataclass
class DetectResult:
    # ... existing fields ...

    # NEW: Topology context (from NetworkContextEnricher)
    topology_context: Optional[Dict[str, Any]] = None

    # NEW: Fault propagation result (from fault_propagation)
    propagation_result: Optional[Dict[str, Any]] = None
```

#### 3.4.4 Integration Point — `run_detection()` Extension

```python
# detect_agent.py — after pattern matching, before return

# ── Topology Context (NEW) ──
if event and event.anomalies:
    try:
        from src.rca.network_context import NetworkContextEnricher
        from src.aci.topology.propagation import fault_propagation, PropagationMode

        enricher = NetworkContextEnricher()
        vpc_id = self._extract_vpc_id(event)  # from event metadata
        if vpc_id:
            net_ctx = enricher.enrich(
                region=self.region,
                vpc_id=vpc_id,
                failed_resource_id=self._extract_failed_resource(event),
            )
            result.topology_context = net_ctx.to_dict()

            # Run propagation if critical anomalies found
            if net_ctx.critical_anomalies:
                graph = enricher._build_graph(self.region, vpc_id)  # expose helper
                for anomaly in net_ctx.critical_anomalies:
                    prop_result = fault_propagation(
                        graph,
                        anomaly["node_id"],
                        mode=PropagationMode.REALISTIC,
                    )
                    result.propagation_result = prop_result.to_dict()
                    break  # First critical anomaly only (for now)
    except Exception as e:
        logger.warning(f"[{detect_id}] Topology enrichment failed (non-fatal): {e}")
```

#### 3.4.5 RCA Context Block Format

The `rca_context_block` is a pre-rendered string injected into the RCA agent prompt. Format:

```
## 🗺️ Network Topology Context

**Failed Resource**: nat-0abc123 (NAT Gateway)
**Propagation Mode**: realistic
**Blast Radius**: 0.34 (34% of graph affected)

### Wave 0 (Root Failure)
- nat-0abc123 [NAT Gateway] — FAILED

### Wave 1 (Direct Impact)
- subnet-priv-1a [Private Subnet] — DEGRADED (multi-AZ: NAT in us-east-1b still active)
- subnet-priv-1b [Private Subnet] — FAILED (single NAT path)
- rtb-priv [Route Table] — DEGRADED

### Wave 2 (Cascading)
- vpce-s3 [VPC Endpoint] — AT_RISK (hosted in affected subnet, but S3 gateway route unaffected)

### Degradation Factors
- multi_az on subnet-priv-1a: weight=0.7 (NAT redundancy across AZs)

### Recent Topology Changes (last 1h)
- 10:02 UTC: Route added rtb-priv → nat-0abc123 (source: cloudtrail, user: deploy-role)
- 09:45 UTC: NAT Gateway nat-0xyz789 removed (source: cloudtrail, user: cleanup-lambda)
  ⚠️ This removal may have eliminated redundancy for subnet-priv-1b
```

### 3.5 Cache Miss & Graceful Degradation Strategy

**Definitive behavior** (supersedes any prior Slack discussion):

```
Cache hit  + Level 1 无异常  → Level 1 context only (<50ms)
Cache hit  + Level 1 有异常  → Level 1 + Level 2 deep analysis (3-5s)
Cache miss (graph=None)      → skip topology section entirely
                               RCA proceeds with metrics + logs only
                               (NOT fallback to Level 2 live query)
```

**Rationale**: Cache miss means either cold start or boto3 failure. Doing a live
Level 2 query at RCA time would add 3-5s latency to *every* RCA during outages —
precisely when boto3 is most likely to be slow/erroring. Better to degrade
gracefully and let the background refresh recover the cache.

**InfraGraph prerequisites** (Developer: add before GraphCache):
- `InfraGraph.update_node_status(resource_id, status)` — for `inject_alarm()`
- `InfraGraph.copy()` — deep copy for `rebuild_at()` time-travel

```python
# In _enrich_topology():
graph = graph_cache.get_current()  # may be None
if graph is None:
    logger.info("Graph cache empty, topology context skipped")
    return  # result.topology_context remains None — RCA handles gracefully
```

### 3.6 API Endpoints

No new URL prefixes. Extensions to existing `/api/topology/*`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/topology/vpc/{vpc_id}/propagation?node_id=X&mode=realistic` | Run fault propagation |
| GET | `/api/topology/vpc/{vpc_id}/changes?since=ISO&source=cloudtrail` | Get topology deltas |
| GET | `/api/topology/vpc/{vpc_id}/graph?annotate_propagation=node_id` | ReactFlow graph with propagation overlays |

#### Response: `/api/topology/vpc/{vpc_id}/propagation`

```json
{
  "root_failure": {"id": "nat-0abc123", "type": "nat"},
  "mode": "realistic",
  "waves": [
    {
      "depth": 0,
      "affected": [
        {"node_id": "nat-0abc123", "node_type": "nat", "impact_level": "failed", "reason": "root failure"}
      ],
      "edge_cuts": []
    },
    {
      "depth": 1,
      "affected": [
        {"node_id": "subnet-priv-1b", "node_type": "subnet", "impact_level": "failed", "reason": "single NAT path cut"},
        {"node_id": "subnet-priv-1a", "node_type": "subnet", "impact_level": "degraded", "reason": "multi-AZ NAT (nat-0xyz in 1b still active)"}
      ],
      "edge_cuts": [
        {"source": "rtb-priv", "target": "nat-0abc123", "edge_type": "routes_to"}
      ]
    }
  ],
  "summary": {
    "total_affected": 2,
    "total_degraded": 1,
    "total_at_risk": 1,
    "blast_radius_score": 0.34,
    "max_depth": 2
  },
  "degradation_factors": [
    {"type": "multi_az", "node": "subnet-priv-1a", "desc": "NAT redundancy across AZs", "weight": 0.7}
  ],
  "propagation_time_ms": 12
}
```

---

## 4. Implementation Plan

### Phase 1 (Day 1) — Core Propagation (~350 lines)

| File | What | Lines (est) |
|------|------|-------------|
| `src/aci/topology/propagation.py` | `fault_propagation()` + models + degradation inference | ~280 |
| `src/aci/topology/__init__.py` | Export propagation | +2 |
| `tests/test_propagation.py` | Core algorithm tests (pessimistic + realistic + edge cases) | ~200 |

### Phase 2 (Day 1-2) — DetectAgent Integration (~80 lines)

| File | What | Lines (est) |
|------|------|-------------|
| `src/detect_agent.py` | Add `topology_context` + `propagation_result` fields + enrichment in `run_detection()` | ~50 |
| `src/incident_orchestrator.py` | Inject `rca_context_block` into Stage 2 telemetry | ~30 |

### Phase 3 (Day 2) — Delta Tracking (~200 lines)

| File | What | Lines (est) |
|------|------|-------------|
| `src/aci/topology/changes.py` | `TopologyChange` + `TopologyDelta` + drift detector + CloudTrail poller | ~180 |
| `tests/test_topology_changes.py` | Delta detection + purge tests | ~100 |

### Phase 4 (Day 2-3) — API + ReactFlow (~100 lines)

| File | What | Lines (est) |
|------|------|-------------|
| `src/aci/topology/api.py` | 3 new endpoints | ~60 |
| `src/aci/topology/serializers.py` | `annotate_propagation()` overlay on ReactFlow output | ~40 |

**Total**: ~630 lines new code + ~500 lines tests

---

## 5. Interface Stubs for Developer

These are the contracts for integration. Developer: code against these interfaces.

### 5.1 `fault_propagation()` — topology/propagation.py

```python
from src.aci.topology.propagation import fault_propagation, PropagationMode, PropagationResult

# Build graph first (you already have this)
from src.aci.topology.engine import InfraGraph
graph = InfraGraph().build_from_vpc_topology(topo_json)

# Run propagation
result: PropagationResult = fault_propagation(
    graph,
    "nat-0abc123",
    mode=PropagationMode.REALISTIC,
    max_depth=10,
)

# For RCA injection:
rca_block: str = result.rca_context_block
# Inject into telemetry dict:
telemetry["network_propagation"] = result.to_dict()
telemetry["network_propagation_summary"] = rca_block
```

### 5.2 DetectResult Extension — detect_agent.py

```python
# New fields on DetectResult:
topology_context: Optional[Dict[str, Any]] = None      # NetworkContext.to_dict()
propagation_result: Optional[Dict[str, Any]] = None     # PropagationResult.to_dict()

# In run_detection(), after pattern matching:
# Call _enrich_topology(event, result) → populates both fields
```

### 5.3 RCA Injection — incident_orchestrator.py

```python
# In handle_incident(), Stage 2 (RCA):
if detect_result and detect_result.propagation_result:
    rca_block = detect_result.propagation_result.get("rca_context_block", "")
    if rca_block:
        # Prepend to telemetry for LLM context
        telemetry["network_propagation_context"] = rca_block
```

### 5.4 TopologyDelta Query — topology/changes.py

```python
from src.aci.topology.changes import TopologyDeltaStore

store = TopologyDeltaStore(data_dir="data/topology_deltas")

# Record a change (called by drift detector or CloudTrail poller)
store.record_change(TopologyChange(
    change_id="...",
    timestamp="...",
    source="cloudtrail",
    change_type="node_removed",
    node_id="nat-0xyz789",
    metadata={"event_name": "DeleteNatGateway", "user": "cleanup-lambda"},
))

# Query recent changes
delta = store.get_delta(since="2026-02-26T09:00:00Z")
```

---

## 6. Trade-offs & Alternatives

### Considered and Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| **Full event-sourced graph** (store every state transition) | Over-engineering for Phase 1; delta snapshots sufficient |
| **Probabilistic propagation** (Monte Carlo simulation) | Performance cost (>500ms for 2K nodes); deterministic BFS covers 95% of cases |
| **Real-time K8s watch integration** | Requires persistent WebSocket; defer to Phase 2 |
| **Separate propagation microservice** | Unnecessary latency hop; in-process function call is <500ms |

### Known Limitations

1. **Cross-region propagation** — current graph is per-region; cross-region peering requires multi-graph stitching (P2)
2. **Dynamic degradation** — ASG scaling events change degradation in real-time; we use point-in-time snapshot
3. **CloudTrail latency** — 5-min delivery delay means changes during active incident may be missed; drift detection (15-min) is backup
4. **LLM context window** — `rca_context_block` for large graphs may exceed token budget; truncation strategy: show top 3 waves + critical factors only

---

## 7. Compatibility

- **No URL changes** — new endpoints extend existing `/api/topology/*` prefix
- **DetectResult backward compatible** — new fields default to `None`; existing consumers unaffected
- **IncidentOrchestrator backward compatible** — topology injection is additive (new key in telemetry dict)
- **ReactFlow backward compatible** — propagation overlay is opt-in query parameter

---

## 8. Testing Strategy

| Category | Tests | Coverage Target |
|----------|-------|----------------|
| Propagation algorithm (pessimistic) | BFS depth, all edge types, cycle handling, max_depth | 100% |
| Propagation algorithm (realistic) | All degradation factor types, weight thresholds, custom overrides | 100% |
| RCA context block rendering | Format validation, truncation, edge cases (empty graph, no anomalies) | 100% |
| Delta tracking | Add/remove/update detection, purge, CloudTrail source | 90% |
| DetectAgent integration | `topology_context` populated, non-fatal fallback on failure | 90% |
| API endpoints | Response schema, error handling, query params | 85% |

Estimated: **~500 test lines** across 2 test files (updated per Tester feedback).

---

## 9. Open Questions

1. **Degradation factor sources** — should we support user-defined degradation annotations (e.g., Terraform tags `resilience:multi-az=true`)? → Suggest Phase 2.
2. **Cross-graph propagation** — when VPC peering spans regions, do we stitch graphs or treat remote VPC as opaque? → Suggest opaque for Phase 1.
3. **RCA context block token budget** — should we hard-cap at N characters or let the RCA agent manage truncation? → Suggest 2,000 char cap with progressive detail reduction.

---

*Architect — 📐 Ready for review. @cloud-mbot-researcher-1 please evaluate. @cloud-mbot-developer interface stubs are in §5, start with `detect_agent` → `graph_cache` → `rca_prompt` integration points.*
