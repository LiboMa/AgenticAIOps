"""
Tests for EventCorrelator — data models, collection, anomaly detection.

Covers:
- Data models: MetricDataPoint, AlarmInfo, TrailEvent, HealthEvent, CorrelatedEvent
- CorrelatedEvent: to_dict, to_rca_telemetry, summary
- EventCorrelator: collect (mocked), _detect_anomalies, _extract_changes
- _sync_collect_trail: retry logic (Bug-013)
- _sync_collect_metrics, _sync_collect_alarms, _sync_collect_health (mocked)
- Singleton: get_correlator
- quick_collect helper
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.event_correlator import (
    EventCorrelator,
    CorrelatedEvent,
    MetricDataPoint,
    AlarmInfo,
    TrailEvent,
    HealthEvent,
    get_correlator,
    quick_collect,
)


# =============================================================================
# Data Model Tests
# =============================================================================

class TestMetricDataPoint:

    def test_creation(self):
        m = MetricDataPoint(
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            resource_id="i-123",
            value=95.5,
            unit="Percent",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert m.namespace == "AWS/EC2"
        assert m.value == 95.5


class TestAlarmInfo:

    def test_creation(self):
        a = AlarmInfo(
            name="HighCPU",
            state="ALARM",
            metric_name="CPUUtilization",
            namespace="AWS/EC2",
            threshold=90.0,
            comparison=">=",
            resource_id="i-123",
        )
        assert a.state == "ALARM"
        assert a.threshold == 90.0


class TestTrailEvent:

    def test_creation(self):
        t = TrailEvent(
            event_name="RunInstances",
            event_source="ec2.amazonaws.com",
            username="admin",
            timestamp=datetime.now(timezone.utc).isoformat(),
            resource_type="AWS::EC2::Instance",
            resource_id="i-123",
            error_code="",
            error_message="",
            read_only=False,
        )
        assert t.event_name == "RunInstances"
        assert t.read_only is False


class TestHealthEvent:

    def test_creation(self):
        h = HealthEvent(
            service="EC2",
            event_type="issue",
            status="open",
            description="Instance connectivity issues",
            start_time=datetime.now(timezone.utc).isoformat(),
        )
        assert h.service == "EC2"
        assert h.status == "open"


# =============================================================================
# CorrelatedEvent Tests
# =============================================================================

class TestCorrelatedEvent:

    def _make_event(self, **overrides):
        return CorrelatedEvent(
            collection_id=overrides.get("collection_id", "col-test"),
            timestamp=overrides.get("timestamp", datetime.now(timezone.utc).isoformat()),
            duration_ms=overrides.get("duration_ms", 100),
            region=overrides.get("region", "ap-southeast-1"),
            metrics=overrides.get("metrics", [
                MetricDataPoint("AWS/EC2", "CPUUtilization", "i-123", 95.0, "Percent", "2026-01-01T00:00:00Z"),
            ]),
            alarms=overrides.get("alarms", [
                AlarmInfo("HighCPU", "ALARM", "CPUUtilization", "AWS/EC2", 90.0, ">=", "i-123"),
            ]),
            trail_events=overrides.get("trail_events", [
                TrailEvent("RunInstances", "ec2.amazonaws.com", "admin", "2026-01-01T00:00:00Z", "EC2", "i-123", "", "", False),
            ]),
            health_events=overrides.get("health_events", []),
            source_status=overrides.get("source_status", {"metrics": "ok", "alarms": "ok"}),
            anomalies=overrides.get("anomalies", [{"type": "cpu_spike", "value": 95}]),
            recent_changes=overrides.get("recent_changes", []),
        )

    def test_to_dict(self):
        event = self._make_event()
        d = event.to_dict()
        assert d["collection_id"] == "col-test"
        assert d["region"] == "ap-southeast-1"
        assert len(d["metrics"]) == 1
        assert len(d["alarms"]) == 1
        assert d["duration_ms"] == 100

    def test_to_rca_telemetry(self):
        event = self._make_event()
        t = event.to_rca_telemetry()
        assert "metrics" in t
        assert "events" in t
        assert "logs" in t

    def test_to_rca_telemetry_empty(self):
        event = self._make_event(
            metrics=[], alarms=[], trail_events=[], health_events=[], anomalies=[], recent_changes=[]
        )
        t = event.to_rca_telemetry()
        assert t["events"] == []
        assert t["metrics"] == {}
        assert t["logs"] == []

    def test_summary(self):
        event = self._make_event()
        s = event.summary()
        assert "ap-southeast-1" in s
        assert "100ms" in s
        assert "HighCPU" in s

    def test_summary_empty(self):
        event = self._make_event(
            metrics=[], alarms=[], trail_events=[], anomalies=[], recent_changes=[]
        )
        s = event.summary()
        assert "ap-southeast-1" in s
        assert "无活跃告警" in s


# =============================================================================
# EventCorrelator — _detect_anomalies
# =============================================================================

class TestDetectAnomalies:

    def _make_correlator(self):
        with patch("boto3.Session"):
            c = EventCorrelator.__new__(EventCorrelator)
            c.region = "ap-southeast-1"
        return c

    def test_cpu_spike_detected(self):
        correlator = self._make_correlator()
        metrics = [
            MetricDataPoint("AWS/EC2", "CPUUtilization", "i-123", 95.0, "Percent", "2026-01-01T00:00:00Z"),
        ]
        anomalies = correlator._detect_anomalies(metrics)
        assert len(anomalies) == 1
        assert anomalies[0]["metric"] == "CPUUtilization"
        assert anomalies[0]["severity"] == "critical"

    def test_cpu_warning(self):
        correlator = self._make_correlator()
        metrics = [
            MetricDataPoint("AWS/EC2", "CPUUtilization", "i-123", 75.0, "Percent", "2026-01-01T00:00:00Z"),
        ]
        anomalies = correlator._detect_anomalies(metrics)
        assert len(anomalies) == 1
        assert anomalies[0]["severity"] == "warning"

    def test_normal_cpu_no_anomaly(self):
        correlator = self._make_correlator()
        metrics = [
            MetricDataPoint("AWS/EC2", "CPUUtilization", "i-123", 50.0, "Percent", "2026-01-01T00:00:00Z"),
        ]
        anomalies = correlator._detect_anomalies(metrics)
        assert len(anomalies) == 0

    def test_empty_metrics_no_anomaly(self):
        correlator = self._make_correlator()
        anomalies = correlator._detect_anomalies([])
        assert anomalies == []

    def test_error_metric_detected(self):
        correlator = self._make_correlator()
        metrics = [
            MetricDataPoint("AWS/Lambda", "Errors", "my-func", 25.0, "Count", "2026-01-01T00:00:00Z"),
        ]
        anomalies = correlator._detect_anomalies(metrics)
        assert len(anomalies) == 1
        assert anomalies[0]["severity"] == "critical"

    def test_unknown_metric_ignored(self):
        correlator = self._make_correlator()
        metrics = [
            MetricDataPoint("AWS/EC2", "NetworkIn", "i-123", 999999.0, "Bytes", "2026-01-01T00:00:00Z"),
        ]
        anomalies = correlator._detect_anomalies(metrics)
        assert len(anomalies) == 0


# =============================================================================
# EventCorrelator — _extract_changes
# =============================================================================

class TestExtractChanges:

    def _make_correlator(self):
        with patch("boto3.Session"):
            c = EventCorrelator.__new__(EventCorrelator)
            c.region = "ap-southeast-1"
        return c

    def test_extract_significant_events(self):
        correlator = self._make_correlator()
        events = [
            TrailEvent("RunInstances", "ec2.amazonaws.com", "admin", "2026-01-01T00:00:00Z", "EC2", "i-123", "", "", False),
            TrailEvent("ModifyInstanceAttribute", "ec2.amazonaws.com", "admin", "2026-01-01T00:00:00Z", "EC2", "i-123", "", "", False),
        ]
        changes = correlator._extract_changes(events)
        assert len(changes) == 2
        assert changes[0]["event"] == "RunInstances"

    def test_extract_error_events(self):
        correlator = self._make_correlator()
        events = [
            TrailEvent("SomeRandomAPI", "ec2.amazonaws.com", "admin", "2026-01-01T00:00:00Z", "EC2", "i-123", "UnauthorizedAccess", "Access denied", True),
        ]
        changes = correlator._extract_changes(events)
        assert len(changes) == 1
        assert changes[0]["is_error"] is True
        assert changes[0]["error"] == "UnauthorizedAccess"

    def test_insignificant_event_ignored(self):
        correlator = self._make_correlator()
        events = [
            TrailEvent("DescribeInstances", "ec2.amazonaws.com", "admin", "2026-01-01T00:00:00Z", "", "", "", "", True),
        ]
        changes = correlator._extract_changes(events)
        assert len(changes) == 0

    def test_empty_events(self):
        correlator = self._make_correlator()
        changes = correlator._extract_changes([])
        assert changes == []


# =============================================================================
# EventCorrelator — collect (mocked)
# =============================================================================

class TestCollect:

    @pytest.mark.asyncio
    async def test_collect_basic(self):
        """collect() returns CorrelatedEvent with all sources."""
        with patch("boto3.Session"):
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MagicMock()

        metrics = [MetricDataPoint("AWS/EC2", "CPUUtilization", "i-123", 50.0, "Percent", "2026-01-01T00:00:00Z")]
        alarms = [AlarmInfo("Test", "OK", "CPU", "AWS/EC2", 90, ">=", "i-123")]
        trail = [TrailEvent("DescribeInstances", "ec2", "user", "2026-01-01T00:00:00Z", "", "", "", "", True)]
        health = []

        with patch.object(correlator, "_collect_metrics", new=AsyncMock(return_value=metrics)), \
             patch.object(correlator, "_collect_alarms", new=AsyncMock(return_value=alarms)), \
             patch.object(correlator, "_collect_trail_events", new=AsyncMock(return_value=trail)), \
             patch.object(correlator, "_collect_health_events", new=AsyncMock(return_value=health)), \
             patch.object(correlator, "_detect_anomalies", return_value=[]), \
             patch.object(correlator, "_extract_changes", return_value=[]):

            event = await correlator.collect()

        assert isinstance(event, CorrelatedEvent)
        assert len(event.metrics) == 1
        assert len(event.alarms) == 1
        assert event.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_collect_partial_failure(self):
        """One source fails, others still collected."""
        with patch("boto3.Session"):
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MagicMock()

        metrics = [MetricDataPoint("AWS/EC2", "CPUUtilization", "i-123", 50.0, "Percent", "2026-01-01T00:00:00Z")]

        with patch.object(correlator, "_collect_metrics", new=AsyncMock(return_value=metrics)), \
             patch.object(correlator, "_collect_alarms", new=AsyncMock(side_effect=Exception("alarm fail"))), \
             patch.object(correlator, "_collect_trail_events", new=AsyncMock(return_value=[])), \
             patch.object(correlator, "_collect_health_events", new=AsyncMock(return_value=[])), \
             patch.object(correlator, "_detect_anomalies", return_value=[]), \
             patch.object(correlator, "_extract_changes", return_value=[]):

            event = await correlator.collect()

        assert len(event.metrics) == 1
        assert "error" in event.source_status.get("alarms", "")


# =============================================================================
# _sync_collect_metrics / _sync_collect_alarms / _sync_collect_health (mocked)
# =============================================================================

class TestSyncCollectMetrics:

    def test_collect_ec2_metrics(self):
        """Collect EC2 CPU metric from mocked CloudWatch."""
        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_cw = MagicMock()
            correlator._session.client.return_value = mock_cw

            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [
                {"Metrics": [{"Dimensions": [{"Name": "InstanceId", "Value": "i-123"}]}]}
            ]
            mock_cw.get_paginator.return_value = mock_paginator
            mock_cw.get_metric_statistics.return_value = {
                "Datapoints": [
                    {"Average": 85.5, "Maximum": 92.0, "Timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                ]
            }

            metrics = correlator._sync_collect_metrics(["ec2"], 15)

        assert len(metrics) >= 1
        cpu_metrics = [m for m in metrics if m.metric_name == "CPUUtilization"]
        assert len(cpu_metrics) >= 1
        assert cpu_metrics[0].value == 85.5
        assert cpu_metrics[0].resource_id == "i-123"

    def test_collect_unknown_service_skipped(self):
        """Unknown service produces no metrics."""
        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_cw = MagicMock()
            correlator._session.client.return_value = mock_cw

            metrics = correlator._sync_collect_metrics(["unknown_service"], 15)

        assert metrics == []

    def test_collect_handles_client_error(self):
        """ClientError is caught gracefully."""
        from botocore.exceptions import ClientError

        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_cw = MagicMock()
            correlator._session.client.return_value = mock_cw

            mock_paginator = MagicMock()
            mock_paginator.paginate.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "No access"}},
                "ListMetrics"
            )
            mock_cw.get_paginator.return_value = mock_paginator

            metrics = correlator._sync_collect_metrics(["ec2"], 15)
            assert metrics == []

    def test_collect_empty_datapoints(self):
        """Metric with empty datapoints is skipped."""
        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_cw = MagicMock()
            correlator._session.client.return_value = mock_cw

            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [
                {"Metrics": [{"Dimensions": [{"Name": "InstanceId", "Value": "i-123"}]}]}
            ]
            mock_cw.get_paginator.return_value = mock_paginator
            mock_cw.get_metric_statistics.return_value = {"Datapoints": []}

            metrics = correlator._sync_collect_metrics(["ec2"], 15)
            assert metrics == []


class TestSyncCollectAlarms:

    def test_collect_firing_alarms(self):
        """Collect ALARM state alarms."""
        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_cw = MagicMock()
            correlator._session.client.return_value = mock_cw

            mock_paginator = MagicMock()
            # First paginate for ALARM, second for INSUFFICIENT_DATA
            mock_paginator.paginate.side_effect = [
                [{"MetricAlarms": [{
                    "AlarmName": "HighCPU",
                    "StateValue": "ALARM",
                    "MetricName": "CPUUtilization",
                    "Namespace": "AWS/EC2",
                    "Threshold": 90.0,
                    "ComparisonOperator": "GreaterThanThreshold",
                    "Dimensions": [{"Name": "InstanceId", "Value": "i-123"}],
                    "StateReason": "Threshold crossed",
                    "StateUpdatedTimestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
                }]}],
                [{"MetricAlarms": []}],  # No INSUFFICIENT_DATA
            ]
            mock_cw.get_paginator.return_value = mock_paginator

            alarms = correlator._sync_collect_alarms()

        assert len(alarms) == 1
        assert alarms[0].name == "HighCPU"
        assert alarms[0].state == "ALARM"
        assert alarms[0].resource_id == "i-123"

    def test_collect_alarms_client_error(self):
        """ClientError returns empty list."""
        from botocore.exceptions import ClientError

        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_cw = MagicMock()
            correlator._session.client.return_value = mock_cw

            mock_paginator = MagicMock()
            mock_paginator.paginate.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "No access"}},
                "DescribeAlarms"
            )
            mock_cw.get_paginator.return_value = mock_paginator

            alarms = correlator._sync_collect_alarms()
            assert alarms == []


class TestSyncCollectHealth:

    def test_collect_health_events(self):
        """Collect open health events."""
        with patch("boto3.Session"), \
             patch("boto3.client") as mock_client:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MagicMock()

            mock_health = MagicMock()
            mock_client.return_value = mock_health
            mock_health.describe_events.return_value = {
                "events": [{
                    "service": "EC2",
                    "eventTypeCode": "AWS_EC2_OPERATIONAL_ISSUE",
                    "statusCode": "open",
                    "eventTypeCategory": "issue",
                    "startTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
                }]
            }

            events = correlator._sync_collect_health()

        assert len(events) == 1
        assert events[0].service == "EC2"
        assert events[0].status == "open"

    def test_collect_health_api_unavailable(self):
        """Health API failure returns empty list."""
        from botocore.exceptions import ClientError

        with patch("boto3.Session"), \
             patch("boto3.client") as mock_client:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MagicMock()

            mock_client.side_effect = ClientError(
                {"Error": {"Code": "SubscriptionRequiredException", "Message": "Need Business support"}},
                "DescribeEvents"
            )

            events = correlator._sync_collect_health()
            assert events == []

class TestSyncCollectTrail:

    def test_success_first_attempt(self):
        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_ct = MagicMock()
            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [{"Events": []}]
            mock_ct.get_paginator.return_value = mock_paginator
            correlator._session.client.return_value = mock_ct

            events = correlator._sync_collect_trail(15)
            assert isinstance(events, list)

    def test_throttle_retry_success(self):
        """Throttle on first attempt, success on second."""
        from botocore.exceptions import ClientError

        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_ct = MagicMock()
            mock_paginator = MagicMock()

            # First call throttles, second succeeds
            throttle_error = ClientError(
                {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
                "LookupEvents"
            )
            mock_paginator.paginate.side_effect = [
                iter([throttle_error]),  # Won't work this way
            ]

            # Better approach: make paginate raise on first call, succeed on second
            call_count = [0]
            def paginate_side_effect(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise throttle_error
                return [{"Events": []}]

            mock_paginator.paginate = paginate_side_effect
            mock_ct.get_paginator.return_value = mock_paginator
            correlator._session.client.return_value = mock_ct

            with patch("time.sleep"):  # Don't actually sleep
                events = correlator._sync_collect_trail(15)

            assert isinstance(events, list)
            assert call_count[0] == 2  # Retried once

    def test_page_limit_respected(self):
        """Max 3 pages collected."""
        with patch("boto3.Session") as MockSession:
            correlator = EventCorrelator.__new__(EventCorrelator)
            correlator.region = "ap-southeast-1"
            correlator._session = MockSession()

            mock_ct = MagicMock()
            mock_paginator = MagicMock()
            # Return 5 pages
            pages = [{"Events": [{"EventName": f"Event{i}", "EventSource": "test", "Resources": []}]} for i in range(5)]
            mock_paginator.paginate.return_value = pages
            mock_ct.get_paginator.return_value = mock_paginator
            correlator._session.client.return_value = mock_ct

            events = correlator._sync_collect_trail(15)
            # Should only process max 3 pages
            assert len(events) <= 3


# =============================================================================
# Singleton + quick_collect
# =============================================================================

class TestSingleton:

    def test_get_correlator_singleton(self):
        import src.event_correlator as mod
        old = mod._correlator

        mod._correlator = None
        with patch("boto3.Session"):
            c1 = get_correlator()
            c2 = get_correlator()
        assert c1 is c2

        mod._correlator = old  # restore

    @pytest.mark.asyncio
    async def test_quick_collect(self):
        """quick_collect() delegates to correlator.collect()."""
        mock_event = MagicMock(spec=CorrelatedEvent)

        with patch("src.event_correlator.get_correlator") as mock_get:
            mock_correlator = MagicMock()
            mock_correlator.collect = AsyncMock(return_value=mock_event)
            mock_get.return_value = mock_correlator

            result = await quick_collect()

        assert result is mock_event
        mock_correlator.collect.assert_called_once()
