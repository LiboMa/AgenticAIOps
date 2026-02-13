"""
Tests for src/intent_classifier.py — Query intent classification

Coverage target: 80%+ (from 0%)
"""

import pytest
from src.intent_classifier import (
    classify_intent, get_tools_for_intent, get_intent_description,
    filter_tools_by_intent, analyze_query, INTENT_CATEGORIES,
)


class TestClassifyIntent:
    """Test intent classification from queries."""

    def test_diagnose_intent_english(self):
        intent, conf = classify_intent("What's the issue with my pod?")
        assert intent == "diagnose"
        assert conf > 0

    def test_diagnose_intent_crash(self):
        intent, _ = classify_intent("My pod is crashing")
        assert intent == "diagnose"

    def test_diagnose_intent_oom(self):
        intent, _ = classify_intent("Pod OOM killed and restart")
        assert intent == "diagnose"

    def test_diagnose_intent_chinese(self):
        intent, _ = classify_intent("这个pod有什么问题？")
        assert intent == "diagnose"

    def test_monitor_intent(self):
        intent, _ = classify_intent("Check the health status of the cluster")
        assert intent == "monitor"

    def test_monitor_intent_chinese(self):
        intent, _ = classify_intent("检查集群状态")
        assert intent == "monitor"

    def test_scale_intent(self):
        intent, _ = classify_intent("Scale the deployment to 5 replicas")
        assert intent == "scale"

    def test_scale_intent_chinese(self):
        intent, _ = classify_intent("扩容到4个副本")
        assert intent == "scale"

    def test_info_intent(self):
        intent, _ = classify_intent("List all deployments")
        assert intent == "info"

    def test_info_intent_version(self):
        intent, _ = classify_intent("What version is running?")
        assert intent == "info"

    def test_recover_intent(self):
        intent, _ = classify_intent("Restart the pod and rollback deployment")
        assert intent == "recover"

    def test_recover_intent_chinese(self):
        intent, _ = classify_intent("恢复服务并回滚")
        assert intent == "recover"

    def test_unknown_query_defaults_to_info(self):
        intent, conf = classify_intent("xyzzy foobar gibberish")
        assert intent == "info"
        assert conf == 0.0

    def test_empty_query(self):
        intent, conf = classify_intent("")
        assert intent == "info"
        assert conf == 0.0

    def test_confidence_increases_with_matches(self):
        _, conf_one = classify_intent("error")
        _, conf_multi = classify_intent("error crash fail problem")
        assert conf_multi >= conf_one

    def test_confidence_capped_at_1(self):
        _, conf = classify_intent("error crash fail problem issue wrong restart oom backoff pending")
        assert conf <= 1.0

    def test_case_insensitive(self):
        intent, _ = classify_intent("SCALE REPLICAS")
        assert intent == "scale"


class TestGetToolsForIntent:
    """Test tool recommendation."""

    def test_diagnose_tools(self):
        tools = get_tools_for_intent("diagnose")
        assert "get_pods" in tools
        assert "get_pod_logs" in tools

    def test_monitor_tools(self):
        tools = get_tools_for_intent("monitor")
        assert "get_cluster_health" in tools

    def test_scale_tools(self):
        tools = get_tools_for_intent("scale")
        assert "scale_deployment" in tools

    def test_unknown_intent_returns_empty(self):
        tools = get_tools_for_intent("nonexistent")
        assert tools == []


class TestGetIntentDescription:
    """Test intent descriptions."""

    def test_known_intent(self):
        desc = get_intent_description("diagnose")
        assert "Diagnose" in desc or "troubleshoot" in desc

    def test_unknown_intent(self):
        desc = get_intent_description("nonexistent")
        assert desc == "Unknown intent"


class TestFilterToolsByIntent:
    """Test tool filtering."""

    def test_filter_with_matching_tools(self):
        class FakeTool:
            def __init__(self, name):
                self.__name__ = name

        tools = [FakeTool("get_pods"), FakeTool("get_pod_logs"), FakeTool("delete_everything")]
        filtered = filter_tools_by_intent(tools, "diagnose")
        names = [t.__name__ for t in filtered]
        assert "get_pods" in names
        assert "get_pod_logs" in names
        assert "delete_everything" not in names

    def test_filter_unknown_intent_returns_all(self):
        tools = ["a", "b", "c"]
        filtered = filter_tools_by_intent(tools, "nonexistent")
        assert filtered == tools


class TestAnalyzeQuery:
    """Test full query analysis."""

    def test_analyze_returns_all_fields(self):
        result = analyze_query("Check pod health status")
        assert "query" in result
        assert "intent" in result
        assert "confidence" in result
        assert "description" in result
        assert "recommended_tools" in result
        assert result["query"] == "Check pod health status"
        assert isinstance(result["recommended_tools"], list)

    def test_analyze_diagnose_query(self):
        result = analyze_query("Why is my pod crashing with OOM?")
        assert result["intent"] == "diagnose"
        assert result["confidence"] > 0

    def test_analyze_empty_query(self):
        result = analyze_query("")
        assert result["intent"] == "info"
        assert result["confidence"] == 0.0
