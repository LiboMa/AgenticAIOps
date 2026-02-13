# Multi-Agent Voting 机制设计文档

**版本**: 1.0  
**作者**: Architect  
**日期**: 2026-02-02  
**参考**: mABC Framework (arXiv:2404.12135)

---

## 1. 概述

### 1.1 背景

mABC (Multi-Agent Blockchain-inspired Collaboration) 论文提出了区块链启发的多 Agent 投票机制，通过贡献度和专业度加权来减少 LLM 幻觉，提高决策准确性。

### 1.2 现有实现

当前 `src/multi_agent_voting.py` 已实现：
- ✅ 诊断关键词提取
- ✅ 温度采样投票 (3 轮)
- ✅ 简单多数投票
- ❌ 缺少贡献度/专业度加权
- ❌ 缺少 Agent 角色投票

### 1.3 目标

- 引入 mABC 的加权投票机制
- 支持多 Agent 角色投票 (Orchestrator/Architect/Developer/Tester/Reviewer)
- 计算 Contribution Index 和 Expertise Index
- 与现有投票系统兼容

---

## 2. mABC 投票机制设计

### 2.1 核心公式

```
投票权重 = α × Contribution_Index + β × Expertise_Index

其中:
- α = 0.4 (贡献度权重)
- β = 0.6 (专业度权重)
- Contribution_Index: 历史任务完成度
- Expertise_Index: 角色-任务匹配度
```

### 2.2 架构设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Multi-Agent Voting System                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      Task Input                              │   │
│  │  • 诊断任务 (Detection/Localization/Analysis/Mitigation)     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│           ┌──────────────────┼──────────────────┐                   │
│           ▼                  ▼                  ▼                    │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │  Architect   │   │  Developer   │   │   Tester     │            │
│  │  (设计视角)   │   │  (实现视角)  │   │  (测试视角)  │            │
│  │              │   │              │   │              │            │
│  │ Weight: 0.35 │   │ Weight: 0.30 │   │ Weight: 0.20 │            │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘            │
│         │                  │                  │                     │
│         └──────────────────┼──────────────────┘                     │
│                            ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Weighted Voting Aggregation                     │   │
│  │                                                              │   │
│  │  Final = argmax(Σ Weight_i × Vote_i)                        │   │
│  │                                                              │   │
│  │  Contribution Index = Historical Success Rate                │   │
│  │  Expertise Index = Role-Task Match Score                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                            │                                         │
│                            ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Reviewer (最终确认)                        │   │
│  │                     评估投票一致性                            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 数据模型

### 3.1 任务类型

```python
from enum import Enum

class TaskType(Enum):
    """AIOps 任务类型 (来自 AIOpsLab)"""
    DETECTION = "detection"         # 故障检测
    LOCALIZATION = "localization"   # 故障定位
    ANALYSIS = "analysis"           # 根因分析
    MITIGATION = "mitigation"       # 故障修复
    DESIGN = "design"               # 设计任务
    IMPLEMENTATION = "implementation" # 实现任务
    TESTING = "testing"             # 测试任务
    REVIEW = "review"               # 评审任务
```

### 3.2 Agent 角色

```python
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class AgentRole:
    """Agent 角色定义"""
    id: str
    name: str
    expertise_areas: List[str]  # 专业领域
    base_weight: float          # 基础权重
    contribution_history: Dict[str, float]  # 历史贡献

# 预定义角色
AGENT_ROLES = {
    "orchestrator": AgentRole(
        id="orchestrator",
        name="Orchestrator",
        expertise_areas=["coordination", "planning", "detection"],
        base_weight=0.15,
        contribution_history={}
    ),
    "architect": AgentRole(
        id="architect",
        name="Architect",
        expertise_areas=["design", "analysis", "localization"],
        base_weight=0.25,
        contribution_history={}
    ),
    "developer": AgentRole(
        id="developer",
        name="Developer",
        expertise_areas=["implementation", "mitigation", "debugging"],
        base_weight=0.25,
        contribution_history={}
    ),
    "tester": AgentRole(
        id="tester",
        name="Tester",
        expertise_areas=["testing", "detection", "verification"],
        base_weight=0.20,
        contribution_history={}
    ),
    "reviewer": AgentRole(
        id="reviewer",
        name="Reviewer",
        expertise_areas=["review", "analysis", "validation"],
        base_weight=0.15,
        contribution_history={}
    ),
}
```

### 3.3 投票结果

```python
@dataclass
class Vote:
    """单个投票"""
    agent_id: str
    proposal: str           # 提议的答案/诊断
    confidence: float       # 置信度 (0-1)
    reasoning: str          # 推理过程
    weight: float           # 计算后的权重

@dataclass
class VotingResult:
    """投票结果"""
    task_type: TaskType
    query: str
    votes: List[Vote]
    final_answer: str
    total_score: float
    consensus: bool         # 是否达成共识
    agreement_ratio: float  # 一致性比例
    metadata: Dict[str, Any]
```

---

## 4. 核心算法

### 4.1 权重计算

```python
class VotingWeightCalculator:
    """投票权重计算器"""
    
    def __init__(
        self,
        alpha: float = 0.4,  # 贡献度权重
        beta: float = 0.6    # 专业度权重
    ):
        self.alpha = alpha
        self.beta = beta
        self.contribution_history = {}  # agent_id -> success_rate
    
    def calculate_contribution_index(
        self,
        agent_id: str
    ) -> float:
        """
        计算贡献指数
        
        基于历史任务完成率
        """
        history = self.contribution_history.get(agent_id, [])
        if not history:
            return 0.5  # 默认值
        
        success_count = sum(1 for h in history if h["success"])
        return success_count / len(history)
    
    def calculate_expertise_index(
        self,
        agent_id: str,
        task_type: TaskType
    ) -> float:
        """
        计算专业度指数
        
        基于角色-任务匹配度
        """
        role = AGENT_ROLES.get(agent_id)
        if not role:
            return 0.5
        
        # 任务类型到专业领域的映射
        task_expertise_map = {
            TaskType.DETECTION: ["detection", "testing"],
            TaskType.LOCALIZATION: ["analysis", "localization", "debugging"],
            TaskType.ANALYSIS: ["analysis", "review", "design"],
            TaskType.MITIGATION: ["implementation", "mitigation"],
            TaskType.DESIGN: ["design", "analysis"],
            TaskType.IMPLEMENTATION: ["implementation", "debugging"],
            TaskType.TESTING: ["testing", "verification"],
            TaskType.REVIEW: ["review", "validation"],
        }
        
        required_expertise = task_expertise_map.get(task_type, [])
        
        # 计算匹配度
        match_count = sum(
            1 for exp in role.expertise_areas 
            if exp in required_expertise
        )
        
        if not required_expertise:
            return role.base_weight
        
        return match_count / len(required_expertise)
    
    def calculate_weight(
        self,
        agent_id: str,
        task_type: TaskType
    ) -> float:
        """
        计算最终投票权重
        
        Weight = α × Contribution + β × Expertise
        """
        contribution = self.calculate_contribution_index(agent_id)
        expertise = self.calculate_expertise_index(agent_id, task_type)
        
        return self.alpha * contribution + self.beta * expertise
    
    def update_contribution(
        self,
        agent_id: str,
        task_type: TaskType,
        success: bool
    ):
        """更新贡献历史"""
        if agent_id not in self.contribution_history:
            self.contribution_history[agent_id] = []
        
        self.contribution_history[agent_id].append({
            "task_type": task_type.value,
            "success": success,
            "timestamp": datetime.now()
        })
```

### 4.2 投票聚合

```python
class MultiAgentVoting:
    """多 Agent 投票系统"""
    
    def __init__(self):
        self.weight_calculator = VotingWeightCalculator()
    
    def vote(
        self,
        task_type: TaskType,
        query: str,
        agent_responses: Dict[str, str]  # agent_id -> response
    ) -> VotingResult:
        """
        执行多 Agent 投票
        
        Args:
            task_type: 任务类型
            query: 查询/问题
            agent_responses: 各 Agent 的响应
        
        Returns:
            VotingResult 投票结果
        """
        votes = []
        
        for agent_id, response in agent_responses.items():
            # 提取诊断/提议
            proposal = extract_diagnosis(response)
            
            # 计算权重
            weight = self.weight_calculator.calculate_weight(
                agent_id, task_type
            )
            
            votes.append(Vote(
                agent_id=agent_id,
                proposal=proposal,
                confidence=0.8,  # 可从响应中提取
                reasoning=response[:200],
                weight=weight
            ))
        
        # 加权聚合
        proposal_scores = {}
        for vote in votes:
            if vote.proposal not in proposal_scores:
                proposal_scores[vote.proposal] = 0
            proposal_scores[vote.proposal] += vote.weight * vote.confidence
        
        # 选择最高分
        final_answer = max(proposal_scores, key=proposal_scores.get)
        total_score = proposal_scores[final_answer]
        
        # 计算一致性
        proposals = [v.proposal for v in votes]
        agreement_ratio = proposals.count(final_answer) / len(proposals)
        consensus = agreement_ratio >= 0.66
        
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
                "proposal_scores": proposal_scores
            }
        )
```

---

## 5. 与现有系统集成

### 5.1 保留现有功能

```python
# 现有的温度采样投票保留
from multi_agent_voting import (
    extract_diagnosis,
    multi_agent_vote,      # 温度采样投票
    simple_vote,           # 简单投票
    DIAGNOSIS_PATTERNS     # 诊断模式
)

# 新增: 加权投票
from multi_agent_voting_v2 import (
    MultiAgentVoting,      # 多 Agent 加权投票
    VotingWeightCalculator,
    TaskType,
    AGENT_ROLES
)
```

### 5.2 向后兼容

```python
def vote_with_agents(
    query: str,
    agent_responses: Dict[str, str],
    task_type: TaskType = TaskType.ANALYSIS,
    use_weighted: bool = True
) -> Dict[str, Any]:
    """
    统一投票接口 (向后兼容)
    
    Args:
        query: 查询
        agent_responses: Agent 响应
        task_type: 任务类型
        use_weighted: 是否使用加权投票
    
    Returns:
        投票结果字典
    """
    if use_weighted and len(agent_responses) > 1:
        # 使用新的加权投票
        voting = MultiAgentVoting()
        result = voting.vote(task_type, query, agent_responses)
        return {
            "diagnosis": result.final_answer,
            "confidence": result.agreement_ratio,
            "consensus": result.consensus,
            "votes": {v.agent_id: v.proposal for v in result.votes},
            "weights": {v.agent_id: v.weight for v in result.votes}
        }
    else:
        # 使用现有简单投票
        responses = list(agent_responses.values())
        return simple_vote(responses)
```

---

## 6. 使用示例

### 6.1 诊断场景

```python
from multi_agent_voting_v2 import MultiAgentVoting, TaskType

# 创建投票系统
voting = MultiAgentVoting()

# 模拟各 Agent 对同一问题的诊断
agent_responses = {
    "architect": "根据日志分析，问题是 OOM 导致的容器崩溃，建议增加内存限制",
    "developer": "代码没有问题，是 OOMKilled，容器内存不足",
    "tester": "测试发现在高负载下会触发 OOM，复现了问题",
    "reviewer": "确认是内存问题，建议优化内存使用或增加限制"
}

# 执行投票
result = voting.vote(
    task_type=TaskType.ANALYSIS,
    query="Pod 频繁重启的原因是什么？",
    agent_responses=agent_responses
)

print(f"最终诊断: {result.final_answer}")
print(f"一致性: {result.agreement_ratio:.0%}")
print(f"共识: {'是' if result.consensus else '否'}")
```

### 6.2 输出示例

```
最终诊断: oom
一致性: 100%
共识: 是

投票详情:
- architect: oom (权重: 0.65, 专业匹配: analysis)
- developer: oom (权重: 0.55, 专业匹配: debugging)
- tester: oom (权重: 0.50, 专业匹配: detection)
- reviewer: oom (权重: 0.60, 专业匹配: review)
```

---

## 7. 实现计划

### 7.1 阶段划分

| 阶段 | 内容 | 预计时间 |
|------|------|----------|
| **Phase 1** | 权重计算类 | 0.5 天 |
| **Phase 2** | 投票聚合类 | 0.5 天 |
| **Phase 3** | 与现有系统集成 | 0.5 天 |
| **Phase 4** | 测试 + 文档 | 0.5 天 |

### 7.2 文件清单

```
修改文件:
├── src/multi_agent_voting.py      # 添加新的投票类

新增文件 (可选):
├── src/voting/__init__.py
├── src/voting/weights.py          # 权重计算
├── src/voting/aggregation.py      # 投票聚合
├── tests/test_voting_v2.py        # 测试
└── docs/designs/VOTING_DESIGN.md  # 本文件
```

---

## 8. 评审检查点

- [ ] 权重计算公式是否符合 mABC 规范
- [ ] 是否与现有 multi_agent_voting.py 兼容
- [ ] 贡献度历史如何持久化
- [ ] 专业度映射是否合理
- [ ] 测试覆盖率

---

**设计状态**: 📝 待评审  
**下一步**: 提交给 @Reviewer 评审，通过后交给 @Developer 实现
