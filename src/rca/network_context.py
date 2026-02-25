"""
RCA Network Context Enrichment — injects VPC/topology data into root cause analysis.

Uses the ACI Topology engine (InfraGraph + algorithms) to provide
network-level context during RCA:

1. Structural anomalies (blackhole routes, orphan nodes, cycles)
2. Reachability analysis (subnet → internet path)
3. Impact radius (blast radius of a failed resource)
4. Security group dependency chains

This context helps the RCA engine distinguish between application-level
failures and infrastructure/network-level root causes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class NetworkContext:
    """Network topology context for RCA enrichment.

    Attributes:
        vpc_id: VPC under analysis.
        region: AWS region.
        anomalies: Structural anomalies detected in the topology.
        reachability: Subnet reachability results.
        impact: Blast radius of a simulated failure.
        security_group_chains: SG dependency relationships.
        summary: Human-readable summary for LLM/agent consumption.
        raw_graph_stats: Node/edge counts and type breakdown.
    """

    vpc_id: str = ""
    region: str = ""
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    reachability: List[Dict[str, Any]] = field(default_factory=list)
    impact: Optional[Dict[str, Any]] = None
    security_group_chains: Dict[str, List[str]] = field(default_factory=dict)
    summary: str = ""
    raw_graph_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON / telemetry injection."""
        return {
            "vpc_id": self.vpc_id,
            "region": self.region,
            "anomalies": self.anomalies,
            "anomaly_count": len(self.anomalies),
            "reachability": self.reachability,
            "impact": self.impact,
            "security_group_chains": self.security_group_chains,
            "summary": self.summary,
            "graph_stats": self.raw_graph_stats,
        }

    @property
    def has_network_issues(self) -> bool:
        """True if any anomalies or reachability problems detected."""
        if self.anomalies:
            return True
        for r in self.reachability:
            if not r.get("can_reach_internet", True):
                return True
        return False

    @property
    def critical_anomalies(self) -> List[Dict[str, Any]]:
        """Filter to critical/high severity anomalies only."""
        return [
            a for a in self.anomalies
            if a.get("severity") in ("critical", "high")
        ]


class NetworkContextEnricher:
    """Enriches RCA with network topology context.

    Builds an InfraGraph from the collector, runs anomaly detection
    and reachability checks, and returns a NetworkContext for injection
    into RCA results.

    Usage:
        enricher = NetworkContextEnricher()
        ctx = enricher.enrich(region="us-east-1", vpc_id="vpc-abc123")
        # Inject into RCA telemetry:
        telemetry["network_context"] = ctx.to_dict()
    """

    def __init__(self, collector=None, graph_cls=None):
        """Initialize with optional dependency injection for testing.

        Args:
            collector: Module with collect_vpc_topology(region, vpc_id).
                       Defaults to src.aci.topology.collector.
            graph_cls: InfraGraph class. Defaults to src.aci.topology.engine.InfraGraph.
        """
        self._collector = collector
        self._graph_cls = graph_cls

    @property
    def collector(self):
        """Lazy-load the topology collector."""
        if self._collector is None:
            try:
                from src.aci.topology.collector import (
                    collect_vpc_topology,
                    collect_region_topology,
                )
                # Wrap functions into a simple namespace
                import types

                self._collector = types.SimpleNamespace(
                    collect_vpc_topology=collect_vpc_topology,
                    collect_region_topology=collect_region_topology,
                )
            except ImportError:
                logger.warning("Topology collector not available")
        return self._collector

    @property
    def graph_cls(self):
        """Lazy-load InfraGraph class."""
        if self._graph_cls is None:
            try:
                from src.aci.topology.engine import InfraGraph

                self._graph_cls = InfraGraph
            except ImportError:
                logger.warning("InfraGraph not available")
        return self._graph_cls

    def enrich(
        self,
        region: str,
        vpc_id: str,
        *,
        failed_resource_id: Optional[str] = None,
        subnet_ids: Optional[List[str]] = None,
    ) -> NetworkContext:
        """Build network context for a VPC.

        Args:
            region: AWS region.
            vpc_id: VPC to analyze.
            failed_resource_id: Optional resource to run impact analysis on.
            subnet_ids: Optional list of subnets to check reachability for.

        Returns:
            NetworkContext with anomalies, reachability, and impact data.
        """
        ctx = NetworkContext(vpc_id=vpc_id, region=region)

        if not self.collector or not self.graph_cls:
            ctx.summary = "Network context unavailable — topology modules not loaded."
            return ctx

        try:
            topo = self.collector.collect_vpc_topology(region, vpc_id)
            graph = self.graph_cls().build_from_vpc_topology(topo)
        except Exception as e:
            logger.error("Failed to build topology graph for %s: %s", vpc_id, e)
            ctx.summary = f"Failed to build topology graph: {e}"
            return ctx

        # Graph statistics
        ctx.raw_graph_stats = self._graph_stats(graph)

        # 1. Anomaly detection
        ctx.anomalies = self._detect_anomalies(graph)

        # 2. Reachability analysis
        if subnet_ids:
            ctx.reachability = self._check_reachability(graph, subnet_ids)
        else:
            # Auto-discover subnets from the graph
            ctx.reachability = self._check_all_subnets(graph)

        # 3. Impact analysis (if a failed resource is specified)
        if failed_resource_id:
            ctx.impact = self._analyze_impact(graph, failed_resource_id)

        # 4. Security group chains
        ctx.security_group_chains = self._extract_sg_chains(topo)

        # Build human-readable summary
        ctx.summary = self._build_summary(ctx)

        return ctx

    def enrich_from_telemetry(
        self,
        telemetry: Dict[str, Any],
        region: str,
        vpc_id: str,
    ) -> Dict[str, Any]:
        """Enrich existing telemetry dict with network context.

        Convenience method that enriches and injects in one call.
        Detects relevant subnet/resource IDs from telemetry events.

        Args:
            telemetry: Existing telemetry dict with events/metrics/logs.
            region: AWS region.
            vpc_id: VPC to analyze.

        Returns:
            The same telemetry dict with 'network_context' key added.
        """
        # Extract resource hints from events
        failed_resource = None
        subnet_ids: List[str] = []

        for event in telemetry.get("events", []):
            # Look for resource identifiers in event data
            involved = event.get("involvedObject", {})
            labels = involved.get("labels", {})

            # If event mentions a specific AWS resource
            msg = event.get("message", "")
            if "subnet-" in msg:
                import re

                subnet_match = re.findall(r"subnet-[a-f0-9]+", msg)
                subnet_ids.extend(subnet_match)
            if "nat-" in msg or "igw-" in msg:
                import re

                resource_match = re.findall(r"(nat|igw)-[a-f0-9]+", msg)
                if resource_match and not failed_resource:
                    failed_resource = resource_match[0]

        ctx = self.enrich(
            region=region,
            vpc_id=vpc_id,
            failed_resource_id=failed_resource,
            subnet_ids=subnet_ids if subnet_ids else None,
        )

        telemetry["network_context"] = ctx.to_dict()
        return telemetry

    # ── Internal methods ─────────────────────────────────────────────

    def _detect_anomalies(self, graph) -> List[Dict[str, Any]]:
        """Run anomaly detection on the graph."""
        try:
            from src.aci.topology.algorithms import detect_anomalies

            report = detect_anomalies(graph)
            return [a.model_dump() for a in report.anomalies]
        except Exception as e:
            logger.error("Anomaly detection failed: %s", e)
            return []

    def _check_reachability(
        self, graph, subnet_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """Check internet reachability for specific subnets."""
        try:
            from src.aci.topology.algorithms import can_reach_internet

            results = []
            for subnet_id in subnet_ids:
                result = can_reach_internet(graph, subnet_id)
                results.append(result.model_dump())
            return results
        except Exception as e:
            logger.error("Reachability check failed: %s", e)
            return []

    def _check_all_subnets(self, graph) -> List[Dict[str, Any]]:
        """Check reachability for all subnets in the graph."""
        try:
            from src.aci.topology.algorithms import can_reach_internet
            from src.aci.topology.types import NodeType

            g = graph.graph
            subnet_ids = [
                n
                for n, d in g.nodes(data=True)
                if d.get("node_type") == NodeType.SUBNET
            ]

            results = []
            for subnet_id in subnet_ids:
                result = can_reach_internet(graph, subnet_id)
                results.append(result.model_dump())
            return results
        except Exception as e:
            logger.error("All-subnet reachability check failed: %s", e)
            return []

    def _analyze_impact(
        self, graph, failed_resource_id: str
    ) -> Optional[Dict[str, Any]]:
        """Run impact analysis for a failed resource."""
        try:
            from src.aci.topology.algorithms import impact_analysis

            result = impact_analysis(graph, failed_resource_id)
            return result.model_dump()
        except Exception as e:
            logger.error("Impact analysis failed for %s: %s", failed_resource_id, e)
            return None

    def _extract_sg_chains(self, topo: Dict[str, Any]) -> Dict[str, List[str]]:
        """Extract security group dependency chains from VPC topology."""
        sg_map = topo.get("security_group_dependency_map", {})
        chains: Dict[str, List[str]] = {}
        for sg_id, info in sg_map.items():
            refs = info.get("references", [])
            if refs:
                chains[sg_id] = refs
        return chains

    def _graph_stats(self, graph) -> Dict[str, Any]:
        """Compute graph node/edge counts and type breakdown."""
        g = graph.graph
        node_types: Dict[str, int] = {}
        for _, data in g.nodes(data=True):
            nt = str(data.get("node_type", "unknown"))
            node_types[nt] = node_types.get(nt, 0) + 1

        edge_types: Dict[str, int] = {}
        for _, _, data in g.edges(data=True):
            et = str(data.get("edge_type", "unknown"))
            edge_types[et] = edge_types.get(et, 0) + 1

        return {
            "total_nodes": g.number_of_nodes(),
            "total_edges": g.number_of_edges(),
            "node_types": node_types,
            "edge_types": edge_types,
        }

    def _build_summary(self, ctx: NetworkContext) -> str:
        """Build human-readable summary for agent/LLM consumption."""
        parts = [f"Network context for VPC {ctx.vpc_id} in {ctx.region}:"]

        stats = ctx.raw_graph_stats
        parts.append(
            f"  Graph: {stats.get('total_nodes', 0)} nodes, "
            f"{stats.get('total_edges', 0)} edges"
        )

        # Anomalies
        if ctx.anomalies:
            critical = ctx.critical_anomalies
            parts.append(
                f"  Anomalies: {len(ctx.anomalies)} total"
                f" ({len(critical)} critical/high)"
            )
            for a in critical[:3]:
                parts.append(f"    - [{a['severity']}] {a['description']}")
        else:
            parts.append("  Anomalies: none detected")

        # Reachability
        unreachable = [
            r for r in ctx.reachability if not r.get("can_reach_internet", True)
        ]
        if unreachable:
            parts.append(
                f"  Reachability: {len(unreachable)}/{len(ctx.reachability)}"
                " subnets CANNOT reach internet"
            )
            for r in unreachable[:3]:
                parts.append(
                    f"    - {r['subnet_id']}: {r.get('blocking_reason', 'unknown')}"
                )
        elif ctx.reachability:
            parts.append(
                f"  Reachability: all {len(ctx.reachability)} subnets OK"
            )

        # Impact
        if ctx.impact:
            severity = ctx.impact.get("severity", "unknown")
            isolated = ctx.impact.get("isolated_subnets", [])
            affected = ctx.impact.get("affected_nodes", [])
            parts.append(
                f"  Impact analysis: severity={severity}, "
                f"{len(isolated)} isolated subnets, "
                f"{len(affected)} affected nodes"
            )

        # SG chains
        if ctx.security_group_chains:
            parts.append(
                f"  Security groups: {len(ctx.security_group_chains)} "
                "with cross-references"
            )

        return "\n".join(parts)
