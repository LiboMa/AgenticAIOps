import { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Button, Avatar, Spin, Card, Typography, Space, Badge, Tooltip, message as antMessage } from 'antd'
import { SendOutlined, RobotOutlined, UserOutlined, BellOutlined, SettingOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'

const { TextArea } = Input
const { Text, Title } = Typography

// Proactive message types
const MESSAGE_TYPES = {
  USER: 'user',
  ASSISTANT: 'assistant',
  PROACTIVE: 'proactive',  // Agent-initiated messages
  ALERT: 'alert',          // Urgent alerts
}

function AgentChat({ apiUrl, onNewAlert }) {
  const [messages, setMessages] = useState([
    {
      type: MESSAGE_TYPES.ASSISTANT,
      content: `👋 **Welcome to AgenticAIOps!**

I'm your AI Operations Assistant. I'll **proactively** monitor your AWS resources and alert you when issues arise.

**What I do:**
- 🔍 Continuous anomaly detection
- 🔬 Root cause analysis (RCA)
- 🔒 Security monitoring
- 📊 Periodic health reports

**Try asking:**
- "Scan my AWS resources"
- "Show current issues"
- "Analyze security status"

I'll also notify you automatically when I detect problems. No need to ask! 🚀`,
      timestamp: new Date().toISOString(),
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [proactiveEnabled, setProactiveEnabled] = useState(true)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Simulate proactive agent messages (in real impl, this would be WebSocket)
  useEffect(() => {
    if (!proactiveEnabled) return
    
    // Simulate a heartbeat check after 30 seconds
    const heartbeatTimer = setTimeout(() => {
      const proactiveMsg = {
        type: MESSAGE_TYPES.PROACTIVE,
        content: `🔔 **Heartbeat Check Complete**

Scanned 5 AWS services:
- ✅ EC2: 4 running, 1 stopped
- ✅ Lambda: 5 functions healthy
- ⚠️ S3: 1 bucket with public access
- ✅ RDS: 3 instances available

**1 issue detected** - Added to Observability List.

[View Details →](/observability)`,
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, proactiveMsg])
      onNewAlert?.()
    }, 30000)

    return () => clearTimeout(heartbeatTimer)
  }, [proactiveEnabled, onNewAlert])

  const handleSend = async () => {
    if (!input.trim() || loading) return

    const userMessage = input.trim()
    setInput('')
    
    setMessages(prev => [...prev, { 
      type: MESSAGE_TYPES.USER, 
      content: userMessage,
      timestamp: new Date().toISOString(),
    }])
    setLoading(true)

    try {
      const response = await fetch(`${apiUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage })
      })
      const data = await response.json()
      
      setMessages(prev => [...prev, { 
        type: MESSAGE_TYPES.ASSISTANT, 
        content: data.response || data.error || 'No response',
        timestamp: new Date().toISOString(),
      }])
    } catch (error) {
      setMessages(prev => [...prev, { 
        type: MESSAGE_TYPES.ASSISTANT, 
        content: `❌ Error: ${error.message}. Make sure the backend is running.`,
        timestamp: new Date().toISOString(),
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const getMessageStyle = (type) => {
    switch (type) {
      case MESSAGE_TYPES.PROACTIVE:
        return { background: '#f6ffed', border: '1px solid #b7eb8f' }
      case MESSAGE_TYPES.ALERT:
        return { background: '#fff2f0', border: '1px solid #ffccc7' }
      case MESSAGE_TYPES.USER:
        return { background: '#e6f7ff', border: '1px solid #91d5ff' }
      default:
        return { background: '#fff', border: '1px solid #e8e8e8' }
    }
  }

  const getAvatar = (type) => {
    if (type === MESSAGE_TYPES.USER) {
      return <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#1890ff' }} />
    }
    if (type === MESSAGE_TYPES.PROACTIVE || type === MESSAGE_TYPES.ALERT) {
      return <Avatar icon={<BellOutlined />} style={{ backgroundColor: '#52c41a' }} />
    }
    return <Avatar icon={<RobotOutlined />} style={{ backgroundColor: '#06AC38' }} />
  }

  return (
    <Card 
      style={{ 
        height: '100%', 
        display: 'flex', 
        flexDirection: 'column',
        borderRadius: 12,
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
      }}
      bodyStyle={{ padding: 0, flex: 1, display: 'flex', flexDirection: 'column' }}
    >
      {/* Header */}
      <div style={{ 
        padding: '16px 24px', 
        borderBottom: '1px solid #e8e8e8',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: '#fff',
        borderRadius: '12px 12px 0 0',
      }}>
        <Space>
          <RobotOutlined style={{ fontSize: 24, color: '#06AC38' }} />
          <Title level={4} style={{ margin: 0 }}>AI Operations Assistant</Title>
          <Badge status={proactiveEnabled ? 'success' : 'default'} text={proactiveEnabled ? 'Monitoring' : 'Paused'} />
        </Space>
        <Tooltip title={proactiveEnabled ? 'Pause proactive monitoring' : 'Enable proactive monitoring'}>
          <Button 
            type={proactiveEnabled ? 'primary' : 'default'}
            icon={<BellOutlined />}
            onClick={() => setProactiveEnabled(!proactiveEnabled)}
            style={proactiveEnabled ? { background: '#06AC38', borderColor: '#06AC38' } : {}}
          >
            {proactiveEnabled ? 'Proactive ON' : 'Proactive OFF'}
          </Button>
        </Tooltip>
      </div>

      {/* Messages */}
      <div style={{ 
        flex: 1, 
        overflowY: 'auto', 
        padding: 24,
        background: '#fafafa',
      }}>
        {messages.map((msg, index) => (
          <div
            key={index}
            style={{
              display: 'flex',
              flexDirection: msg.type === MESSAGE_TYPES.USER ? 'row-reverse' : 'row',
              marginBottom: 16,
              gap: 12,
            }}
          >
            {getAvatar(msg.type)}
            <div style={{
              maxWidth: '70%',
              padding: '12px 16px',
              borderRadius: 8,
              ...getMessageStyle(msg.type),
            }}>
              {msg.type === MESSAGE_TYPES.PROACTIVE && (
                <div style={{ marginBottom: 8, color: '#52c41a', fontWeight: 500, fontSize: 12 }}>
                  🤖 PROACTIVE ALERT
                </div>
              )}
              <div className="markdown-content" style={{ fontSize: 14, lineHeight: 1.6 }}>
                <ReactMarkdown>{msg.content}</ReactMarkdown>
              </div>
              <div style={{ marginTop: 8, fontSize: 11, color: '#999' }}>
                {new Date(msg.timestamp).toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
            <Avatar icon={<RobotOutlined />} style={{ backgroundColor: '#06AC38' }} />
            <div style={{ padding: '12px 16px', background: '#fff', borderRadius: 8 }}>
              <Spin size="small" /> <Text type="secondary">Analyzing...</Text>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ 
        padding: 16, 
        borderTop: '1px solid #e8e8e8',
        background: '#fff',
      }}>
        <div style={{ display: 'flex', gap: 12 }}>
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Ask about your infrastructure, or I'll alert you proactively..."
            disabled={loading}
            autoSize={{ minRows: 1, maxRows: 4 }}
            style={{ flex: 1 }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={loading || !input.trim()}
            style={{ background: '#06AC38', borderColor: '#06AC38', height: 'auto' }}
          >
            Send
          </Button>
        </div>
      </div>
    </Card>
  )
}

export default AgentChat
