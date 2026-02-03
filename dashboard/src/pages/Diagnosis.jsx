import { useState, useRef, useEffect } from 'react'
import { Card, Button, Input, Space, message, Spin, Descriptions, Tag, Steps, Timeline, Row, Col, Typography, Avatar, Select } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import {
  SearchOutlined,
  BugOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  ExperimentOutlined,
  SendOutlined,
  RobotOutlined,
  UserOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'

const { TextArea } = Input
const { Title, Text } = Typography

// Inline ChatPanel for Diagnostics page
function DiagnosisChat({ apiUrl }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: `👋 **AI Diagnostics Assistant**

I can help you with:
- 🔍 Diagnose pods and deployments
- 📊 Analyze OOMKilled, CrashLoop issues
- 🛠️ Suggest remediation steps

Try: *"What's wrong with pod memory-hog in stress-test?"*`
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
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
        content: `❌ Error: ${error.message}`
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Messages */}
      <div style={{ 
        flex: 1, 
        overflowY: 'auto', 
        marginBottom: 12,
        padding: 12,
        background: '#fafafa',
        borderRadius: 8,
        minHeight: 400,
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
              size={28}
              icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
              style={{ 
                backgroundColor: msg.role === 'user' ? '#1890ff' : '#06AC38',
                flexShrink: 0,
              }}
            />
            <div
              style={{
                maxWidth: '85%',
                padding: '8px 12px',
                borderRadius: 8,
                background: msg.role === 'user' ? '#e6f7ff' : '#fff',
                border: `1px solid ${msg.role === 'user' ? '#91d5ff' : '#e8e8e8'}`,
                fontSize: 13,
              }}
            >
              {msg.role === 'assistant' ? (
                <div className="markdown-content" style={{ lineHeight: 1.5 }}>
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
              ) : (
                <Text>{msg.content}</Text>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display: 'flex', gap: 8 }}>
            <Avatar size={28} icon={<RobotOutlined />} style={{ backgroundColor: '#06AC38' }} />
            <div style={{ padding: '8px 16px', background: '#fff', borderRadius: 8 }}>
              <Spin size="small" /> <Text type="secondary">Analyzing...</Text>
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
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); handleSend(); } }}
          placeholder="Ask about cluster issues..."
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
    </div>
  )
}

function Diagnosis({ apiUrl }) {
  const [namespace, setNamespace] = useState('stress-test')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleDiagnosis = async () => {
    setLoading(true)
    setResult(null)
    
    try {
      const res = await fetch(`${apiUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: `Diagnose all issues in ${namespace} namespace` }),
      })
      const data = await res.json()
      
      if (data.error) {
        message.error(data.error)
      } else {
        setResult({ response: data.response, namespace, timestamp: new Date().toISOString() })
        message.success('Diagnosis completed')
      }
    } catch (err) {
      message.error('Diagnosis request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>AI Diagnostics</Title>
        <Text type="secondary">Analyze and troubleshoot cluster issues with AI assistance</Text>
      </div>

      <Row gutter={24}>
        {/* Left: Diagnostics Panel */}
        <Col xs={24} lg={14}>
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            {/* Quick Diagnosis */}
            <Card
              bordered={false}
              title={
                <Space>
                  <ExperimentOutlined style={{ color: '#06AC38' }} />
                  Quick Diagnosis
                </Space>
              }
            >
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <div>
                  <label style={{ color: '#666', marginBottom: 8, display: 'block' }}>
                    Target Namespace
                  </label>
                  <Space>
                    <Select
                      value={namespace}
                      onChange={setNamespace}
                      style={{ width: 200 }}
                      options={[
                        { value: 'stress-test', label: 'stress-test' },
                        { value: 'default', label: 'default' },
                        { value: 'production', label: 'production' },
                        { value: 'kube-system', label: 'kube-system' },
                      ]}
                    />
                    <Button
                      type="primary"
                      icon={loading ? <LoadingOutlined /> : <BugOutlined />}
                      onClick={handleDiagnosis}
                      loading={loading}
                      style={{ background: '#06AC38', borderColor: '#06AC38' }}
                    >
                      {loading ? 'Analyzing...' : 'Run Diagnosis'}
                    </Button>
                  </Space>
                </div>

                {loading && (
                  <Steps
                    current={1}
                    size="small"
                    items={[
                      { title: 'Collect Data', status: 'finish' },
                      { title: 'Analyze', status: 'process' },
                      { title: 'Report', status: 'wait' },
                    ]}
                  />
                )}
              </Space>
            </Card>

            {/* Results */}
            {result && (
              <Card bordered={false} title="Diagnosis Results">
                <Descriptions column={2} bordered size="small" style={{ marginBottom: 16 }}>
                  <Descriptions.Item label="Namespace">{result.namespace}</Descriptions.Item>
                  <Descriptions.Item label="Time">
                    {new Date(result.timestamp).toLocaleString()}
                  </Descriptions.Item>
                </Descriptions>
                <div style={{ 
                  background: '#f5f5f5', 
                  padding: 16, 
                  borderRadius: 8,
                  maxHeight: 400,
                  overflow: 'auto',
                }}>
                  <div className="markdown-content">
                    <ReactMarkdown>{result.response}</ReactMarkdown>
                  </div>
                </div>
              </Card>
            )}
          </Space>
        </Col>

        {/* Right: AI Chat */}
        <Col xs={24} lg={10}>
          <Card
            bordered={false}
            title={
              <Space>
                <RobotOutlined style={{ color: '#06AC38' }} />
                AI Assistant
              </Space>
            }
            bodyStyle={{ padding: 12 }}
            style={{ height: 'calc(100vh - 220px)', minHeight: 500 }}
          >
            <DiagnosisChat apiUrl={apiUrl} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Diagnosis
