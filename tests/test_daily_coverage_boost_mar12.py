"""
Daily Coverage Boost — March 12, 2026

Targets the 3 lowest-coverage modules:
1. src/config.py (60% → target 90%+)
2. src/skills/iteration/spec_builder.py (69% → target 90%+)
3. src/rca/pattern_matcher.py (72% → target 85%+)
"""

import os
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path


# ===========================================================================
# 1. src/config.py — Cover the __main__ block (lines 72-81)
# ===========================================================================

class TestConfigMainBlock:
    """Cover the __main__ print block in config.py."""

    def test_config_main_block_runs(self, capsys):
        """Execute the __main__ guard block via runpy."""
        import runpy
        runpy.run_module("src.config", run_name="__main__")
        captured = capsys.readouterr()
        assert "AgenticAIOps Configuration" in captured.out
        assert "Default Model:" in captured.out
        assert "Available Models:" in captured.out
        assert "Cluster:" in captured.out
        assert "Region:" in captured.out

    def test_get_model_id_apac_passthrough(self):
        """Cover the apac prefix passthrough branch."""
        from src.config import get_model_id
        apac_id = "apac.anthropic.claude-3-haiku-20240307-v1:0"
        assert get_model_id(apac_id) == apac_id

    def test_get_model_id_unknown_falls_back_to_haiku(self):
        """Unknown model name falls back to haiku."""
        from src.config import get_model_id, AVAILABLE_MODELS
        result = get_model_id("nonexistent-model")
        assert result == AVAILABLE_MODELS["haiku"]

    def test_get_model_id_none_uses_default(self):
        """None uses DEFAULT_MODEL."""
        from src.config import get_model_id
        result = get_model_id(None)
        assert result  # should return a valid model ID

    def test_config_env_overrides(self):
        """Verify environment variables override defaults."""
        with patch.dict(os.environ, {"AGENT_MODEL": "sonnet"}):
            import importlib
            import src.config as cfg
            importlib.reload(cfg)
            assert cfg.DEFAULT_MODEL == "sonnet"
            # Restore
            importlib.reload(cfg)


# ===========================================================================
# 2. src/skills/iteration/spec_builder.py — Cover build_and_invoke branches
# ===========================================================================

class TestSpecBuilderBuildAndInvoke:
    """Cover async build_and_invoke and helper methods."""

    def _make_gap(self):
        from src.skills.iteration.gap_detector import SkillGap
        return SkillGap(
            gap_type="novel_tool_usage",
            incident_id="inc-test",
            uncovered_commands=["db_failover"],
            suggested_skill_domain="database_ha",
        )

    def test_build_and_invoke_no_invoker_returns_task(self):
        """When no harness_invoker, returns the task itself."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        builder = SkillSpecBuilder()
        gap = self._make_gap()
        result = asyncio.get_event_loop().run_until_complete(
            builder.build_and_invoke(gap, incident=None, harness_invoker=None)
        )
        assert result is not None
        assert hasattr(result, "task")
        assert "database_ha" in result.output_dir

    def test_build_and_invoke_success(self):
        """When harness_invoker succeeds, return its result."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        builder = SkillSpecBuilder()
        gap = self._make_gap()

        async def mock_invoker(task):
            return {"status": "ok", "files": ["SKILL.md"]}

        result = asyncio.get_event_loop().run_until_complete(
            builder.build_and_invoke(gap, incident=None, harness_invoker=mock_invoker)
        )
        assert result == {"status": "ok", "files": ["SKILL.md"]}

    def test_build_and_invoke_exception_returns_none(self):
        """When harness_invoker raises, returns None."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        builder = SkillSpecBuilder()
        gap = self._make_gap()

        async def failing_invoker(task):
            raise RuntimeError("Harness timeout")

        result = asyncio.get_event_loop().run_until_complete(
            builder.build_and_invoke(gap, incident=None, harness_invoker=failing_invoker)
        )
        assert result is None

    def test_summarize_incident_none(self):
        """_summarize_incident with None returns 'N/A'."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        builder = SkillSpecBuilder()
        assert builder._summarize_incident(None) == "N/A"

    def test_summarize_incident_with_to_dict(self):
        """_summarize_incident with object that has to_dict()."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        builder = SkillSpecBuilder()
        mock_inc = MagicMock()
        mock_inc.to_dict.return_value = {
            "incident_id": "INC-001",
            "service": "api-gateway",
            "alert_type": "HighLatency",
        }
        result = builder._summarize_incident(mock_inc)
        assert "INC-001" in result
        assert "api-gateway" in result

    def test_summarize_incident_plain_string(self):
        """_summarize_incident with plain object falls back to str()."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        builder = SkillSpecBuilder()
        result = builder._summarize_incident("some incident text")
        assert result == "some incident text"

    def test_list_existing_skills_with_registry(self):
        """_list_existing_skills with a registry."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        mock_registry = MagicMock()
        mock_registry.skills = {"kubernetes": {}, "linux_admin": {}}
        builder = SkillSpecBuilder(skill_registry=mock_registry)
        result = builder._list_existing_skills()
        assert "kubernetes" in result
        assert "linux_admin" in result

    def test_list_existing_skills_no_registry(self):
        """_list_existing_skills without registry returns default list."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        builder = SkillSpecBuilder()
        result = builder._list_existing_skills()
        assert "kubernetes" in result

    def test_build_task_with_incident(self):
        """build_task populates prompt with incident context."""
        from src.skills.iteration.spec_builder import SkillSpecBuilder
        builder = SkillSpecBuilder()
        gap = self._make_gap()
        mock_inc = MagicMock()
        mock_inc.to_dict.return_value = {"incident_id": "INC-002", "service": "db", "alert_type": "OOM"}
        task = builder.build_task(gap, incident=mock_inc)
        assert "INC-002" in task.task
        assert "database_ha" in task.output_dir


# ===========================================================================
# 3. src/rca/pattern_matcher.py — Cover uncovered branches
# ===========================================================================

class TestPatternMatcherEdgeCases:
    """Cover uncovered branches in PatternMatcher."""

    def _make_matcher_from_config(self, config_data):
        """Create a PatternMatcher with in-memory config."""
        import tempfile
        import yaml
        from src.rca.pattern_matcher import PatternMatcher

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            f.flush()
            matcher = PatternMatcher(config_path=f.name)
        os.unlink(f.name)
        return matcher

    def test_init_missing_config(self):
        """PatternMatcher with non-existent config loads no patterns."""
        from src.rca.pattern_matcher import PatternMatcher
        matcher = PatternMatcher(config_path="/nonexistent/path.yaml")
        assert len(matcher.patterns) == 0

    def test_load_patterns_invalid_yaml(self):
        """PatternMatcher handles malformed YAML gracefully."""
        import tempfile
        from src.rca.pattern_matcher import PatternMatcher
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("{{{invalid yaml")
            f.flush()
            matcher = PatternMatcher(config_path=f.name)
        os.unlink(f.name)
        assert len(matcher.patterns) == 0

    def test_parse_pattern_missing_required_field(self):
        """Pattern missing 'id' or 'root_cause' is skipped."""
        config = {
            "patterns": [
                {
                    "name": "test-bad",
                    # missing 'id' and 'root_cause'
                    "symptoms": {"events": []},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        assert len(matcher.patterns) == 0

    def test_parse_pattern_with_logs_string(self):
        """Logs symptoms as plain strings are parsed."""
        config = {
            "patterns": [
                {
                    "id": "test-log-str",
                    "name": "Log String Pattern",
                    "root_cause": "Bad log",
                    "severity": "low",
                    "symptoms": {
                        "logs": ["error.*timeout", "connection refused"]
                    },
                    "remediation": {"action": "manual_review"},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        assert len(matcher.patterns) == 1
        log_symptoms = [s for s in matcher.patterns[0].symptoms if s.source == 'logs']
        assert len(log_symptoms) == 2

    def test_match_event_reason(self):
        """_match_event with field='reason'."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='events', field='reason', value='OOMKilled')
        event = {'reason': 'OOMKilled', 'message': 'container killed'}
        assert matcher._match_event(symptom, event) is True

    def test_match_event_type(self):
        """_match_event with field='type'."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='events', field='type', value='Warning')
        event = {'type': 'Warning', 'reason': 'BackOff'}
        assert matcher._match_event(symptom, event) is True

    def test_match_event_message(self):
        """_match_event with field='message'."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='events', field='message', value='back-off')
        event = {'message': 'Back-off restarting failed container'}
        assert matcher._match_event(symptom, event) is True

    def test_match_event_value_generic(self):
        """_match_event with field='value' does generic match."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='events', field='value', value='crashloop')
        event = {'reason': 'CrashLoopBackOff', 'message': 'restarting'}
        assert matcher._match_event(symptom, event) is True

    def test_match_event_unknown_field_returns_false(self):
        """_match_event with unknown field returns False."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='events', field='unknown_field', value='x')
        event = {'reason': 'X'}
        assert matcher._match_event(symptom, event) is False

    def test_match_metric_exists(self):
        """_match_metric when metric exists without condition."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='metrics', field='cpu_usage', value='cpu_usage')
        metrics = {'cpu_usage': 85.5}
        assert matcher._match_metric(symptom, metrics) is True

    def test_match_metric_not_exists(self):
        """_match_metric when metric doesn't exist."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='metrics', field='gpu_usage', value='gpu_usage')
        metrics = {'cpu_usage': 85.5}
        assert matcher._match_metric(symptom, metrics) is False

    def test_match_metric_gt_condition(self):
        """_match_metric with '> 80' condition."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='metrics', field='cpu_usage', value='cpu_usage', condition='> 80')
        assert matcher._match_metric(symptom, {'cpu_usage': 90}) is True
        assert matcher._match_metric(symptom, {'cpu_usage': 70}) is False

    def test_match_metric_lt_condition(self):
        """_match_metric with '< 10' condition."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='metrics', field='free_mem', value='free_mem', condition='< 10')
        assert matcher._match_metric(symptom, {'free_mem': 5}) is True
        assert matcher._match_metric(symptom, {'free_mem': 15}) is False

    def test_match_metric_eq_condition(self):
        """_match_metric with '== ready' condition."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='metrics', field='status', value='status', condition='== ready')
        assert matcher._match_metric(symptom, {'status': 'ready'}) is True

    def test_match_metric_invalid_condition(self):
        """_match_metric with unparseable condition still returns True (metric exists)."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='metrics', field='x', value='x', condition='> not_a_number')
        assert matcher._match_metric(symptom, {'x': 50}) is True

    def test_match_log_regex(self):
        """_match_log with regex pattern."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='logs', field='pattern', value=r'error.*timeout')
        assert matcher._match_log(symptom, "2026-03-12 error: connection timeout") is True

    def test_match_log_invalid_regex_falls_back(self):
        """_match_log with invalid regex falls back to substring match."""
        from src.rca.pattern_matcher import PatternMatcher
        from src.rca.models import Symptom
        matcher = PatternMatcher(config_path="/nonexistent")
        symptom = Symptom(source='logs', field='pattern', value='[invalid regex')
        assert matcher._match_log(symptom, "some text with [invalid regex in it") is True

    def test_get_pattern_found(self):
        """get_pattern returns pattern by ID."""
        config = {
            "patterns": [
                {
                    "id": "p1",
                    "name": "Pattern 1",
                    "root_cause": "Test cause",
                    "severity": "medium",
                    "symptoms": {"events": [{"reason": "OOMKilled"}]},
                    "remediation": {"action": "restart"},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        p = matcher.get_pattern("p1")
        assert p is not None
        assert p.id == "p1"

    def test_get_pattern_not_found(self):
        """get_pattern returns None for unknown ID."""
        from src.rca.pattern_matcher import PatternMatcher
        matcher = PatternMatcher(config_path="/nonexistent")
        assert matcher.get_pattern("nonexistent") is None

    def test_match_only_log_symptoms(self):
        """match() where only log symptoms are defined and they match."""
        config = {
            "patterns": [
                {
                    "id": "log-only",
                    "name": "Log Only Pattern",
                    "root_cause": "Log-detected issue",
                    "severity": "high",
                    "symptoms": {
                        "logs": [{"pattern": "FATAL.*database"}]
                    },
                    "remediation": {"action": "restart_db"},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        result = matcher.match({
            "events": [],
            "metrics": {},
            "logs": ["2026-03-12 FATAL: database connection lost"],
        })
        assert result is not None
        assert result.root_cause == "Log-detected issue"

    def test_match_only_metric_symptoms(self):
        """match() where only metric symptoms are defined and they match."""
        config = {
            "patterns": [
                {
                    "id": "metric-only",
                    "name": "Metric Only Pattern",
                    "root_cause": "High CPU",
                    "severity": "medium",
                    "symptoms": {
                        "metrics": [{"name": "cpu_usage", "condition": "> 90"}]
                    },
                    "remediation": {"action": "scale_up"},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        result = matcher.match({
            "events": [],
            "metrics": {"cpu_usage": 95},
            "logs": [],
        })
        assert result is not None

    def test_match_no_match(self):
        """match() with no matching data returns None."""
        config = {
            "patterns": [
                {
                    "id": "nomatch",
                    "name": "Won't Match",
                    "root_cause": "X",
                    "severity": "low",
                    "symptoms": {
                        "events": [{"reason": "VerySpecificReason"}]
                    },
                    "remediation": {"action": "manual"},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        result = matcher.match({
            "events": [{"reason": "DifferentReason"}],
            "metrics": {},
            "logs": [],
        })
        assert result is None

    def test_match_log_entry_as_dict(self):
        """match() where log entries are dicts with 'message' key."""
        config = {
            "patterns": [
                {
                    "id": "dict-log",
                    "name": "Dict Log",
                    "root_cause": "Logged error",
                    "severity": "high",
                    "symptoms": {
                        "logs": [{"pattern": "OOM"}]
                    },
                    "remediation": {"action": "fix"},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        result = matcher.match({
            "events": [],
            "metrics": {},
            "logs": [{"message": "OOM killed process", "timestamp": "2026-03-12"}],
        })
        assert result is not None

    def test_match_combined_event_and_log(self):
        """match() with both event and log symptoms matching."""
        config = {
            "patterns": [
                {
                    "id": "combined",
                    "name": "Combined Pattern",
                    "root_cause": "Combined issue",
                    "severity": "high",
                    "symptoms": {
                        "events": [{"reason": "OOMKilled"}],
                        "logs": [{"pattern": "killed process"}],
                    },
                    "remediation": {"action": "restart"},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        result = matcher.match({
            "events": [{"reason": "OOMKilled", "message": "container killed"}],
            "metrics": {},
            "logs": ["killed process 12345"],
        })
        assert result is not None

    def test_list_patterns(self):
        """list_patterns returns summary dicts."""
        config = {
            "patterns": [
                {
                    "id": "p1",
                    "name": "P1",
                    "root_cause": "Cause1",
                    "severity": "low",
                    "symptoms": {"events": [{"reason": "Test"}]},
                    "remediation": {"action": "manual"},
                }
            ]
        }
        matcher = self._make_matcher_from_config(config)
        patterns = matcher.list_patterns()
        assert len(patterns) >= 1
        assert patterns[0]["id"] == "p1"

    def test_reload(self):
        """reload() re-reads config."""
        import tempfile, yaml
        from src.rca.pattern_matcher import PatternMatcher
        config = {
            "patterns": [
                {
                    "id": "r1",
                    "name": "Reload Test",
                    "root_cause": "test",
                    "severity": "low",
                    "symptoms": {"events": [{"reason": "Test"}]},
                    "remediation": {"action": "manual"},
                }
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config, f)
            path = f.name
        matcher = PatternMatcher(config_path=path)
        assert len(matcher.patterns) == 1
        # Update file
        config["patterns"].append({
            "id": "r2", "name": "Second", "root_cause": "test2",
            "severity": "medium", "symptoms": {"events": [{"reason": "X"}]},
            "remediation": {"action": "manual"},
        })
        with open(path, 'w') as f:
            yaml.dump(config, f)
        matcher.reload()
        assert len(matcher.patterns) == 2
        os.unlink(path)
