import { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Button, Avatar, Spin, Card, Typography, Space, message as antMessage, Upload, Tooltip } from 'antd'
import { SendOutlined, RobotOutlined, UserOutlined, PaperClipOutlined, InboxOutlined, CloseOutlined, FileOutlined, FilePdfOutlined, FileImageOutlined, FileTextOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'

const { TextArea } = Input
const { Text } = Typography
const { Dragger } = Upload

// Get file icon based on type
const getFileIcon = (filename) => {
  const ext = filename?.split('.').pop()?.toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) return <FileImageOutlined style={{ color: '#52c41a' }} />
  if (['pdf'].includes(ext)) return <FilePdfOutlined style={{ color: '#ff4d4f' }} />
  if (['txt', 'md', 'log', 'yaml', 'yml', 'json'].includes(ext)) return <FileTextOutlined style={{ color: '#1890ff' }} />
  return <FileOutlined style={{ color: '#666' }} />
}

function ChatPanelPD({ apiUrl }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: `👋 **Hello! I'm your AIOps Assistant.**

I can help you with:
- 🔍 Diagnose cluster issues
- 📊 Check pod/node status
- 🛠️ Analyze OOMKilled, CrashLoop errors
- 📁 Analyze uploaded files (logs, configs, YAML)
- 💡 Provide remediation suggestions

Try asking: *"What pods are having issues in stress-test namespace?"*

**Tip:** You can drag & drop files or click 📎 to upload logs for analysis!`
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [uploadedFiles, setUploadedFiles] = useState([])
  const [isDragging, setIsDragging] = useState(false)
  const messagesEndRef = useRef(null)
  const fileInputRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Handle file upload
  const handleFileUpload = useCallback(async (file) => {
    const maxSize = 5 * 1024 * 1024 // 5MB
    if (file.size > maxSize) {
      antMessage.error(`File ${file.name} is too large (max 5MB)`)
      return false
    }

    // Read file content
    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target.result
      setUploadedFiles(prev => [...prev, {
        name: file.name,
        size: file.size,
        type: file.type,
        content: content.substring(0, 50000), // Limit content size
      }])
      antMessage.success(`File "${file.name}" uploaded`)
    }
    reader.readAsText(file)
    return false // Prevent default upload behavior
  }, [])

  // Handle drag events
  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    files.forEach(handleFileUpload)
  }, [handleFileUpload])

  // Remove uploaded file
  const removeFile = (index) => {
    setUploadedFiles(prev => prev.filter((_, i) => i !== index))
  }

  const handleSend = async () => {
    if ((!input.trim() && uploadedFiles.length === 0) || loading) return

    const userMessage = input.trim()
    const files = [...uploadedFiles]
    
    setInput('')
    setUploadedFiles([])
    
    // Build message with file info
    let displayMessage = userMessage
    if (files.length > 0) {
      displayMessage += files.length > 0 && userMessage ? '\n\n' : ''
      displayMessage += files.map(f => `📎 ${f.name}`).join('\n')
    }
    
    setMessages(prev => [...prev, { role: 'user', content: displayMessage }])
    setLoading(true)

    try {
      // Build request with file content
      let fullMessage = userMessage
      if (files.length > 0) {
        fullMessage += '\n\n--- Attached Files ---\n'
        files.forEach(f => {
          fullMessage += `\n### File: ${f.name}\n\`\`\`\n${f.content.substring(0, 10000)}\n\`\`\`\n`
        })
        if (!userMessage) {
          fullMessage = `Please analyze the following uploaded file(s):\n${fullMessage}`
        }
      }

      const response = await fetch(`${apiUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: fullMessage })
      })
      const data = await response.json()
      
      // Check for A2UI action
      let assistantMessage = data.response || data.error || 'No response'
      if (data.ui_action && data.ui_action.action === 'add_widget') {
        const widget = data.ui_action.widget
        assistantMessage += `\n\n✅ **Widget Created!**\n- Type: ${widget.type}\n- Title: ${widget.config?.title || 'Untitled'}\n\n*Go to **Cloud Services** → Dashboard to see it, or I can add more widgets!*`
        
        // Store widget for potential use
        if (window.addDashboardWidget) {
          window.addDashboardWidget(widget)
        }
      }
      
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: assistantMessage
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

  const uploadProps = {
    beforeUpload: handleFileUpload,
    showUploadList: false,
    multiple: true,
    accept: '.txt,.log,.yaml,.yml,.json,.md,.csv,.xml,.conf,.cfg,.ini,.sh,.py,.js',
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
      {/* Messages with drag-drop zone */}
      <div 
        style={{ 
          flex: 1, 
          overflowY: 'auto', 
          marginBottom: 12,
          padding: 8,
          background: isDragging ? '#e6f7ff' : '#fafafa',
          borderRadius: 8,
          border: isDragging ? '2px dashed #06AC38' : '2px solid transparent',
          transition: 'all 0.2s',
          position: 'relative',
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {/* Drag overlay */}
        {isDragging && (
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(6, 172, 56, 0.1)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10,
            borderRadius: 8,
          }}>
            <div style={{ textAlign: 'center' }}>
              <InboxOutlined style={{ fontSize: 48, color: '#06AC38' }} />
              <div style={{ marginTop: 8, color: '#06AC38', fontWeight: 500 }}>
                Drop files here to upload
              </div>
            </div>
          </div>
        )}

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
                <Text style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{msg.content}</Text>
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

      {/* Uploaded files preview */}
      {uploadedFiles.length > 0 && (
        <div style={{ 
          marginBottom: 8, 
          padding: 8, 
          background: '#f0f5ff', 
          borderRadius: 4,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 8,
        }}>
          {uploadedFiles.map((file, index) => (
            <div 
              key={index}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                background: '#fff',
                padding: '4px 8px',
                borderRadius: 4,
                border: '1px solid #d9d9d9',
                fontSize: 12,
              }}
            >
              {getFileIcon(file.name)}
              <span style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {file.name}
              </span>
              <CloseOutlined 
                style={{ cursor: 'pointer', color: '#999', fontSize: 10 }} 
                onClick={() => removeFile(index)}
              />
            </div>
          ))}
        </div>
      )}

      {/* Input with file upload */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <Upload {...uploadProps}>
          <Tooltip title="Upload file for analysis">
            <Button 
              icon={<PaperClipOutlined />} 
              style={{ borderColor: '#d9d9d9' }}
            />
          </Tooltip>
        </Upload>
        <TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Ask about your cluster or drop files here..."
          disabled={loading}
          autoSize={{ minRows: 1, maxRows: 3 }}
          style={{ flex: 1 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          disabled={loading || (!input.trim() && uploadedFiles.length === 0)}
          style={{ background: '#06AC38', borderColor: '#06AC38' }}
        />
      </div>
    </Card>
  )
}

export default ChatPanelPD
