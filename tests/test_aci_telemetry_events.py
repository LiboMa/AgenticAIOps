"""
ACI Telemetry Events Provider — Unit Tests
Covers: EventsProvider.get_events() + _parse_event()
Target: raise src/aci/telemetry/events.py coverage from 22% → 80%+
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from src.aci.telemetry.events import EventsProvider
from src.aci.models import ResultStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    return EventsProvider(cluster_name="test-cluster", region="us-east-1")


def _make_k8s_event(
    name: str = "my-pod",
    kind: str = "Pod",
    namespace: str = "default",
    event_type: str = "Warning",
    reason: str = "BackOff",
    message: str = "Back-off pulling image",
    count: int = 3,
    minutes_ago: int = 10,
):
    """Helper to build a minimal K8s event JSON item."""
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "metadata": {"namespace": namespace, "creationTimestamp": ts},
        "type": event_type,
        "reason": reason,
        "message": message,
        "count": count,
        "lastTimestamp": ts,
        "involvedObject": {"name": name, "kind": kind},
    }


def _kubectl_success(items):
    """Return a mock subprocess result with items."""
    return MagicMock(
        returncode=0,
        stdout=json.dumps({"items": items}),
        stderr="",
    )


def _kubectl_fail(stderr="error"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# Tests — get_events (happy path)
# ---------------------------------------------------------------------------

class TestEventsProviderGetEvents:

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_basic_get_events_all_namespaces(self, mock_run, provider):
        """All-namespaces query returns correct events."""
        items = [_make_k8s_event(), _make_k8s_event(event_type="Normal", reason="Pulled")]
        mock_run.return_value = _kubectl_success(items)

        result = provider.get_events(namespace="all")

        assert result.status == ResultStatus.SUCCESS
        assert result.metadata["total_events"] == 2
        assert result.metadata["namespace"] == "all"
        # Check --all-namespaces flag
        cmd = mock_run.call_args[0][0]
        assert "--all-namespaces" in cmd

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_get_events_specific_namespace(self, mock_run, provider):
        """Specific namespace adds -n flag."""
        mock_run.return_value = _kubectl_success([_make_k8s_event()])

        result = provider.get_events(namespace="kube-system")

        cmd = mock_run.call_args[0][0]
        assert "-n" in cmd
        assert "kube-system" in cmd
        assert result.status == ResultStatus.SUCCESS

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_filter_by_event_type(self, mock_run, provider):
        """Filter by event_type (Warning vs Normal)."""
        items = [
            _make_k8s_event(event_type="Warning"),
            _make_k8s_event(event_type="Normal", reason="Scheduled"),
        ]
        mock_run.return_value = _kubectl_success(items)

        result = provider.get_events(event_type="Warning")

        assert result.status == ResultStatus.SUCCESS
        assert result.metadata["warning_count"] == 1
        assert result.metadata["total_events"] == 1

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_filter_by_reason(self, mock_run, provider):
        """Filter events by reason substring."""
        items = [
            _make_k8s_event(reason="BackOff"),
            _make_k8s_event(reason="Pulled"),
        ]
        mock_run.return_value = _kubectl_success(items)

        result = provider.get_events(reason="BackOff")

        assert result.metadata["total_events"] == 1

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_filter_by_involved_object(self, mock_run, provider):
        """Filter events by involved object name."""
        items = [
            _make_k8s_event(name="nginx-pod"),
            _make_k8s_event(name="redis-pod"),
        ]
        mock_run.return_value = _kubectl_success(items)

        result = provider.get_events(involved_object="nginx")

        assert result.metadata["total_events"] == 1

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_duration_filter(self, mock_run, provider):
        """Old events are excluded by duration_minutes."""
        items = [
            _make_k8s_event(minutes_ago=5),   # within range
            _make_k8s_event(minutes_ago=120),  # too old
        ]
        mock_run.return_value = _kubectl_success(items)

        result = provider.get_events(duration_minutes=60)

        assert result.metadata["total_events"] == 1

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_limit(self, mock_run, provider):
        """Limit caps event count."""
        items = [_make_k8s_event(minutes_ago=i) for i in range(1, 6)]
        mock_run.return_value = _kubectl_success(items)

        result = provider.get_events(limit=2)

        assert result.metadata["total_events"] == 2

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_events_sorted_newest_first(self, mock_run, provider):
        """Events should be sorted newest-first."""
        items = [
            _make_k8s_event(minutes_ago=30),
            _make_k8s_event(minutes_ago=5),
            _make_k8s_event(minutes_ago=15),
        ]
        mock_run.return_value = _kubectl_success(items)

        result = provider.get_events()

        assert result.status == ResultStatus.SUCCESS
        timestamps = [d["timestamp"] for d in result.data]
        assert timestamps == sorted(timestamps, reverse=True)

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_warning_and_normal_counts(self, mock_run, provider):
        """Metadata correctly counts Warning vs Normal."""
        items = [
            _make_k8s_event(event_type="Warning"),
            _make_k8s_event(event_type="Warning"),
            _make_k8s_event(event_type="Normal"),
        ]
        mock_run.return_value = _kubectl_success(items)

        result = provider.get_events()

        assert result.metadata["warning_count"] == 2
        assert result.metadata["normal_count"] == 1

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_empty_items(self, mock_run, provider):
        """Empty items list returns success with zero events."""
        mock_run.return_value = _kubectl_success([])

        result = provider.get_events()

        assert result.status == ResultStatus.SUCCESS
        assert result.metadata["total_events"] == 0


# ---------------------------------------------------------------------------
# Tests — error paths
# ---------------------------------------------------------------------------

class TestEventsProviderErrors:

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_kubectl_failure(self, mock_run, provider):
        """Non-zero return code yields ERROR status."""
        mock_run.return_value = _kubectl_fail("connection refused")

        result = provider.get_events()

        assert result.status == ResultStatus.ERROR
        assert "connection refused" in result.error

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_kubectl_timeout(self, mock_run, provider):
        """subprocess.TimeoutExpired yields TIMEOUT status."""
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="kubectl", timeout=30)

        result = provider.get_events()

        assert result.status == ResultStatus.TIMEOUT

    @patch("src.aci.telemetry.events.subprocess.run")
    def test_invalid_json(self, mock_run, provider):
        """Invalid JSON stdout returns ERROR."""
        mock_run.return_value = MagicMock(returncode=0, stdout="not-json", stderr="")

        result = provider.get_events()

        assert result.status == ResultStatus.ERROR


# ---------------------------------------------------------------------------
# Tests — _parse_event
# ---------------------------------------------------------------------------

class TestParseEvent:

    def test_parse_valid_event(self, provider):
        item = _make_k8s_event()
        entry = provider._parse_event(item)

        assert entry is not None
        assert entry.reason == "BackOff"
        assert entry.namespace == "default"
        assert entry.involved_object == "my-pod"
        assert entry.involved_kind == "Pod"
        assert entry.count == 3

    def test_parse_event_with_eventTime(self, provider):
        """Use eventTime when lastTimestamp is absent."""
        item = _make_k8s_event()
        item.pop("lastTimestamp")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        item["eventTime"] = ts

        entry = provider._parse_event(item)

        assert entry is not None

    def test_parse_event_with_fractional_seconds(self, provider):
        """Handle timestamp with microseconds."""
        item = _make_k8s_event()
        item["lastTimestamp"] = "2026-02-25T03:00:00.123456Z"

        entry = provider._parse_event(item)

        assert entry is not None

    def test_parse_event_no_timestamp(self, provider):
        """Return None when no timestamp at all."""
        item = {
            "metadata": {},
            "type": "Warning",
            "reason": "Err",
            "involvedObject": {},
        }

        entry = provider._parse_event(item)

        assert entry is None

    def test_parse_event_missing_optional_fields(self, provider):
        """Missing optional fields get defaults."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        item = {
            "metadata": {"creationTimestamp": ts},
            "involvedObject": {},
        }

        entry = provider._parse_event(item)

        assert entry is not None
        assert entry.event_type == "Unknown"
        assert entry.reason == "Unknown"
        assert entry.message == ""
        assert entry.involved_object == "unknown"
        assert entry.count == 1

    def test_parse_event_malformed(self, provider):
        """Totally broken item returns None, no crash."""
        entry = provider._parse_event({"metadata": {"creationTimestamp": "not-a-date"}})

        assert entry is None
