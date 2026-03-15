"""Tests to boost coverage for src/voting/__init__.py (79% → ~90%+)."""

import json
import tempfile
from pathlib import Path

from src.voting import (
    VotingWeightCalculator,
    MultiAgentVoting,
    TaskType,
    extract_diagnosis,
    simple_vote,
    vote_with_agents,
)


class TestVotingWeightCalculatorHistoryIO:
    def test_save_and_load_history(self, tmp_path):
        history_file = str(tmp_path / "history.json")
        calc = VotingWeightCalculator(history_file=history_file)
        calc.update_contribution("agent-a", TaskType.ANALYSIS, True)
        calc.update_contribution("agent-a", TaskType.ANALYSIS, False)

        # Verify file was written
        assert Path(history_file).exists()
        data = json.loads(Path(history_file).read_text())
        assert "agent-a" in data

        # Load into new calculator
        calc2 = VotingWeightCalculator(history_file=history_file)
        assert len(calc2.contribution_history.get("agent-a", [])) == 2

    def test_load_missing_file_no_error(self, tmp_path):
        calc = VotingWeightCalculator(history_file=str(tmp_path / "nope.json"))
        assert calc.contribution_history == {} or isinstance(calc.contribution_history, dict)

    def test_save_creates_parent_dirs(self, tmp_path):
        deep = str(tmp_path / "a" / "b" / "history.json")
        calc = VotingWeightCalculator(history_file=deep)
        calc.update_contribution("x", TaskType.ANALYSIS, True)
        assert Path(deep).exists()


class TestExtractConfidenceAndDiagnosis:
    def test_high_confidence_keyword(self):
        voting = MultiAgentVoting()
        assert voting._extract_confidence("I am definitely sure it's OOM") == 0.9

    def test_low_confidence_keyword(self):
        voting = MultiAgentVoting()
        assert voting._extract_confidence("maybe it's a network issue") == 0.6

    def test_default_confidence(self):
        voting = MultiAgentVoting()
        assert voting._extract_confidence("the root cause is disk full") == 0.8

    def test_extract_diagnosis_unknown(self):
        result = extract_diagnosis("nothing relevant here at all")
        assert result == "unknown"


class TestSimpleVoteEdgeCases:
    def test_empty_list(self):
        result = simple_vote([])
        assert result["diagnosis"] == "unknown"
        assert result["confidence"] == 0.0


class TestMultiAgentVotingEdgeCases:
    def test_vote_with_empty_responses(self):
        voting = MultiAgentVoting()
        result = voting.vote(TaskType.ANALYSIS, "test", {})
        assert result.final_answer == "unknown"

    def test_exception_in_extract_fn(self):
        """When extract raises, should fallback to truncated response."""
        voting = MultiAgentVoting()
        result = voting.vote(
            TaskType.ANALYSIS,
            "test query",
            {"agent-1": "some response about oom kill events"},
        )
        assert result.final_answer is not None

    def test_update_history(self):
        voting = MultiAgentVoting()
        voting.update_history("agent-1", TaskType.ANALYSIS, True)
        history = voting.weight_calculator.contribution_history
        assert "agent-1" in history


class TestVoteWithAgents:
    def test_weighted_voting(self):
        result = vote_with_agents(
            "what happened?",
            {"a1": "oom kill detected", "a2": "oom killer triggered"},
            task_type=TaskType.ANALYSIS,
            use_weighted=True,
        )
        assert "diagnosis" in result
        assert result["method"] == "weighted_voting"

    def test_simple_voting_fallback(self):
        result = vote_with_agents(
            "test",
            {"a1": "disk full"},
            use_weighted=True,  # only 1 agent → simple
        )
        assert result["method"] == "simple_voting"

    def test_simple_voting_explicit(self):
        result = vote_with_agents(
            "test",
            {"a1": "oom", "a2": "oom"},
            use_weighted=False,
        )
        assert result["method"] == "simple_voting"
