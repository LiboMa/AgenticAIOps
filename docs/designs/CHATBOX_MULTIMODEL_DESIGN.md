# Chatbox 多模型交互建议

**日期:** 2026-02-12
**作者:** Researcher Agent

---

## 1. 调研结果

### 1.1 业界优秀 Chatbox 参考

| 项目 | Stars | 特点 |
|------|-------|------|
| **Open WebUI** | 80k+ | 多模型支持、RAG、插件系统、权限管理 |
| **LobeChat** | 60k+ | 多Agent协作、MCP插件、多模型Provider |
| **NextChat** | 80k+ | 轻量、MCP支持、多平台 |

### 1.2 多模型交互的核心功能

```
┌─────────────────────────────────────────────────────────────┐
│              多模型 Chatbox 功能矩阵                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  🔀 模型切换                                                 │
│  ├── 下拉菜单快速切换模型                                   │
│  ├── 每个对话独立模型设置                                   │
│  └── 热键切换 (Ctrl+M)                                     │
│                                                              │
│  🆚 模型对比                                                 │
│  ├── 并排对比 (Side-by-side)                                │
│  ├── 同一问题多模型回答                                     │
│  └── 评分/投票选择最佳回答                                  │
│                                                              │
│  🧩 模型编排                                                 │
│  ├── 路由策略 (按任务类型选模型)                            │
│  ├── 级联调用 (快模型过滤 → 强模型精答)                    │
│  └── 多模型投票 (现有 multi_agent_voting.py)               │
│                                                              │
│  📊 模型管理                                                 │
│  ├── Provider 配置 (Bedrock/OpenAI/Ollama)                 │
│  ├── 成本追踪 (per-model token usage)                      │
│  └── 性能对比 (延迟/质量评分)                               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. AgenticAIOps Chatbox 升级建议

### 2.1 Phase 1: 基础多模型 (1-2 周)

#### 2.1.1 后端: 模型路由

```python
# api_server.py 新增

# 模型配置
AVAILABLE_MODELS = {
    "claude-sonnet": {
        "id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "name": "Claude Sonnet 3.5",
        "provider": "bedrock",
        "strengths": ["fast", "code", "analysis"],
        "cost_per_1k": 0.003
    },
    "claude-opus": {
        "id": "global.anthropic.claude-opus-4-6-v1",
        "name": "Claude Opus 4",
        "provider": "bedrock",
        "strengths": ["reasoning", "complex", "creative"],
        "cost_per_1k": 0.015
    },
    "titan-lite": {
        "id": "amazon.titan-text-lite-v1",
        "name": "Titan Lite",
        "provider": "bedrock",
        "strengths": ["fast", "cheap", "simple"],
        "cost_per_1k": 0.0003
    }
}

# 智能路由
class ModelRouter:
    def select_model(self, message: str, context: dict) -> str:
        """基于意图自动选择模型"""
        intent = classify_intent(message)
        
        if intent in ['simple_query', 'list', 'status']:
            return "titan-lite"        # 简单查询用便宜模型
        elif intent in ['rca', 'analysis', 'complex']:
            return "claude-opus"       # 复杂分析用强模型
        else:
            return "claude-sonnet"     # 默认用平衡模型

# 新 API
@app.get("/api/models")
async def list_models():
    return {"models": AVAILABLE_MODELS}

@app.post("/api/chat")
async def chat(request: ChatRequest):
    model = request.model or router.select_model(request.message, {})
    # ... 使用选定模型处理
```

#### 2.1.2 前端: 模型选择器

```jsx
// AgentChat.jsx 新增模型选择器

const ModelSelector = ({ models, selectedModel, onSelect }) => (
  <Select
    value={selectedModel}
    onChange={onSelect}
    style={{ width: 200 }}
    options={models.map(m => ({
      value: m.id,
      label: (
        <Space>
          <Tag color={m.strengths.includes('fast') ? 'green' : 'blue'}>
            {m.name}
          </Tag>
          <Text type="secondary">${m.cost_per_1k}/1K</Text>
        </Space>
      )
    }))}
  />
)

// 在 Chat 输入框旁添加
<Space>
  <ModelSelector models={models} selectedModel={model} onSelect={setModel} />
  <Tooltip title="自动选择">
    <Switch checked={autoRoute} onChange={setAutoRoute} />
  </Tooltip>
  <TextArea />
  <Button icon={<SendOutlined />} />
</Space>
```

### 2.2 Phase 2: 模型对比 (2-3 周)

#### 并排对比视图

```
┌─────────────────────┬─────────────────────┐
│    Claude Opus 4    │   Claude Sonnet 3.5 │
├─────────────────────┼─────────────────────┤
│                     │                     │
│  RCA 分析结果:      │  RCA 分析结果:      │
│  根因: CPU 飙高     │  根因: CPU 飙高     │
│  置信度: 95%        │  置信度: 87%        │
│  建议: 扩容实例     │  建议: 重启进程     │
│                     │                     │
│  延迟: 3.2s         │  延迟: 1.1s         │
│  Tokens: 1,523      │  Tokens: 823        │
│  成本: $0.023       │  成本: $0.002       │
│                     │                     │
│  [👍 选择此回答]     │  [👍 选择此回答]     │
└─────────────────────┴─────────────────────┘
```

```jsx
// CompareView.jsx
const CompareView = ({ question, responses }) => (
  <Row gutter={16}>
    {responses.map(resp => (
      <Col span={12} key={resp.model}>
        <Card title={resp.modelName} extra={
          <Space>
            <Tag>{resp.latency}ms</Tag>
            <Tag color="gold">${resp.cost}</Tag>
          </Space>
        }>
          <ReactMarkdown>{resp.content}</ReactMarkdown>
          <Button onClick={() => vote(resp.model)}>👍 选择</Button>
        </Card>
      </Col>
    ))}
  </Row>
)
```

### 2.3 Phase 3: 智能编排 (3-4 周)

#### 模型级联策略

```
用户输入
    │
    ▼
┌──────────────┐
│ Intent 分类  │ (Titan Lite - 快且便宜)
└──────┬───────┘
       │
       ├── 简单查询 → Titan Lite 直接回答
       │
       ├── 运维操作 → Claude Sonnet (平衡)
       │
       └── 复杂分析 → Claude Opus (最强)
                          │
                          ├── RCA 分析
                          ├── 多模型投票
                          └── 知识库关联
```

#### 运维场景模型推荐

| 场景 | 推荐模型 | 原因 |
|------|---------|------|
| 资源列表查询 | Titan Lite | 简单格式化，无需推理 |
| 健康检查 | Sonnet | 需要一定判断力 |
| 异常检测 | Sonnet | 模式匹配 |
| RCA 根因分析 | Opus | 需要深度推理 |
| SOP 推荐 | Sonnet | 知识匹配 |
| 安全分析 | Opus | 需要全面考虑 |
| 成本优化建议 | Opus | 需要综合分析 |

---

## 3. UI 改进建议

### 3.1 当前 Chatbox 局限

```
当前:
├── 单模型 (Bedrock Claude)
├── 纯文本输入/输出
├── 无模型选择
├── 无成本追踪
├── 无对话分支
└── 无历史搜索
```

### 3.2 建议新增功能

```
优先级 P0:
├── 模型选择下拉菜单
├── 自动/手动模型切换
├── 消息中显示使用的模型
└── Token 使用量统计

优先级 P1:
├── 并排模型对比
├── 对话分支 (Branching)
├── 历史搜索
├── 代码高亮
└── Markdown 渲染增强

优先级 P2:
├── 语音输入/输出
├── 文件上传 (日志分析)
├── 图表渲染 (指标可视化)
├── 快捷命令面板 (Cmd+K)
└── 对话模板 (预设 Prompt)
```

### 3.3 参考实现

| 功能 | 参考项目 | 链接 |
|------|---------|------|
| 多模型切换 | Open WebUI | github.com/open-webui/open-webui |
| 对话分支 | LobeChat | github.com/lobehub/lobe-chat |
| MCP 集成 | NextChat | github.com/ChatGPTNextWeb/NextChat |
| Agent Market | LobeChat | 预置 Agent 模板 |

---

## 4. 实现路线图

```
Week 1-2: 后端模型路由 + 前端模型选择器
Week 3-4: 并排对比视图 + 投票机制
Week 5-6: 智能路由 + 成本追踪
Week 7-8: 高级功能 (分支对话/文件上传/语音)
```

### 成本估算

| 模型 | 输入/$1M tokens | 输出/$1M tokens | 日均预估 |
|------|----------------|----------------|---------|
| Titan Lite | $0.15 | $0.20 | ~$0.50 |
| Claude Sonnet | $3.00 | $15.00 | ~$5.00 |
| Claude Opus | $15.00 | $75.00 | ~$15.00 |
| **混合使用** | | | **~$8-12** |

**智能路由可降低 30-50% 成本** (简单查询用便宜模型)

---

*文档结束*
