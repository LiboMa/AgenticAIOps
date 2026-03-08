"""
Voting System Unit Tests
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.voting import (
    TaskType,
    AgentRole,
    Vote,
    VotingResult,
    AGENT_ROLES,
    VotingWeightCalculator,
    MultiAgentVoting,
    vote_with_agents,
)


class TestTaskType:
    """Test TaskType enum."""
    
    def test_task_types_exist(self):
        """All task types should be defined."""
        assert TaskType.DETECTION.value == "detection"
        assert TaskType.LOCALIZATION.value == "localization"
        assert TaskType.ANALYSIS.value == "analysis"
        assert TaskType.MITIGATION.value == "mitigation"


class TestAgentRoles:
    """Test agent role definitions."""
    
    def test_roles_defined(self):
        """All agent roles should be defined."""
        assert "orchestrator" in AGENT_ROLES
        assert "architect" in AGENT_ROLES
        assert "developer" in AGENT_ROLES
        assert "tester" in AGENT_ROLES
        assert "reviewer" in AGENT_ROLES
    
    def test_architect_expertise(self):
        """Architect should have design expertise."""
        architect = AGENT_ROLES["architect"]
        assert "design" in architect.expertise_areas
        assert "analysis" in architect.expertise_areas
    
    def test_developer_expertise(self):
        """Developer should have implementation expertise."""
        developer = AGENT_ROLES["developer"]
        assert "implementation" in developer.expertise_areas
        assert "debugging" in developer.expertise_areas


class TestVotingWeightCalculator:
    """Test voting weight calculator."""
    
    def setup_method(self):
        self.calculator = VotingWeightCalculator()
    
    def test_default_contribution(self):
        """New agents should have default contribution index."""
        index = self.calculator.calculate_contribution_index("new_agent")
        assert index == 0.5
    
    def test_contribution_with_history(self):
        """Contribution should reflect success rate."""
        self.calculator.contribution_history["test_agent"] = [
            {"success": True},
            {"success": True},
            {"success": False},
            {"success": True},
        ]
        
        index = self.calculator.calculate_contribution_index("test_agent")
        assert index == 0.75  # 3/4 success
    
    def test_expertise_architect_design(self):
        """Architect should have high expertise for design tasks."""
        index = self.calculator.calculate_expertise_index("architect", TaskType.DESIGN)
        assert index > 0.5  # Should be above average
    
    def test_expertise_developer_implementation(self):
        """Developer should have high expertise for implementation tasks."""
        index = self.calculator.calculate_expertise_index("developer", TaskType.IMPLEMENTATION)
        assert index > 0.5  # Should be above average
    
    def test_expertise_tester_testing(self):
        """Tester should have high expertise for testing tasks."""
        index = self.calculator.calculate_expertise_index("tester", TaskType.TESTING)
        assert index > 0.5  # Should be above average
    
    def test_weight_calculation(self):
        """Weight should be α*contribution + β*expertise."""
        weight, contrib, expert = self.calculator.calculate_weight(
            "developer", TaskType.IMPLEMENTATION
        )
        
        expected = 0.4 * contrib + 0.6 * expert
        assert abs(weight - expected) < 0.001
    
    def test_update_contribution(self):
        """Updating contribution should add to history."""
        self.calculator.update_contribution("test_agent", TaskType.ANALYSIS, True)
        
        assert len(self.calculator.contribution_history.get("test_agent", [])) == 1
        assert self.calculator.contribution_history["test_agent"][0]["success"] == True


class TestMultiAgentVoting:
    """Test multi-agent voting system."""
    
    def setup_method(self):
        self.voting = MultiAgentVoting()
    
    def test_vote_single_agent(self):
        """Single agent vote should work."""
        def mock_extract(text):
            return "oom"
        
        result = self.voting.vote(
            task_type=TaskType.ANALYSIS,
            query="Why is the pod crashing?",
            agent_responses={"developer": "The pod is crashing due to OOM"},
            extract_fn=mock_extract,
        )
        
        assert result.final_answer == "oom"
        assert len(result.votes) == 1
    
    def test_vote_consensus(self):
        """Consensus should be detected when all agents agree."""
        def mock_extract(text):
            return "oom"
        
        result = self.voting.vote(
            task_type=TaskType.ANALYSIS,
            query="Why is the pod crashing?",
            agent_responses={
                "architect": "OOM issue",
                "developer": "Memory exceeded",
                "tester": "OOM killed",
            },
            extract_fn=mock_extract,
        )
        
        assert result.consensus == True
        assert result.agreement_ratio == 1.0
    
    def test_vote_no_consensus(self):
        """No consensus when agents disagree."""
        # Mock different diagnoses
        diagnoses = iter(["oom", "network", "config"])
        def mock_extract(text):
            return next(diagnoses)
        
        result = self.voting.vote(
            task_type=TaskType.ANALYSIS,
            query="Why is the pod crashing?",
            agent_responses={
                "architect": "OOM issue",
                "developer": "Network problem",
                "tester": "Config error",
            },
            extract_fn=mock_extract,
        )
        
        assert result.consensus == False
        assert result.agreement_ratio < 0.66
    
    def test_extract_confidence_high(self):
        """High confidence keywords should return high confidence."""
        confidence = self.voting._extract_confidence("I am definitely sure it's OOM")
        assert confidence == 0.9
    
    def test_extract_confidence_low(self):
        """Low confidence keywords should return lower confidence."""
        confidence = self.voting._extract_confidence("Maybe it's a network issue")
        assert confidence == 0.6
    
    def test_extract_confidence_default(self):
        """Default confidence should be 0.8."""
        confidence = self.voting._extract_confidence("The issue is OOM")
        assert confidence == 0.8


class TestVoteWithAgents:
    """Test backward compatible interface."""
    
    def test_weighted_voting(self):
        """vote_with_agents should use weighted voting by default."""
        def mock_extract(text):
            return "oom"
        
        # Patch at module level for vote_with_agents
        with patch.object(MultiAgentVoting, 'vote') as mock_vote:
            mock_vote.return_value = VotingResult(
                task_type=TaskType.ANALYSIS,
                query="test",
                votes=[
                    Vote("architect", "oom", 0.8, "", 0.6, 0.5, 0.7),
                    Vote("developer", "oom", 0.8, "", 0.55, 0.5, 0.6),
                ],
                final_answer="oom",
                total_score=0.8,
                consensus=True,
                agreement_ratio=1.0,
            )
            
            result = vote_with_agents(
                query="Why is the pod crashing?",
                agent_responses={
                    "architect": "OOM issue",
                    "developer": "Memory problem",
                },
                task_type=TaskType.ANALYSIS,
                use_weighted=True,
            )
            
            assert result["method"] == "weighted_voting"
            assert "weights" in result
            assert "votes" in result


class TestVotingResult:
    """Test voting result model."""
    
    def test_to_dict(self):
        """VotingResult should serialize to dict."""
        result = VotingResult(
            task_type=TaskType.ANALYSIS,
            query="test query",
            votes=[],
            final_answer="oom",
            total_score=0.8,
            consensus=True,
            agreement_ratio=1.0,
        )
        
        d = result.to_dict()
        
        assert d["task_type"] == "analysis"
        assert d["final_answer"] == "oom"
        assert d["consensus"] == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
