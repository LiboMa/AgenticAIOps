import { useState, useRef, useEffect } from 'react'
import { Input, Button, Avatar, Spin, Card, Typography, Space, message as antMessage } from 'antd'
import { SendOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'

const { TextArea } = Input
const { Text } = Typography

function ChatPanelPD({ apiUrl }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: `👋 **Hello! I'm your AIOps Assistant.**

I can help you with:
- 🔍 Diagnose cluster issues
- 📊 Check pod/node status
- 🛠️ Analyze OOMKilled, CrashLoop errors
- 💡 Provide remediation suggestions

Try asking: *"What pods are having issues in stress-test namespace?"*`
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || loading) return

    const userMessage = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setLoading(true)

    try {
      const response = await fetch(`${apiUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage })
      })
      const data = await response.json()
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: data.response || data.error || 'No response'
      }])
    } catch (error) {
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: `❌ Error: ${error.message}. Make sure the backend API is running.`
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

  return (
    <Card 
      title={
        <Space>
          <RobotOutlined style={{ color: '#06AC38' }} />
          <span>AI Assistant</span>
        </Space>
      }
      bordered={false}
      style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
      bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 12, overflow: 'hidden' }}
    >
      {/* Messages */}
      <div style={{ 
        flex: 1, 
        overflowY: 'auto', 
        marginBottom: 12,
        padding: 8,
        background: '#fafafa',
        borderRadius: 8,
      }}>
        {messages.map((msg, index) => (
          <div
            key={index}
            style={{
              display: 'flex',
              flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
              marginBottom: 12,
              gap: 8,
            }}
          >
            <Avatar 
              size={32}
              icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
              style={{ 
                backgroundColor: msg.role === 'user' ? '#1890ff' : '#06AC38',
                flexShrink: 0,
              }}
            />
            <div
              style={{
                maxWidth: '80%',
                padding: '8px 12px',
                borderRadius: 8,
                background: msg.role === 'user' ? '#e6f7ff' : '#fff',
                border: `1px solid ${msg.role === 'user' ? '#91d5ff' : '#e8e8e8'}`,
              }}
            >
              {msg.role === 'assistant' ? (
                <div className="markdown-content" style={{ fontSize: 13, lineHeight: 1.6 }}>
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
              ) : (
                <Text style={{ fontSize: 13 }}>{msg.content}</Text>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <Avatar 
              size={32}
              icon={<RobotOutlined />}
              style={{ backgroundColor: '#06AC38' }}
            />
            <div style={{ padding: '8px 16px', background: '#fff', borderRadius: 8 }}>
              <Spin size="small" /> <Text type="secondary">Thinking...</Text>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ display: 'flex', gap: 8 }}>
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Ask about your cluster..."
          disabled={loading}
          autoSize={{ minRows: 1, maxRows: 3 }}
          style={{ flex: 1 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          disabled={loading || !input.trim()}
          style={{ background: '#06AC38', borderColor: '#06AC38' }}
        />
      </div>
    </Card>
  )
}

export default ChatPanelPD
