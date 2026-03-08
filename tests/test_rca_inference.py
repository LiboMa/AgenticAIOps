"""
Tests for src/rca_inference.py — Bedrock Claude-powered RCA

Coverage target: 70%+ (from 35%)
"""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from types import SimpleNamespace

from src.rca.models import RCAResult, Severity, Remediation


# ── Fixtures ─────────────────────────────────────────────────────────

def _make_alarm(name="test-alarm", metric="CPUUtilization", state="ALARM",
                comparison="GreaterThanThreshold", threshold=90.0, resource_id="i-abc123"):
    return SimpleNamespace(
        name=name, metric_name=metric, state=state,
        comparison=comparison, threshold=threshold, resource_id=resource_id,
    )


def _make_correlated_event(
    alarms=None, anomalies=None, metrics=None,
    recent_changes=None, health_events=None,
    region="ap-southeast-1", duration_ms=1500,
):
    """Create a mock CorrelatedEvent."""
    ce = MagicMock()
    ce.alarms = alarms or []
    ce.anomalies = anomalies or []
    ce.metrics = metrics or []
    ce.recent_changes = recent_changes or []
    ce.health_events = health_events or []
    ce.region = region
    ce.duration_ms = duration_ms
    ce.source_status = {"cloudwatch": "ok", "cloudtrail": "ok"}
    ce.to_rca_telemetry.return_value = {
        "alarms": [{"name": a.name, "metric": a.metric_name} for a in (alarms or [])],
        "anomalies": anomalies or [],
    }
    return ce


def _make_claude_response(root_cause="High CPU", severity="high", confidence=0.85,
                          category="resource", service="ec2"):
    """Create a mock Claude JSON response."""
    return json.dumps({
        "root_cause": root_cause,
        "severity": severity,
        "confidence": confidence,
        "category": category,
        "affected_service": service,
        "affected_resources": ["i-abc123"],
        "evidence": ["CPU at 95%", "Recent deployment"],
        "remediation": {
            "action": "scale_up",
            "description": "Scale up the instance",
            "auto_executable": True,
            "risk_level": "L1",
            "steps": ["Check metrics", "Scale up"],
        },
        "related_patterns": [],
    })


# ── Test _build_analysis_prompt ──────────────────────────────────────

class TestBuildAnalysisPrompt:
    """Test prompt construction from correlated events."""

    def test_prompt_with_alarms(self):
        from src.rca_inference import _build_analysis_prompt
        ce = _make_correlated_event(alarms=[_make_alarm()])
        prompt = _build_analysis_prompt(ce)
        assert "Active Alarms" in prompt
        assert "test-alarm" in prompt
        assert "CPUUtilization" in prompt

    def test_prompt_with_anomalies(self):
        from src.rca_inference import _build_analysis_prompt
        ce = _make_correlated_event(anomalies=[{
            "resource": "i-abc", "metric": "cpu", "value": 95,
            "threshold": 80, "severity": "high",
        }])
        prompt = _build_analysis_prompt(ce)
        assert "Detected Anomalies" in prompt
        assert "i-abc" in prompt

    def test_prompt_with_metrics(self):
        from src.rca_inference import _build_analysis_prompt
        metric = SimpleNamespace(
            resource_id="i-abc", metric_name="CPUUtilization",
            value=95.0, unit="Percent",
        )
        ce = _make_correlated_event(metrics=[metric])
        prompt = _build_analysis_prompt(ce)
        assert "Key Metrics" in prompt
        assert "CPUUtilization" in prompt

    def test_prompt_with_recent_changes(self):
        from src.rca_inference import _build_analysis_prompt
        ce = _make_correlated_event(recent_changes=[{
            "event": "RunInstances", "user": "admin",
            "resource": "i-abc", "timestamp": "2026-02-13T10:00:00Z",
        }])
        prompt = _build_analysis_prompt(ce)
        assert "Recent Changes" in prompt
        assert "RunInstances" in prompt

    def test_prompt_with_error_in_changes(self):
        from src.rca_inference import _build_analysis_prompt
        ce = _make_correlated_event(recent_changes=[{
            "event": "TerminateInstances", "user": "admin",
            "error": "UnauthorizedAccess", "timestamp": "2026-02-13T10:00:00Z",
        }])
        prompt = _build_analysis_prompt(ce)
        assert "ERROR: UnauthorizedAccess" in prompt

    def test_prompt_with_health_events(self):
        from src.rca_inference import _build_analysis_prompt
        health = SimpleNamespace(service="EC2", event_type="issue", status="open")
        ce = _make_correlated_event(health_events=[health])
        prompt = _build_analysis_prompt(ce)
        assert "AWS Health Events" in prompt
        assert "EC2" in prompt

    def test_prompt_no_issues_note(self):
        from src.rca_inference import _build_analysis_prompt
        ce = _make_correlated_event()  # empty everything
        prompt = _build_analysis_prompt(ce)
        assert "No active issues detected" in prompt

    def test_prompt_collection_info(self):
        from src.rca_inference import _build_analysis_prompt
        ce = _make_correlated_event(region="us-east-1", duration_ms=2500)
        prompt = _build_analysis_prompt(ce)
        assert "us-east-1" in prompt
        assert "2500" in prompt

    def test_prompt_with_knowledge_context(self):
        from src.rca_inference import _build_analysis_prompt
        hit = SimpleNamespace(
            score=0.92, search_level="opensearch", title="CPU Spike Pattern",
            description="Known CPU spike from deployment", content="Details here",
            metadata={"remediation": "Scale up instance"},
        )
        knowledge = SimpleNamespace(hits=[hit], best_hit=hit)
        ce = _make_correlated_event()
        prompt = _build_analysis_prompt(ce, knowledge_context=knowledge)
        assert "Historical Patterns" in prompt
        assert "CPU Spike Pattern" in prompt
        assert "Scale up instance" in prompt

    def test_prompt_knowledge_no_content(self):
        from src.rca_inference import _build_analysis_prompt
        hit = SimpleNamespace(
            score=0.7, search_level="local", title="Pattern",
            description="desc", content=None, metadata={},
        )
        knowledge = SimpleNamespace(hits=[hit])
        ce = _make_correlated_event()
        prompt = _build_analysis_prompt(ce, knowledge_context=knowledge)
        assert "Historical Patterns" in prompt


# ── Test RCAInferenceEngine ──────────────────────────────────────────

class TestRCAInferenceEngine:
    """Test the RCA inference engine."""

    def test_init(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()
        assert engine.pattern_matcher is not None
        assert engine._bedrock_client is None

    @pytest.mark.asyncio
    async def test_pattern_match_high_confidence_skips_claude(self):
        from src.rca_inference import RCAInferenceEngine

        engine = RCAInferenceEngine()
        mock_result = RCAResult(
            pattern_id="cpu-001", pattern_name="High CPU",
            root_cause="CPU overload", severity=Severity.HIGH,
            confidence=0.9, matched_symptoms=["high_cpu"],
            remediation=Remediation(action="scale_up"),
        )

        with patch.object(engine.pattern_matcher, 'match', return_value=mock_result):
            ce = _make_correlated_event(alarms=[_make_alarm()])
            result = await engine.analyze(ce)

        assert result.pattern_id == "cpu-001"
        assert result.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_force_llm_skips_pattern_matching(self):
        from src.rca_inference import RCAInferenceEngine

        engine = RCAInferenceEngine()

        claude_response = _make_claude_response()
        mock_bedrock_response = {
            'body': MagicMock(read=MagicMock(return_value=json.dumps({
                'content': [{'text': claude_response}],
            }).encode()))
        }

        with patch.object(engine.pattern_matcher, 'match') as mock_match, \
             patch.object(engine, '_bedrock_client', create=True) as mock_client, \
             patch('src.knowledge_search.get_knowledge_search', side_effect=ImportError("skip")):
            mock_client.invoke_model.return_value = mock_bedrock_response
            engine._bedrock_client = mock_client

            ce = _make_correlated_event(alarms=[_make_alarm()])
            result = await engine.analyze(ce, force_llm=True)

        mock_match.assert_not_called()
        assert result is not None
        assert result.root_cause == "High CPU"

    @pytest.mark.asyncio
    async def test_no_issue_result(self):
        from src.rca_inference import RCAInferenceEngine

        engine = RCAInferenceEngine()

        with patch.object(engine.pattern_matcher, 'match', return_value=None), \
             patch.object(engine, '_invoke_claude', return_value=None), \
             patch('src.knowledge_search.get_knowledge_search', side_effect=ImportError("skip")):
            engine._bedrock_client = MagicMock()

            ce = _make_correlated_event()
            result = await engine.analyze(ce)

        assert result.pattern_id == "healthy"
        assert result.severity == Severity.LOW
        assert "No active issues" in result.root_cause


class TestParseClaudeResponse:
    """Test Claude response parsing."""

    def test_parse_valid_json(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        response = _make_claude_response()
        result = engine._parse_claude_response(response, "apac.anthropic.claude-sonnet-4")

        assert result is not None
        assert result.root_cause == "High CPU"
        assert result.severity == Severity.HIGH
        assert result.confidence == 0.85
        assert "llm-sonnet" in result.pattern_id
        assert result.remediation.action == "scale_up"
        assert result.remediation.auto_execute is True
        assert len(result.evidence) == 2

    def test_parse_markdown_wrapped_json(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        wrapped = f"Here is my analysis:\n```json\n{_make_claude_response()}\n```"
        result = engine._parse_claude_response(wrapped, "global.anthropic.claude-opus-4-6-v1")

        assert result is not None
        assert "llm-opus" in result.pattern_id

    def test_parse_no_json(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        result = engine._parse_claude_response("I cannot analyze this.", "test-model")
        assert result is None

    def test_parse_invalid_json(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        result = engine._parse_claude_response("{invalid json}", "test-model")
        assert result is None

    def test_parse_low_severity(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        response = _make_claude_response(severity="low", confidence=0.5)
        result = engine._parse_claude_response(response, "test-model")
        assert result.severity == Severity.LOW
        assert result.confidence == 0.5

    def test_parse_medium_severity(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        response = _make_claude_response(severity="medium")
        result = engine._parse_claude_response(response, "test-model")
        assert result.severity == Severity.MEDIUM

    def test_parse_confidence_clamped(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        response = _make_claude_response(confidence=1.5)
        result = engine._parse_claude_response(response, "test-model")
        assert result.confidence == 1.0

        response = _make_claude_response(confidence=-0.5)
        result = engine._parse_claude_response(response, "test-model")
        assert result.confidence == 0.0

    def test_parse_unknown_severity_defaults_to_medium(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        response = _make_claude_response(severity="critical")
        result = engine._parse_claude_response(response, "test-model")
        assert result.severity == Severity.MEDIUM


class TestInvokeClaude:
    """Test Bedrock Claude invocation."""

    def test_invoke_success(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        claude_response = _make_claude_response()
        mock_response = {
            'body': MagicMock(read=MagicMock(return_value=json.dumps({
                'content': [{'text': claude_response}],
            }).encode()))
        }

        engine._bedrock_client = MagicMock()
        engine._bedrock_client.invoke_model.return_value = mock_response

        result = engine._invoke_claude("test prompt", "test-model")
        assert result is not None
        assert result.root_cause == "High CPU"

    def test_invoke_exception_returns_none(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()

        engine._bedrock_client = MagicMock()
        engine._bedrock_client.invoke_model.side_effect = Exception("Bedrock error")

        result = engine._invoke_claude("test prompt", "test-model")
        assert result is None


class TestNoIssueResult:
    """Test the no-issue fallback result."""

    def test_no_issue_result_structure(self):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()
        ce = _make_correlated_event(
            alarms=[_make_alarm(state="OK")],
            anomalies=[{"x": 1}, {"x": 2}],
        )
        result = engine._no_issue_result(ce)

        assert result.pattern_id == "healthy"
        assert result.severity == Severity.LOW
        assert result.confidence == 0.9
        assert "No action needed" in result.remediation.suggestion
        assert any("Alarms firing: 0" in e for e in result.evidence)
        assert any("Anomalies: 2" in e for e in result.evidence)


class TestSingleton:
    """Test the module-level singleton."""

    def test_get_rca_inference_engine(self):
        from src.rca_inference import get_rca_inference_engine
        import src.rca_inference as mod
        mod._engine = None  # reset
        engine = get_rca_inference_engine()
        assert engine is not None
        # Second call returns same instance
        assert get_rca_inference_engine() is engine
        mod._engine = None  # cleanup
