"""Tests for RCA Network Context Enrichment.

Covers:
- NetworkContext dataclass behavior
- NetworkContextEnricher with mocked topology modules
- Integration with RCAEngine.analyze_with_network_context()
- Edge cases (no topology, no anomalies, critical anomalies, etc.)
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from types import SimpleNamespace

from src.rca.network_context import NetworkContext, NetworkContextEnricher
from src.rca.engine import RCAEngine
from src.rca.models import RCAResult, Severity, Remediation


# ── NetworkContext unit tests ────────────────────────────────────────


class TestNetworkContext:
    """Tests for the NetworkContext dataclass."""

    def test_empty_context(self):
        ctx = NetworkContext()
        assert ctx.vpc_id == ""
        assert ctx.region == ""
        assert ctx.anomalies == []
        assert ctx.reachability == []
        assert ctx.impact is None
        assert ctx.security_group_chains == {}
        assert ctx.summary == ""
        assert not ctx.has_network_issues
        assert ctx.critical_anomalies == []

    def test_to_dict(self):
        ctx = NetworkContext(
            vpc_id="vpc-abc",
            region="us-east-1",
            anomalies=[{"severity": "high", "description": "orphan node"}],
            summary="test summary",
        )
        d = ctx.to_dict()
        assert d["vpc_id"] == "vpc-abc"
        assert d["region"] == "us-east-1"
        assert d["anomaly_count"] == 1
        assert d["summary"] == "test summary"
        assert d["anomalies"] == [{"severity": "high", "description": "orphan node"}]

    def test_has_network_issues_with_anomalies(self):
        ctx = NetworkContext(anomalies=[{"severity": "low", "type": "orphan"}])
        assert ctx.has_network_issues is True

    def test_has_network_issues_with_unreachable_subnet(self):
        ctx = NetworkContext(
            reachability=[
                {"subnet_id": "subnet-1", "can_reach_internet": True},
                {"subnet_id": "subnet-2", "can_reach_internet": False},
            ]
        )
        assert ctx.has_network_issues is True

    def test_no_network_issues(self):
        ctx = NetworkContext(
            reachability=[
                {"subnet_id": "subnet-1", "can_reach_internet": True},
            ]
        )
        assert ctx.has_network_issues is False

    def test_critical_anomalies_filter(self):
        ctx = NetworkContext(
            anomalies=[
                {"severity": "low", "description": "orphan node"},
                {"severity": "critical", "description": "routing cycle"},
                {"severity": "high", "description": "blackhole route"},
                {"severity": "medium", "description": "unhealthy node"},
            ]
        )
        critical = ctx.critical_anomalies
        assert len(critical) == 2
        assert critical[0]["severity"] == "critical"
        assert critical[1]["severity"] == "high"


# ── Mock topology helpers ────────────────────────────────────────────


def _make_mock_collector():
    """Create a mock collector that returns realistic VPC topology."""
    collector = SimpleNamespace()

    def collect_vpc_topology(region, vpc_id):
        return {
            "vpc_id": vpc_id,
            "vpc_cidr": "10.0.0.0/16",
            "vpc_name": "test-vpc",
            "region": region,
            "internet_gateways": [
                {
                    "igw_id": "igw-001",
                    "name": "main-igw",
                    "attachments": [{"state": "available", "vpc_id": vpc_id}],
                }
            ],
            "subnets": [
                {
                    "subnet_id": "subnet-pub1",
                    "name": "public-1",
                    "cidr": "10.0.1.0/24",
                    "az": "us-east-1a",
                    "available_ips": 250,
                    "type": "public",
                },
                {
                    "subnet_id": "subnet-priv1",
                    "name": "private-1",
                    "cidr": "10.0.2.0/24",
                    "az": "us-east-1a",
                    "available_ips": 250,
                    "type": "private",
                },
            ],
            "route_tables": [
                {
                    "route_table_id": "rtb-pub",
                    "name": "public-rt",
                    "associated_subnets": ["subnet-pub1"],
                    "routes": [
                        {"destination": "0.0.0.0/0", "target": "igw-001", "state": "active"},
                        {"destination": "10.0.0.0/16", "target": "local", "state": "active"},
                    ],
                },
                {
                    "route_table_id": "rtb-priv",
                    "name": "private-rt",
                    "associated_subnets": ["subnet-priv1"],
                    "routes": [
                        {"destination": "0.0.0.0/0", "target": "nat-001", "state": "active"},
                        {"destination": "10.0.0.0/16", "target": "local", "state": "active"},
                    ],
                },
            ],
            "nat_gateways": [
                {
                    "nat_gateway_id": "nat-001",
                    "name": "main-nat",
                    "state": "available",
                    "subnet_id": "subnet-pub1",
                }
            ],
            "transit_gateway_attachments": [],
            "vpc_peering_connections": [],
            "vpc_endpoints": [],
            "security_group_dependency_map": {
                "sg-web": {"name": "web-sg", "references": ["sg-app"]},
                "sg-app": {"name": "app-sg", "references": ["sg-db"]},
                "sg-db": {"name": "db-sg", "references": []},
            },
            "blackhole_routes": [],
        }

    collector.collect_vpc_topology = collect_vpc_topology
    collector.collect_region_topology = MagicMock(return_value={"region": "us-east-1", "vpcs": []})
    return collector


def _make_mock_graph_cls():
    """Create a mock InfraGraph class."""
    try:
        from src.aci.topology.engine import InfraGraph
        return InfraGraph
    except ImportError:
        # Fallback mock if topology module not importable
        mock_cls = MagicMock()
        instance = MagicMock()
        instance.build_from_vpc_topology.return_value = instance
        instance.graph.number_of_nodes.return_value = 10
        instance.graph.number_of_edges.return_value = 15
        instance.graph.nodes.return_value = []
        instance.graph.edges.return_value = []
        mock_cls.return_value = instance
        return mock_cls


# ── NetworkContextEnricher tests ─────────────────────────────────────


class TestNetworkContextEnricher:
    """Tests for NetworkContextEnricher."""

    def test_enrich_returns_context(self):
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)
        ctx = enricher.enrich(region="us-east-1", vpc_id="vpc-abc123")

        assert isinstance(ctx, NetworkContext)
        assert ctx.vpc_id == "vpc-abc123"
        assert ctx.region == "us-east-1"
        assert isinstance(ctx.raw_graph_stats, dict)
        assert "total_nodes" in ctx.raw_graph_stats

    def test_enrich_with_subnet_ids(self):
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)
        ctx = enricher.enrich(
            region="us-east-1",
            vpc_id="vpc-abc123",
            subnet_ids=["subnet-pub1", "subnet-priv1"],
        )
        assert isinstance(ctx.reachability, list)

    def test_enrich_with_failed_resource(self):
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)
        ctx = enricher.enrich(
            region="us-east-1",
            vpc_id="vpc-abc123",
            failed_resource_id="nat-001",
        )
        # Impact should be populated (or None if analysis fails gracefully)
        assert isinstance(ctx, NetworkContext)

    def test_enrich_extracts_sg_chains(self):
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)
        ctx = enricher.enrich(region="us-east-1", vpc_id="vpc-abc123")

        assert "sg-web" in ctx.security_group_chains
        assert ctx.security_group_chains["sg-web"] == ["sg-app"]
        assert "sg-app" in ctx.security_group_chains
        assert ctx.security_group_chains["sg-app"] == ["sg-db"]
        # sg-db has no references, so shouldn't appear
        assert "sg-db" not in ctx.security_group_chains

    def test_enrich_builds_summary(self):
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)
        ctx = enricher.enrich(region="us-east-1", vpc_id="vpc-abc123")

        assert "vpc-abc123" in ctx.summary
        assert "us-east-1" in ctx.summary

    def test_enrich_no_collector(self):
        """Should return graceful fallback when modules unavailable."""
        enricher = NetworkContextEnricher(collector=None, graph_cls=None)
        # Override lazy-load to return None
        enricher._collector = None
        enricher._graph_cls = None

        # Patch the property to simulate unavailable modules
        with patch.object(
            type(enricher), 'collector', new_callable=PropertyMock, return_value=None
        ):
            ctx = enricher.enrich(region="us-east-1", vpc_id="vpc-abc123")
            assert "unavailable" in ctx.summary.lower()

    def test_enrich_collector_error(self):
        """Should handle collector exceptions gracefully."""
        collector = SimpleNamespace()
        collector.collect_vpc_topology = MagicMock(
            side_effect=Exception("AWS timeout")
        )
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)
        ctx = enricher.enrich(region="us-east-1", vpc_id="vpc-abc123")

        assert "Failed" in ctx.summary
        assert ctx.anomalies == []

    def test_enrich_from_telemetry(self):
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)

        telemetry = {
            "events": [{"reason": "OOMKilled", "message": "Container killed"}],
            "metrics": {},
            "logs": [],
        }
        result = enricher.enrich_from_telemetry(
            telemetry, region="us-east-1", vpc_id="vpc-abc123"
        )
        assert "network_context" in result
        assert result["network_context"]["vpc_id"] == "vpc-abc123"

    def test_enrich_from_telemetry_extracts_subnet_ids(self):
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)

        telemetry = {
            "events": [
                {"message": "Connection timeout to subnet-abc123 from pod"},
            ],
            "metrics": {},
            "logs": [],
        }
        result = enricher.enrich_from_telemetry(
            telemetry, region="us-east-1", vpc_id="vpc-abc123"
        )
        assert "network_context" in result

    def test_graph_stats(self):
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)
        ctx = enricher.enrich(region="us-east-1", vpc_id="vpc-abc123")

        stats = ctx.raw_graph_stats
        assert "total_nodes" in stats
        assert "total_edges" in stats
        assert "node_types" in stats
        assert "edge_types" in stats


# ── RCAEngine integration tests ──────────────────────────────────────


class TestRCAEngineNetworkIntegration:
    """Tests for RCAEngine.analyze_with_network_context()."""

    def _make_engine_with_mocks(self):
        """Create an RCA engine with mocked dependencies."""
        collector = _make_mock_collector()
        graph_cls = _make_mock_graph_cls()
        enricher = NetworkContextEnricher(collector=collector, graph_cls=graph_cls)
        engine = RCAEngine(network_enricher=enricher)
        return engine

    def test_analyze_with_network_context_basic(self):
        engine = self._make_engine_with_mocks()
        telemetry = {
            "events": [{"reason": "OOMKilled", "message": "Container killed"}],
            "metrics": {},
            "logs": [],
        }
        result = engine.analyze_with_network_context(
            namespace="test-ns",
            region="us-east-1",
            vpc_id="vpc-abc123",
            telemetry=telemetry,
        )
        assert isinstance(result, RCAResult)
        # Should have network evidence in the result
        assert any("Network" in e or "network" in e for e in result.evidence)

    def test_analyze_with_network_context_no_telemetry(self):
        """Should collect telemetry when not provided."""
        engine = self._make_engine_with_mocks()
        # Mock ACI to avoid real calls
        engine._aci = MagicMock()
        engine._aci.get_events.return_value = MagicMock(
            status=MagicMock(value="success"), data=[]
        )
        engine._aci.get_metrics.return_value = MagicMock(
            status=MagicMock(value="success"), data={}
        )

        result = engine.analyze_with_network_context(
            namespace="test-ns",
            region="us-east-1",
            vpc_id="vpc-abc123",
        )
        assert isinstance(result, RCAResult)

    def test_analyze_with_failed_resource(self):
        engine = self._make_engine_with_mocks()
        telemetry = {
            "events": [{"reason": "NetworkFailure", "message": "Connection refused"}],
            "metrics": {},
            "logs": [],
        }
        result = engine.analyze_with_network_context(
            namespace="test-ns",
            region="us-east-1",
            vpc_id="vpc-abc123",
            telemetry=telemetry,
            failed_resource_id="nat-001",
        )
        assert isinstance(result, RCAResult)

    def test_analyze_with_subnet_ids(self):
        engine = self._make_engine_with_mocks()
        telemetry = {
            "events": [],
            "metrics": {},
            "logs": [],
        }
        result = engine.analyze_with_network_context(
            namespace="test-ns",
            region="us-east-1",
            vpc_id="vpc-abc123",
            telemetry=telemetry,
            subnet_ids=["subnet-pub1"],
        )
        assert isinstance(result, RCAResult)

    def test_enrich_result_no_network_issues(self):
        """When no network issues, should add 'no anomalies' evidence."""
        engine = self._make_engine_with_mocks()
        result = RCAResult(
            pattern_id="test",
            pattern_name="Test",
            root_cause="Application crash",
            severity=Severity.MEDIUM,
            confidence=0.9,
            matched_symptoms=["OOMKilled"],
            remediation=Remediation(action="restart"),
            evidence=["Event matched: OOMKilled"],
        )
        ctx = NetworkContext()  # Empty = no issues
        enriched = engine._enrich_result_with_network(result, ctx)
        assert any("no anomalies" in e for e in enriched.evidence)

    def test_enrich_result_with_critical_anomalies(self):
        """Critical anomalies should appear in evidence."""
        engine = self._make_engine_with_mocks()
        result = RCAResult(
            pattern_id="test",
            pattern_name="Test",
            root_cause="Unknown issue",
            severity=Severity.MEDIUM,
            confidence=0.5,
            matched_symptoms=[],
            remediation=Remediation(action="manual_review"),
            evidence=[],
        )
        ctx = NetworkContext(
            anomalies=[
                {
                    "severity": "critical",
                    "description": "Routing cycle detected: rtb-1 -> rtb-2",
                    "type": "routing_cycle",
                },
                {
                    "severity": "high",
                    "description": "Blackhole route in rtb-3",
                    "type": "blackhole_route",
                },
            ],
            summary="test summary",
        )
        enriched = engine._enrich_result_with_network(result, ctx)

        # Should have anomaly evidence
        assert any("routing cycle" in e.lower() for e in enriched.evidence)
        assert any("blackhole" in e.lower() for e in enriched.evidence)
        # Low confidence + critical anomaly => severity upgraded
        assert enriched.severity == Severity.HIGH
        # Root cause should be augmented
        assert "Network context" in enriched.root_cause

    def test_enrich_result_with_unreachable_subnets(self):
        engine = self._make_engine_with_mocks()
        result = RCAResult(
            pattern_id="test",
            pattern_name="Test",
            root_cause="Connection timeout",
            severity=Severity.MEDIUM,
            confidence=0.8,
            matched_symptoms=["timeout"],
            remediation=Remediation(action="check_network"),
            evidence=[],
        )
        ctx = NetworkContext(
            reachability=[
                {
                    "subnet_id": "subnet-priv1",
                    "can_reach_internet": False,
                    "blocking_reason": "No NAT gateway",
                },
            ],
            summary="1 subnet unreachable",
        )
        enriched = engine._enrich_result_with_network(result, ctx)
        assert any("subnet-priv1" in e for e in enriched.evidence)
        assert any("No NAT gateway" in e for e in enriched.evidence)

    def test_enrich_result_with_impact(self):
        engine = self._make_engine_with_mocks()
        result = RCAResult(
            pattern_id="test",
            pattern_name="Test",
            root_cause="NAT failure",
            severity=Severity.HIGH,
            confidence=0.9,
            matched_symptoms=["NAT"],
            remediation=Remediation(action="replace_nat"),
            evidence=[],
        )
        ctx = NetworkContext(
            anomalies=[{"severity": "high", "description": "NAT down"}],
            impact={
                "failed_node_id": "nat-001",
                "severity": "high",
                "isolated_subnets": ["subnet-priv1", "subnet-priv2"],
                "affected_nodes": [{"node_id": "rtb-priv"}],
            },
            summary="impact analysis",
        )
        enriched = engine._enrich_result_with_network(result, ctx)
        assert any("2 subnets isolated" in e for e in enriched.evidence)

    def test_network_enricher_lazy_loaded(self):
        """Engine should lazy-load the enricher."""
        engine = RCAEngine()
        enricher = engine.network_enricher
        assert isinstance(enricher, NetworkContextEnricher)

    def test_high_confidence_result_not_overridden(self):
        """High-confidence results should NOT have root cause overridden."""
        engine = self._make_engine_with_mocks()
        result = RCAResult(
            pattern_id="oom-001",
            pattern_name="OOMKilled",
            root_cause="Memory exhaustion — container killed by OOM killer",
            severity=Severity.MEDIUM,
            confidence=0.95,
            matched_symptoms=["OOMKilled"],
            remediation=Remediation(action="increase_memory"),
            evidence=["Event matched: OOMKilled"],
        )
        ctx = NetworkContext(
            anomalies=[
                {
                    "severity": "critical",
                    "description": "Routing cycle",
                    "type": "routing_cycle",
                },
            ],
            summary="routing cycle",
        )
        enriched = engine._enrich_result_with_network(result, ctx)
        # High confidence (0.95 >= 0.7) means root cause NOT overridden
        assert "Network context:" not in enriched.root_cause
        # But anomaly should still appear in evidence
        assert any("routing cycle" in e.lower() for e in enriched.evidence)
