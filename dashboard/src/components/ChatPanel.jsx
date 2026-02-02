import { useState, useRef, useEffect } from 'react'
import {
  Box, Paper, TextField, IconButton, Typography, Avatar,
  List, ListItem, ListItemAvatar, ListItemText, CircularProgress
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import PersonIcon from '@mui/icons-material/Person'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function ChatPanel() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hello! I\'m your EKS AIOps assistant. How can I help you today?\n\nYou can ask me things like:\n- "What pods are having issues?"\n- "Check the cluster health"\n- "Why is my pod crashing?"'
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
      const response = await axios.post(`${API_URL}/api/chat`, {
        message: userMessage
      })
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: response.data.response 
      }])
    } catch (error) {
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: `Error: ${error.message}. Make sure the backend API is running.`
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
    <Box sx={{ height: 'calc(100vh - 200px)', display: 'flex', flexDirection: 'column' }}>
      <Paper sx={{ flexGrow: 1, overflow: 'auto', p: 2, mb: 2, backgroundColor: '#0d1117' }}>
        <List>
          {messages.map((msg, index) => (
            <ListItem key={index} alignItems="flex-start" sx={{ 
              flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'
            }}>
              <ListItemAvatar sx={{ minWidth: 40 }}>
                <Avatar sx={{ 
                  bgcolor: msg.role === 'user' ? '#0066cc' : '#ff9900',
                  width: 32, 
                  height: 32 
                }}>
                  {msg.role === 'user' ? <PersonIcon fontSize="small" /> : <SmartToyIcon fontSize="small" />}
                </Avatar>
              </ListItemAvatar>
              <ListItemText
                primary={
                  <Paper sx={{ 
                    p: 1.5, 
                    backgroundColor: msg.role === 'user' ? '#0d4a8a' : '#21262d',
                    maxWidth: '80%',
                    display: 'inline-block'
                  }}>
                    <Typography 
                      variant="body2" 
                      sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}
                    >
                      {msg.content}
                    </Typography>
                  </Paper>
                }
              />
            </ListItem>
          ))}
          {loading && (
            <ListItem>
              <ListItemAvatar sx={{ minWidth: 40 }}>
                <Avatar sx={{ bgcolor: '#ff9900', width: 32, height: 32 }}>
                  <SmartToyIcon fontSize="small" />
                </Avatar>
              </ListItemAvatar>
              <CircularProgress size={20} sx={{ color: '#ff9900' }} />
            </ListItem>
          )}
          <div ref={messagesEndRef} />
        </List>
      </Paper>

      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField
          fullWidth
          multiline
          maxRows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Ask about your EKS cluster..."
          disabled={loading}
          sx={{ 
            '& .MuiOutlinedInput-root': {
              backgroundColor: '#21262d'
            }
          }}
        />
        <IconButton 
          onClick={handleSend} 
          disabled={loading || !input.trim()}
          sx={{ 
            backgroundColor: '#ff9900',
            '&:hover': { backgroundColor: '#ec7211' },
            '&:disabled': { backgroundColor: '#333' }
          }}
        >
          <SendIcon />
        </IconButton>
      </Box>
    </Box>
  )
}

export default ChatPanel
