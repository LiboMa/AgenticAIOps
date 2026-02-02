# Agentic SDLC Platform Architecture

## Overview

Agentic SDLC Platform 是一个基于多 AI Agent 协作的软件开发生命周期管理平台。每个 Agent 拥有独立的记忆、专业技能和明确的职责，通过 Slack 进行协作通信。

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Ma Ronnie (Owner)                            │
│                      需求定义 · 决策 · 验收                           │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              │ 需求/反馈
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│                    🎯 ORCHESTRATOR                                  │
│                    cloud-mbot-worker-1                              │
├─────────────────────────────────────────────────────────────────────┤
│  职责：                                                              │
│  • 接收 Owner 需求，分解为可执行任务                                   │
│  • 将任务分配给 Architect/Developer/Tester                           │
│  • 追踪任务进度和状态                                                 │
│  • 协调团队成员间的沟通                                               │
│  • 向 Owner 汇报项目状态                                              │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              │ 任务分配
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│ 📐 ARCHITECT  │     │ 💻 DEVELOPER  │     │  ✅ TESTER    │
│ cloud-mbot-   │     │ cloud-mbot-   │     │ cloud-mbot-   │
│ architect     │     │ developer     │     │ tester        │
├───────────────┤     ├───────────────┤     ├───────────────┤
│ 职责：         │     │ 职责：         │     │ 职责：         │
│ • 系统架构设计 │     │ • 代码开发     │     │ • 测试用例编写 │
│ • 技术选型     │     │ • 功能实现     │     │ • 测试执行     │
│ • 设计文档     │     │ • 单元测试     │     │ • Bug 报告     │
│ • 架构评审     │     │ • 代码优化     │     │ • 质量分析     │
└───────┬───────┘     └───────┬───────┘     └───────┬───────┘
        │                     │                     │
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              │ 提交评审
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│                    🔍 REVIEWER                                      │
│                    cloud-mbot-researcher-1                          │
├─────────────────────────────────────────────────────────────────────┤
│  职责：                                                              │
│  • 代码评审 (Code Review)                                            │
│  • 设计方案评审                                                       │
│  • 最佳实践检查                                                       │
│  • 安全和性能审查                                                     │
│  • 最终验收                                                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Team Members

| Role | Slack App | Display Name | Status | Description |
|------|-----------|--------------|--------|-------------|
| Orchestrator | cloud-mbot-worker-1 | Orchestrator | ✅ Active | 协调任务分配和进度追踪 |
| Architect | cloud-mbot-architect | Architect | 🆕 Pending | 系统设计和技术选型 |
| Developer | cloud-mbot-developer | Developer | 🆕 Pending | 代码开发和功能实现 |
| Tester | cloud-mbot-tester | Tester | 🆕 Pending | 测试验证和质量保证 |
| Reviewer | cloud-mbot-researcher-1 | Reviewer | ✅ Active | 代码评审和设计评审 |

## Workflow

### Standard Development Flow

```
1. Owner 提出需求
         │
         ▼
2. Orchestrator 分析需求，创建任务
         │
         ├──────────────────┐
         ▼                  ▼
3. Architect 设计    或   Developer 直接开发
   (复杂功能)              (简单功能)
         │
         ▼
4. Reviewer 评审设计
         │
         ▼
5. Developer 实现代码
         │
         ▼
6. Tester 测试验证
         │
         ▼
7. Reviewer 代码评审
         │
         ▼
8. Orchestrator 汇报完成
         │
         ▼
9. Owner 验收
```

### Design Review Process (3-Round Voting)

```
┌─────────────────────────────────────────┐
│           设计方案提交                    │
└─────────────────┬───────────────────────┘
                  │
         ┌────────▼────────┐
         │   Round 1 投票   │
         │   (所有成员)      │
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │   Round 2 讨论   │
         │   (修改建议)      │
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │   Round 3 定稿   │
         │   (最终决定)      │
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │   ≥7.5 通过      │
         │   <7.5 重新设计   │
         └─────────────────┘
```

## Communication

### Slack Channel
- **Primary**: #socrates-square (C0AC47T1N5C)
- All agents communicate in this channel
- All conversations visible to Owner

### Message Format
- Task assignment: `@agent 任务描述`
- Status update: `状态汇报格式化表格`
- Review request: `请求评审 + 相关文档/代码`

## Technology Stack

| Component | Technology |
|-----------|------------|
| Agent Runtime | OpenClaw |
| Communication | Slack API (Socket Mode) |
| Knowledge Base | Amazon Bedrock KB |
| Repository | GitHub |
| Tools | MCP Server (kubectl, aws) |

## Memory Management

Each agent has independent memory:

```
~/.openclaw-{agent}/
├── workspace/
│   ├── SOUL.md          # Agent personality
│   ├── AGENTS.md        # Working guidelines
│   ├── MEMORY.md        # Long-term memory
│   └── memory/
│       └── YYYY-MM-DD.md # Daily notes
```

## Shared Resources

| Resource | Location | Purpose |
|----------|----------|---------|
| Codebase | /home/ubuntu/agentic-aiops-mvp | Project code |
| Knowledge Base | Bedrock KB (GGNIZHOHEX) | EKS patterns & docs |
| Documentation | docs/ | Project documentation |

## Security Considerations

1. **Token Management**: Each agent has separate Slack Bot Token
2. **Access Control**: Agents only access necessary resources
3. **Audit Trail**: All communications logged in Slack
4. **Human Oversight**: Critical decisions require Owner approval

## Future Enhancements

1. **Phase 2.2**: Schema validation for plugin manifests
2. **Phase 3**: EventBus for hot-reload
3. **LangGraph Integration**: State machine for complex workflows
4. **Git Integration**: Automated PR creation and review
