"""Targeted tests for Datadog alert parser — uncovered lines 56-58, 77-79.

Covers:
- parse() when no _TRIGGERED_PATTERN matches but _MONITOR_PATTERN does (line 56-58)
- parse() when neither pattern matches → fallback title (line 56-58)
- parse() exception handling → returns None (line 77-79)
- can_parse() with "datadog" + "monitor" keyword combo
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.alert.parsers.datadog import DatadogAlertParser


@pytest.fixture
def parser():
    return DatadogAlertParser()


class TestDatadogParserCoverage:
    def test_parse_monitor_pattern_without_trigger(self, parser):
        """No [Triggered] prefix but has Monitor: line → uses monitor name."""
        msg = "Datadog alert\nMonitor: High Memory Usage on prod-db-01"
        alert = parser.parse(msg, channel_id="C123")
        assert alert is not None
        assert "High Memory Usage" in alert.title
        assert alert.severity == "medium"
        assert alert.channel_id == "C123"

    def test_parse_fallback_title_no_patterns(self, parser):
        """No trigger or monitor pattern → fallback 'Datadog Alert' title."""
        msg = "Datadog says something is wrong but format is unusual"
        alert = parser.parse(msg)
        assert alert is not None
        assert "Datadog Alert" in alert.title
        assert alert.severity == "medium"

    def test_parse_no_data_state(self, parser):
        """[No Data] state maps to medium severity."""
        alert = parser.parse("[No Data] Heartbeat monitor for web-02")
        assert alert is not None
        assert alert.severity == "medium"

    def test_parse_no_host_tag(self, parser):
        """No host: tag → empty resource_hint."""
        alert = parser.parse("[Triggered] High latency on API gateway")
        assert alert is not None
        assert alert.resource_hint == ""

    def test_parse_exception_returns_none(self, parser):
        """If StructuredAlert constructor raises, returns None."""
        with patch("src.alert.parsers.datadog.StructuredAlert", side_effect=Exception("boom")):
            result = parser.parse("[Triggered] test alert")
            assert result is None

    def test_can_parse_datadog_monitor_keyword(self, parser):
        """'datadog' + 'monitor' without 'triggered'."""
        assert parser.can_parse("Datadog monitor check: all good")
