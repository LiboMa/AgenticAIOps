"""Tests for intent_classifier — keyword matching, tool lookup, query analysis."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.intent_classifier import (
    classify_intent,
    get_tools_for_intent,
    get_intent_description,
    filter_tools_by_intent,
    analyze_query,
    INTENT_CATEGORIES,
)


class TestClassifyIntent:

    def test_diagnose_intent(self):
        intent, conf = classify_intent("Why is my pod crashing?")
        assert intent == "diagnose"
        assert conf > 0

    def test_monitor_intent(self):
        intent, conf = classify_intent("Check the health status of the cluster")
        assert intent == "monitor"
        assert conf > 0

    def test_scale_intent(self):
        intent, conf = classify_intent("Scale the replica count to 5")
        assert intent == "scale"
        assert conf > 0

    def test_info_intent(self):
        intent, conf = classify_intent("List all deployments")
        assert intent == "info"
        assert conf > 0

    def test_recover_intent(self):
        intent, conf = classify_intent("Rollback and restore the service")
        assert intent == "recover"
        assert conf > 0

    def test_no_match_defaults_info(self):
        intent, conf = classify_intent("xyzzy gibberish 12345")
        assert intent == "info"
        assert conf == 0.0

    def test_chinese_diagnose(self):
        intent, conf = classify_intent("这个服务有什么问题？")
        assert intent == "diagnose"

    def test_chinese_scale(self):
        intent, conf = classify_intent("扩容到4个副本")
        assert intent == "scale"

    def test_confidence_capped_at_1(self):
        # Many keywords → confidence should cap at 1.0
        _, conf = classify_intent("error fail crash wrong problem issue why pending")
        assert conf <= 1.0


class TestGetTools:

    def test_known_intent(self):
        tools = get_tools_for_intent("diagnose")
        assert "get_pods" in tools

    def test_unknown_intent(self):
        tools = get_tools_for_intent("nonexistent")
        assert tools == []


class TestGetDescription:

    def test_known(self):
        desc = get_intent_description("monitor")
        assert "monitor" in desc.lower() or "Monitor" in desc

    def test_unknown(self):
        desc = get_intent_description("nonexistent")
        assert "Unknown" in desc


class TestFilterTools:

    def test_filter_by_intent(self):
        class FakeTool:
            def __init__(self, name):
                self.__name__ = name

        tools = [FakeTool("get_pods"), FakeTool("get_nodes"), FakeTool("delete_all")]
        filtered = filter_tools_by_intent(tools, "diagnose")
        names = [t.__name__ for t in filtered]
        assert "get_pods" in names
        assert "delete_all" not in names

    def test_no_recommendations_returns_all(self):
        tools = ["a", "b", "c"]
        filtered = filter_tools_by_intent(tools, "nonexistent")
        assert filtered == tools


class TestAnalyzeQuery:

    def test_returns_full_dict(self):
        result = analyze_query("Check cluster health")
        assert "intent" in result
        assert "confidence" in result
        assert "description" in result
        assert "recommended_tools" in result
        assert result["query"] == "Check cluster health"
