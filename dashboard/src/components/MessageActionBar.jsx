/**
 * MessageActionBar - LobeChat-style hover action bar for messages
 * 
 * Shows copy/retry buttons on hover for each message bubble.
 */
import { useState } from 'react'
import { Button, Tooltip, message as antMessage } from 'antd'
import { CopyOutlined, ReloadOutlined, CheckOutlined } from '@ant-design/icons'
import useThemeStore from '../stores/themeStore'

export default function MessageActionBar({ content, onRetry, isUser, isAssistant }) {
  const [copied, setCopied] = useState(false)
  const darkMode = useThemeStore((s) => s.darkMode)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      antMessage.success('Copied to clipboard')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      antMessage.error('Copy failed')
    }
  }

  const buttonStyle = {
    color: darkMode ? '#888' : '#999',
    borderColor: 'transparent',
    background: 'transparent',
  }

  return (
    <div
      className="message-action-bar"
      style={{
        display: 'flex',
        gap: 2,
        marginTop: 4,
        opacity: 0,
        transition: 'opacity 0.2s ease',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
      }}
    >
      <Tooltip title={copied ? 'Copied!' : 'Copy'}>
        <Button
          type="text"
          size="small"
          icon={copied
            ? <CheckOutlined style={{ color: '#52c41a', fontSize: 13 }} />
            : <CopyOutlined style={{ fontSize: 13 }} />}
          onClick={handleCopy}
          style={buttonStyle}
        />
      </Tooltip>
      {isAssistant && onRetry && (
        <Tooltip title="Retry">
          <Button
            type="text"
            size="small"
            icon={<ReloadOutlined style={{ fontSize: 13 }} />}
            onClick={onRetry}
            style={buttonStyle}
          />
        </Tooltip>
      )}
    </div>
  )
}
