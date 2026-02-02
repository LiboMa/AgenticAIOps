"""
AgenticAIOps - Multi-Agent Weighted Voting V2

Enhanced voting mechanism based on mABC framework (arXiv:2404.12135).
Implements contribution-weighted and expertise-weighted voting to reduce
LLM hallucinations and improve decision accuracy.

Features:
- Contribution Index: Based on historical task success rate
- Expertise Index: Based on role-task matching
- Weighted voting aggregation
- Backward compatible with existing voting system
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Types
# =============================================================================

class TaskType(Enum):
    """AIOps task types (from AIOpsLab)"""
    DETECTION = "detection"           # Fault detection
    LOCALIZATION = "localization"     # Fault localization
    ANALYSIS = "analysis"             # Root cause analysis
    MITIGATION = "mitigation"         # Fault remediation
    DESIGN = "design"                 # Design task
    IMPLEMENTATION = "implementation" # Implementation task
    TESTING = "testing"               # Testing task
    REVIEW = "review"                 # Review task


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class AgentRole:
    """Agent role definition"""
    id: str
    name: str
    expertise_areas: List[str]
    base_weight: float
    contribution_history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Vote:
    """Single vote from an agent"""
    agent_id: str
    proposal: str
    confidence: float
    reasoning: str
    weight: float
    contribution_index: float = 0.0
    expertise_index: float = 0.0


@dataclass
class VotingResult:
    """Voting result"""
    task_type: TaskType
    query: str
    votes: List[Vote]
    final_answer: str
    total_score: float
    consensus: bool
    agreement_ratio: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "query": self.query,
            "votes": [
                {
                    "agent_id": v.agent_id,
                    "proposal": v.proposal,
                    "weight": v.weight,
                    "confidence": v.confidence,
                }
                for v in self.votes
            ],
            "final_answer": self.final_answer,
            "total_score": self.total_score,
            "consensus": self.consensus,
            "agreement_ratio": self.agreement_ratio,
            "metadata": self.metadata,
        }


# =============================================================================
# Predefined Agent Roles
# =============================================================================

AGENT_ROLES: Dict[str, AgentRole] = {
    "orchestrator": AgentRole(
        id="orchestrator",
        name="Orchestrator",
        expertise_areas=["coordination", "planning", "detection"],
        base_weight=0.15,
    ),
    "architect": AgentRole(
        id="architect",
        name="Architect",
        expertise_areas=["design", "analysis", "localization"],
        base_weight=0.25,
    ),
    "developer": AgentRole(
        id="developer",
        name="Developer",
        expertise_areas=["implementation", "mitigation", "debugging"],
        base_weight=0.25,
    ),
    "tester": AgentRole(
        id="tester",
        name="Tester",
        expertise_areas=["testing", "detection", "verification"],
        base_weight=0.20,
    ),
    "reviewer": AgentRole(
        id="reviewer",
        name="Reviewer",
        expertise_areas=["review", "analysis", "validation"],
        base_weight=0.25,  # Increased from 0.15 per review suggestion
    ),
}

# Task type to expertise mapping
TASK_EXPERTISE_MAP: Dict[TaskType, List[str]] = {
    TaskType.DETECTION: ["detection", "testing", "monitoring"],
    TaskType.LOCALIZATION: ["analysis", "localization", "debugging"],
    TaskType.ANALYSIS: ["analysis", "review", "design"],
    TaskType.MITIGATION: ["implementation", "mitigation", "debugging"],
    TaskType.DESIGN: ["design", "analysis", "architecture"],
    TaskType.IMPLEMENTATION: ["implementation", "debugging", "coding"],
    TaskType.TESTING: ["testing", "verification", "qa"],
    TaskType.REVIEW: ["review", "validation", "analysis"],
}


# =============================================================================
# Voting Weight Calculator
# =============================================================================

class VotingWeightCalculator:
    """
    Calculates voting weights based on mABC formula:
    
    Weight = α × Contribution_Index + β × Expertise_Index
    
    Where:
    - α = 0.4 (contribution weight)
    - β = 0.6 (expertise weight)
    """
    
    def __init__(
        self,
        alpha: float = 0.4,
        beta: float = 0.6,
        history_file: Optional[str] = None,
    ):
        """
        Initialize weight calculator.
        
        Args:
            alpha: Contribution weight (default 0.4)
            beta: Expertise weight (default 0.6)
            history_file: Path to contribution history file
        """
        self.alpha = alpha
        self.beta = beta
        self.contribution_history: Dict[str, List[Dict[str, Any]]] = {}
        
        self.history_file = history_file
        if history_file:
            self._load_history(history_file)
    
    def calculate_contribution_index(self, agent_id: str) -> float:
        """
        Calculate contribution index based on historical success rate.
        
        Args:
            agent_id: Agent identifier
        
        Returns:
            Contribution index (0.0 - 1.0)
        """
        history = self.contribution_history.get(agent_id, [])
        
        if not history:
            return 0.5  # Default for new agents
        
        # Only consider recent history (last 50 tasks)
        recent_history = history[-50:]
        success_count = sum(1 for h in recent_history if h.get("success", False))
        
        return success_count / len(recent_history)
    
    def calculate_expertise_index(
        self,
        agent_id: str,
        task_type: TaskType,
    ) -> float:
        """
        Calculate expertise index based on role-task matching.
        
        Args:
            agent_id: Agent identifier
            task_type: Task type
        
        Returns:
            Expertise index (0.0 - 1.0)
        """
        role = AGENT_ROLES.get(agent_id)
        
        if not role:
            return 0.5  # Default for unknown agents
        
        required_expertise = TASK_EXPERTISE_MAP.get(task_type, [])
        
        if not required_expertise:
            return role.base_weight
        
        # Calculate matching score
        match_count = sum(
            1 for exp in role.expertise_areas
            if exp in required_expertise
        )
        
        return match_count / len(required_expertise)
    
    def calculate_weight(
        self,
        agent_id: str,
        task_type: TaskType,
    ) -> tuple[float, float, float]:
        """
        Calculate final voting weight.
        
        Args:
            agent_id: Agent identifier
            task_type: Task type
        
        Returns:
            (weight, contribution_index, expertise_index)
        """
        contribution = self.calculate_contribution_index(agent_id)
        expertise = self.calculate_expertise_index(agent_id, task_type)
        
        weight = self.alpha * contribution + self.beta * expertise
        
        return weight, contribution, expertise
    
    def update_contribution(
        self,
        agent_id: str,
        task_type: TaskType,
        success: bool,
    ):
        """
        Update contribution history after task completion.
        
        Args:
            agent_id: Agent identifier
            task_type: Task type
            success: Whether the task was successful
        """
        if agent_id not in self.contribution_history:
            self.contribution_history[agent_id] = []
        
        self.contribution_history[agent_id].append({
            "task_type": task_type.value,
            "success": success,
            "timestamp": datetime.now().isoformat(),
        })
        
        # Persist history
        if self.history_file:
            self._save_history(self.history_file)
    
    def _load_history(self, file_path: str):
        """Load contribution history from file."""
        try:
            path = Path(file_path)
            if path.exists():
                with open(path, "r") as f:
                    self.contribution_history = json.load(f)
                logger.info(f"Loaded contribution history from {file_path}")
        except Exception as e:
            logger.warning(f"Failed to load history: {e}")
    
    def _save_history(self, file_path: str):
        """Save contribution history to file."""
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(self.contribution_history, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save history: {e}")


# =============================================================================
# Multi-Agent Voting System
# =============================================================================

class MultiAgentVoting:
    """
    Multi-agent weighted voting system based on mABC framework.
    
    Features:
    - Contribution-weighted voting
    - Expertise-weighted voting
    - Consensus detection
    - Backward compatible
    """
    
    def __init__(
        self,
        alpha: float = 0.4,
        beta: float = 0.6,
        consensus_threshold: float = 0.66,
        history_file: Optional[str] = None,
    ):
        """
        Initialize voting system.
        
        Args:
            alpha: Contribution weight
            beta: Expertise weight
            consensus_threshold: Threshold for consensus (default 66%)
            history_file: Path to contribution history
        """
        self.consensus_threshold = consensus_threshold
        self.weight_calculator = VotingWeightCalculator(
            alpha=alpha,
            beta=beta,
            history_file=history_file,
        )
    
    def vote(
        self,
        task_type: TaskType,
        query: str,
        agent_responses: Dict[str, str],
        extract_fn: Optional[callable] = None,
    ) -> VotingResult:
        """
        Execute multi-agent voting.
        
        Args:
            task_type: Task type
            query: Query/question
            agent_responses: Dict of agent_id -> response
            extract_fn: Optional function to extract diagnosis from response
        
        Returns:
            VotingResult
        """
        votes: List[Vote] = []
        
        # Import diagnosis extraction from existing module
        if extract_fn is None:
            from .multi_agent_voting import extract_diagnosis
            extract_fn = extract_diagnosis
        
        for agent_id, response in agent_responses.items():
            # Extract proposal/diagnosis
            try:
                proposal = extract_fn(response)
            except:
                proposal = response[:100]  # Fallback to truncated response
            
            # Calculate weight
            weight, contribution, expertise = self.weight_calculator.calculate_weight(
                agent_id, task_type
            )
            
            # Extract confidence from response (simple heuristic)
            confidence = self._extract_confidence(response)
            
            votes.append(Vote(
                agent_id=agent_id,
                proposal=proposal,
                confidence=confidence,
                reasoning=response[:200] if response else "",
                weight=weight,
                contribution_index=contribution,
                expertise_index=expertise,
            ))
        
        # Weighted aggregation
        proposal_scores: Dict[str, float] = {}
        for vote in votes:
            if vote.proposal not in proposal_scores:
                proposal_scores[vote.proposal] = 0.0
            proposal_scores[vote.proposal] += vote.weight * vote.confidence
        
        # Select highest score
        if proposal_scores:
            final_answer = max(proposal_scores, key=proposal_scores.get)
            total_score = proposal_scores[final_answer]
        else:
            final_answer = "unknown"
            total_score = 0.0
        
        # Calculate agreement ratio
        proposals = [v.proposal for v in votes]
        agreement_count = proposals.count(final_answer)
        agreement_ratio = agreement_count / len(proposals) if proposals else 0.0
        consensus = agreement_ratio >= self.consensus_threshold
        
        return VotingResult(
            task_type=task_type,
            query=query,
            votes=votes,
            final_answer=final_answer,
            total_score=total_score,
            consensus=consensus,
            agreement_ratio=agreement_ratio,
            metadata={
                "num_voters": len(votes),
                "proposal_scores": proposal_scores,
                "consensus_threshold": self.consensus_threshold,
            },
        )
    
    def update_history(
        self,
        agent_id: str,
        task_type: TaskType,
        success: bool,
    ):
        """Update contribution history after task completion."""
        self.weight_calculator.update_contribution(agent_id, task_type, success)
    
    def _extract_confidence(self, response: str) -> float:
        """
        Extract confidence from response text.
        
        Simple heuristic based on keywords.
        """
        response_lower = response.lower()
        
        # High confidence indicators
        high_confidence = ["确定", "肯定", "definitely", "certain", "确认", "clearly"]
        if any(kw in response_lower for kw in high_confidence):
            return 0.9
        
        # Low confidence indicators
        low_confidence = ["可能", "也许", "maybe", "perhaps", "might", "不确定"]
        if any(kw in response_lower for kw in low_confidence):
            return 0.6
        
        # Default confidence
        return 0.8


# =============================================================================
# Backward Compatible Interface
# =============================================================================

def vote_with_agents(
    query: str,
    agent_responses: Dict[str, str],
    task_type: TaskType = TaskType.ANALYSIS,
    use_weighted: bool = True,
) -> Dict[str, Any]:
    """
    Unified voting interface (backward compatible).
    
    Args:
        query: Query/question
        agent_responses: Dict of agent_id -> response
        task_type: Task type
        use_weighted: Whether to use weighted voting
    
    Returns:
        Voting result dict
    """
    if use_weighted and len(agent_responses) > 1:
        # Use new weighted voting
        voting = MultiAgentVoting()
        result = voting.vote(task_type, query, agent_responses)
        
        return {
            "diagnosis": result.final_answer,
            "confidence": result.agreement_ratio,
            "consensus": result.consensus,
            "votes": {v.agent_id: v.proposal for v in result.votes},
            "weights": {v.agent_id: round(v.weight, 3) for v in result.votes},
            "method": "weighted_voting",
        }
    else:
        # Use existing simple voting
        from .multi_agent_voting import simple_vote
        
        responses = list(agent_responses.values())
        result = simple_vote(responses)
        result["method"] = "simple_voting"
        
        return result


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TaskType",
    "AgentRole",
    "Vote",
    "VotingResult",
    "AGENT_ROLES",
    "TASK_EXPERTISE_MAP",
    "VotingWeightCalculator",
    "MultiAgentVoting",
    "vote_with_agents",
]
