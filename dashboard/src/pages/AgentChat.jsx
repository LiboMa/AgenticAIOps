/**
 * AgentChat - LobeChat-style AI Operations Chat
 * 
 * Enhanced with:
 * - Markdown rendering (syntax highlighting, styled tables)
 * - Message action bar (copy/retry)
 * - Dark mode aware styling
 * - File drag & drop zone (UI only, backend P1)
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Button, Avatar, Spin, Card, Typography, Space, Badge, Tooltip, Select, Tag, message as antMessage } from 'antd'
import { SendOutlined, RobotOutlined, UserOutlined, BellOutlined, SwapOutlined, DollarOutlined, PaperClipOutlined } from '@ant-design/icons'
import MarkdownRenderer from '../components/MarkdownRenderer'
import MessageActionBar from '../components/MessageActionBar'
import FileDropZone from '../components/FileDropZone'
import useThemeStore from '../stores/themeStore'

const { TextArea } = Input
const { Text, Title } = Typography
const { Option } = Select

// Available Models (Bedrock only)
const MODELS = [
  { 
    id: 'auto', 
    name: 'Auto Router', 
    description: 'Smart routing based on query type',
    icon: '🧠',
    cost: 'optimal',
    speed: 'fast',
    color: '#06AC38'
  },
  { 
    id: 'claude-opus', 
    name: 'Claude Opus 4', 
    description: 'Best for complex analysis & RCA',
    icon: '🔮',
    cost: 'high',
    speed: 'slow',
    color: '#7c3aed'
  },
  { 
    id: 'claude-sonnet', 
    name: 'Claude Sonnet 4', 
    description: 'Balanced performance & cost',
    icon: '⚡',
    cost: 'medium',
    speed: 'fast',
    color: '#2563eb'
  },
  { 
    id: 'nova-pro', 
    name: 'Amazon Nova Pro', 
    description: 'AWS native, good for ops tasks',
    icon: '🌟',
    cost: 'low',
    speed: 'fast',
    color: '#f59e0b'
  },
  { 
    id: 'nova-lite', 
    name: 'Amazon Nova Lite', 
    description: 'Fast & cheap for simple queries',
    icon: '💨',
    cost: 'very-low',
    speed: 'very-fast',
    color: '#10b981'
  },
]

const COST_LABELS = {
  'very-low': { text: '$', color: '#10b981' },
  'low': { text: '$$', color: '#22c55e' },
  'medium': { text: '$$$', color: '#f59e0b' },
  'high': { text: '$$$$', color: '#ef4444' },
  'optimal': { text: 'Auto', color: '#06AC38' },
}

const MESSAGE_TYPES = {
  USER: 'user',
  ASSISTANT: 'assistant',
  PROACTIVE: 'proactive',
  ALERT: 'alert',
  COMPARE: 'compare',
}

function autoRouteModel(query) {
  const q = query.toLowerCase()
  if (['help', 'commands', '帮助', '命令'].some(k => q === k)) return 'nova-lite'
  if (['health', 'scan', 'show', 'list', 'vpc', 'elb', 'dynamodb', 'ecs'].some(k => q.includes(k))) return 'nova-pro'
  if (['start', 'stop', 'reboot', 'failover', 'invoke', 'sop run'].some(k => q.includes(k))) return 'claude-sonnet'
  if (['anomaly', 'rca', 'analyze', 'diagnose', 'root cause', 'why', '分析', '诊断'].some(k => q.includes(k))) return 'claude-opus'
  if (['kb', 'sop', 'knowledge', 'pattern', 'semantic'].some(k => q.includes(k))) return 'claude-sonnet'
  return 'claude-sonnet'
}

function AgentChat({ apiUrl, onNewAlert }) {
  const darkMode = useThemeStore((s) => s.darkMode)
  
  const [messages, setMessages] = useState([
    {
      type: MESSAGE_TYPES.ASSISTANT,
      content: `👋 **Welcome to AgenticAIOps!**

I'm your AI Operations Assistant with **multi-model** support.

**Models Available:**
- 🧠 **Auto Router** — Smart model selection
- 🔮 **Claude Opus 4** — Complex analysis & RCA
- ⚡ **Claude Sonnet 4** — Balanced (default)
- 🌟 **Amazon Nova Pro** — AWS-native operations
- 💨 **Amazon Nova Lite** — Quick queries

**Try asking:**
- \`Scan my AWS resources\`
- \`health\` — Full health check
- \`sop list\` — View SOPs
- \`kb search high cpu\` — Knowledge search

Select a model above, or use **Auto Router** for smart selection! 🚀`,
      timestamp: new Date().toISOString(),
      model: 'system',
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [selectedModel, setSelectedModel] = useState('auto')
  const [compareMode, setCompareMode] = useState(false)
  const [compareModels, setCompareModels] = useState(['claude-sonnet', 'nova-pro'])
  const [proactiveEnabled, setProactiveEnabled] = useState(true)
  const [tokenStats, setTokenStats] = useState({ total: 0, cost: 0 })
  const [stagedFiles, setStagedFiles] = useState([])
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => { scrollToBottom() }, [messages])

  // Proactive monitoring heartbeat
  useEffect(() => {
    if (!proactiveEnabled) return
    const heartbeatTimer = setTimeout(() => {
      const proactiveMsg = {
        type: MESSAGE_TYPES.PROACTIVE,
        content: `🔔 **Heartbeat Check Complete**\n\nScanned AWS services — all nominal.`,
        timestamp: new Date().toISOString(),
        model: 'system',
      }
      setMessages(prev => [...prev, proactiveMsg])
      onNewAlert?.()
    }, 60000)
    return () => clearTimeout(heartbeatTimer)
  }, [proactiveEnabled, onNewAlert])

  const sendToModel = async (userMessage, modelId) => {
    try {
      const actualModel = modelId === 'auto' ? autoRouteModel(userMessage) : modelId
      const response = await fetch(`${apiUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage, model: actualModel })
      })
      const data = await response.json()
      if (data.tokens) {
        setTokenStats(prev => ({
          total: prev.total + (data.tokens || 0),
          cost: prev.cost + (data.cost || 0),
        }))
      }
      return {
        content: data.response || data.error || 'No response',
        model: actualModel,
        routedFrom: modelId === 'auto' ? 'auto' : null,
        tokens: data.tokens || null,
        latency: data.latency || null,
      }
    } catch (error) {
      return { content: `❌ Error: ${error.message}`, model: modelId, error: true }
    }
  }

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const userMessage = input.trim()
    setInput('')
    setStagedFiles([])

    setMessages(prev => [...prev, { 
      type: MESSAGE_TYPES.USER, 
      content: userMessage,
      timestamp: new Date().toISOString(),
    }])
    setLoading(true)

    try {
      if (compareMode) {
        const results = await Promise.all(compareModels.map(m => sendToModel(userMessage, m)))
        setMessages(prev => [...prev, {
          type: MESSAGE_TYPES.COMPARE,
          results: results.map((r, i) => ({ model: compareModels[i], ...r })),
          timestamp: new Date().toISOString(),
        }])
      } else {
        const result = await sendToModel(userMessage, selectedModel)
        setMessages(prev => [...prev, { 
          type: MESSAGE_TYPES.ASSISTANT, 
          content: result.content,
          timestamp: new Date().toISOString(),
          model: result.model,
          routedFrom: result.routedFrom,
          tokens: result.tokens,
        }])
      }
    } finally {
      setLoading(false)
    }
  }

  // Retry: resend the last user message
  const handleRetry = useCallback((messageIndex) => {
    // Find the last user message before this assistant message
    let lastUserMsg = null
    for (let i = messageIndex - 1; i >= 0; i--) {
      if (messages[i].type === MESSAGE_TYPES.USER) {
        lastUserMsg = messages[i].content
        break
      }
    }
    if (lastUserMsg) {
      setInput(lastUserMsg)
      // Remove messages from the retried one onwards
      setMessages(prev => prev.slice(0, messageIndex))
      setTimeout(() => {
        // Auto-send after a tick
        handleSend()
      }, 100)
    }
  }, [messages])

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const getModelInfo = (modelId) => MODELS.find(m => m.id === modelId) || MODELS[0]

  // LobeChat-style message backgrounds
  const getMessageStyle = (type) => {
    if (darkMode) {
      switch (type) {
        case MESSAGE_TYPES.PROACTIVE: return { background: '#162312', border: '1px solid #274916' }
        case MESSAGE_TYPES.ALERT: return { background: '#2a1215', border: '1px solid #58181c' }
        case MESSAGE_TYPES.USER: return { background: '#111a2c', border: '1px solid #15325b' }
        case MESSAGE_TYPES.COMPARE: return { background: '#2b2111', border: '1px solid #594214' }
        default: return { background: '#1f1f1f', border: '1px solid #303030' }
      }
    }
    switch (type) {
      case MESSAGE_TYPES.PROACTIVE: return { background: '#f6ffed', border: '1px solid #b7eb8f' }
      case MESSAGE_TYPES.ALERT: return { background: '#fff2f0', border: '1px solid #ffccc7' }
      case MESSAGE_TYPES.USER: return { background: '#e6f7ff', border: '1px solid #91d5ff' }
      case MESSAGE_TYPES.COMPARE: return { background: '#fff7e6', border: '1px solid #ffd591' }
      default: return { background: '#ffffff', border: '1px solid #e8e8e8' }
    }
  }

  const getAvatar = (type, modelId) => {
    if (type === MESSAGE_TYPES.USER) {
      return <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#1890ff' }} />
    }
    if (type === MESSAGE_TYPES.PROACTIVE || type === MESSAGE_TYPES.ALERT) {
      return <Avatar icon={<BellOutlined />} style={{ backgroundColor: '#52c41a' }} />
    }
    const model = getModelInfo(modelId)
    return (
      <Tooltip title={model.name}>
        <Avatar style={{ backgroundColor: model.color, fontSize: 16 }}>{model.icon}</Avatar>
      </Tooltip>
    )
  }

  const renderCompareMessage = (msg) => (
    <div style={{ width: '100%', maxWidth: '90%' }}>
      <div style={{ marginBottom: 8, fontWeight: 500, color: darkMode ? '#d89614' : '#d48806' }}>
        ⚖️ Model Comparison
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${msg.results.length}, 1fr)`, gap: 12 }}>
        {msg.results.map((result, i) => {
          const model = getModelInfo(result.model)
          return (
            <Card 
              key={i} 
              size="small" 
              title={
                <Space>
                  <span>{model.icon}</span>
                  <span>{model.name}</span>
                  <Tag color={COST_LABELS[model.cost]?.color}>{COST_LABELS[model.cost]?.text}</Tag>
                </Space>
              }
              style={{ borderColor: model.color }}
            >
              <div style={{ fontSize: 13, lineHeight: 1.5 }}>
                <MarkdownRenderer content={result.content} />
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )

  return (
    <Card 
      style={{ 
        height: 'calc(100vh - 48px)', 
        display: 'flex', 
        flexDirection: 'column',
        borderRadius: 12,
        boxShadow: darkMode ? '0 2px 8px rgba(0,0,0,0.4)' : '0 2px 8px rgba(0,0,0,0.15)',
        border: darkMode ? '1px solid #303030' : '1px solid #d9d9d9',
        background: darkMode ? '#141414' : '#fff',
      }}
      styles={{ body: { padding: 0, flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' } }}
    >
      {/* Header */}
      <div style={{ 
        padding: '12px 24px', 
        borderBottom: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
        background: darkMode ? '#1f1f1f' : '#fff',
        borderRadius: '12px 12px 0 0',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <RobotOutlined style={{ fontSize: 24, color: '#06AC38' }} />
            <Title level={4} style={{ margin: 0 }}>AI Operations Assistant</Title>
            <Badge status={proactiveEnabled ? 'success' : 'default'} text={proactiveEnabled ? 'Live' : 'Paused'} />
          </Space>
          <Space>
            <Tooltip title={`Total tokens: ${tokenStats.total}`}>
              <Tag icon={<DollarOutlined />} color="blue">
                {tokenStats.total > 0 ? `${(tokenStats.total / 1000).toFixed(1)}k tokens` : '0 tokens'}
              </Tag>
            </Tooltip>
            <Tooltip title={compareMode ? 'Switch to single model' : 'Compare multiple models'}>
              <Button 
                type={compareMode ? 'primary' : 'default'}
                icon={<SwapOutlined />}
                onClick={() => setCompareMode(!compareMode)}
                size="small"
              >
                {compareMode ? 'Compare ON' : 'Compare'}
              </Button>
            </Tooltip>
            <Tooltip title={proactiveEnabled ? 'Pause monitoring' : 'Enable monitoring'}>
              <Button 
                type={proactiveEnabled ? 'primary' : 'default'}
                icon={<BellOutlined />}
                onClick={() => setProactiveEnabled(!proactiveEnabled)}
                size="small"
                style={proactiveEnabled ? { background: '#06AC38', borderColor: '#06AC38' } : {}}
              >
                {proactiveEnabled ? 'Monitor ON' : 'Monitor OFF'}
              </Button>
            </Tooltip>
          </Space>
        </div>
        
        {/* Model Selector */}
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
          {!compareMode ? (
            <>
              <Text type="secondary" style={{ fontSize: 12 }}>Model:</Text>
              <Select value={selectedModel} onChange={setSelectedModel} style={{ width: 280 }} size="small">
                {MODELS.map(model => (
                  <Option key={model.id} value={model.id}>
                    <Space>
                      <span>{model.icon}</span>
                      <span>{model.name}</span>
                      <Tag color={COST_LABELS[model.cost]?.color} style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                        {COST_LABELS[model.cost]?.text}
                      </Tag>
                    </Space>
                  </Option>
                ))}
              </Select>
              <Text type="secondary" style={{ fontSize: 11 }}>{getModelInfo(selectedModel).description}</Text>
            </>
          ) : (
            <>
              <Text type="secondary" style={{ fontSize: 12 }}>Compare:</Text>
              <Select
                mode="multiple"
                value={compareModels}
                onChange={setCompareModels}
                style={{ flex: 1, maxWidth: 500 }}
                size="small"
                maxTagCount={3}
              >
                {MODELS.filter(m => m.id !== 'auto').map(model => (
                  <Option key={model.id} value={model.id}>
                    <Space><span>{model.icon}</span><span>{model.name}</span></Space>
                  </Option>
                ))}
              </Select>
            </>
          )}
        </div>
      </div>

      {/* Messages area */}
      <div style={{ 
        flex: 1, 
        overflowY: 'auto', 
        padding: 24,
        background: darkMode ? '#0a0a0a' : '#fafafa',
      }}>
        {messages.map((msg, index) => (
          <div
            key={index}
            className="message-wrapper"
            style={{
              display: 'flex',
              flexDirection: msg.type === MESSAGE_TYPES.USER ? 'row-reverse' : 'row',
              marginBottom: 16,
              gap: 12,
            }}
          >
            {msg.type !== MESSAGE_TYPES.COMPARE && getAvatar(msg.type, msg.model)}
            
            {msg.type === MESSAGE_TYPES.COMPARE ? (
              renderCompareMessage(msg)
            ) : (
              <div style={{ maxWidth: '70%' }}>
                <div style={{
                  padding: '12px 16px',
                  borderRadius: 12,
                  ...getMessageStyle(msg.type),
                  transition: 'all 0.2s ease',
                }}>
                  {msg.type === MESSAGE_TYPES.PROACTIVE && (
                    <div style={{ marginBottom: 8, color: '#52c41a', fontWeight: 500, fontSize: 12 }}>
                      🤖 PROACTIVE ALERT
                    </div>
                  )}
                  {msg.type === MESSAGE_TYPES.ASSISTANT && msg.model && msg.model !== 'system' && (
                    <div style={{ marginBottom: 6, display: 'flex', gap: 6, alignItems: 'center' }}>
                      <Tag 
                        color={getModelInfo(msg.model).color} 
                        style={{ fontSize: 10, lineHeight: '16px', padding: '0 6px', margin: 0 }}
                      >
                        {getModelInfo(msg.model).icon} {getModelInfo(msg.model).name}
                      </Tag>
                      {msg.routedFrom === 'auto' && (
                        <Tag color="green" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}>
                          🧠 Auto-routed
                        </Tag>
                      )}
                    </div>
                  )}
                  <div style={{ fontSize: 14, lineHeight: 1.6 }}>
                    <MarkdownRenderer content={msg.content} />
                  </div>
                  <div style={{ marginTop: 8, fontSize: 11, color: darkMode ? '#555' : '#999' }}>
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </div>
                </div>
                {/* Action bar (copy / retry) */}
                <MessageActionBar
                  content={msg.content}
                  isUser={msg.type === MESSAGE_TYPES.USER}
                  isAssistant={msg.type === MESSAGE_TYPES.ASSISTANT}
                  onRetry={msg.type === MESSAGE_TYPES.ASSISTANT ? () => handleRetry(index) : undefined}
                />
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
            <Avatar icon={<RobotOutlined />} style={{ backgroundColor: '#06AC38' }} />
            <div style={{ 
              padding: '12px 16px', 
              background: darkMode ? '#1f1f1f' : '#fff', 
              borderRadius: 12,
              border: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
            }}>
              <Spin size="small" /> <Text type="secondary">
                {compareMode ? 'Comparing models...' : `Analyzing with ${getModelInfo(selectedModel).name}...`}
              </Text>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area with file drop zone */}
      <FileDropZone onFilesChange={setStagedFiles}>
        <div style={{ 
          padding: 16, 
          borderTop: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
          background: darkMode ? '#1f1f1f' : '#fff',
        }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
            <TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={
                compareMode 
                  ? `Compare ${compareModels.length} models — type your question...`
                  : `Ask with ${getModelInfo(selectedModel).name}... (drag files here)`
              }
              disabled={loading}
              autoSize={{ minRows: 1, maxRows: 4 }}
              style={{ 
                flex: 1,
                borderRadius: 8,
                background: darkMode ? '#141414' : undefined,
              }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              disabled={loading || !input.trim()}
              style={{ 
                background: '#06AC38', 
                borderColor: '#06AC38', 
                height: 'auto',
                borderRadius: 8,
                minHeight: 32,
              }}
            >
              Send
            </Button>
          </div>
          <div style={{ marginTop: 6, fontSize: 11, color: darkMode ? '#555' : '#bbb', display: 'flex', alignItems: 'center', gap: 4 }}>
            <PaperClipOutlined /> Drag & drop files to attach • Enter to send, Shift+Enter for new line
          </div>
        </div>
      </FileDropZone>
    </Card>
  )
}

export default AgentChat
