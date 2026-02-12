/**
 * MarkdownRenderer - LobeChat-style enhanced Markdown rendering
 * 
 * Features:
 * - Syntax-highlighted code blocks with language label + copy button
 * - Styled tables with zebra striping
 * - Inline code styling
 * - Dark mode aware
 */
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Button, message as antMessage, Typography } from 'antd'
import { CopyOutlined, CheckOutlined } from '@ant-design/icons'
import useThemeStore from '../stores/themeStore'

const { Text } = Typography

// Code block with copy button & language label (LobeChat style)
function CodeBlock({ language, children }) {
  const [copied, setCopied] = useState(false)
  const darkMode = useThemeStore((s) => s.darkMode)
  const codeString = String(children).replace(/\n$/, '')

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(codeString)
      setCopied(true)
      antMessage.success('Copied!')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      antMessage.error('Copy failed')
    }
  }

  return (
    <div style={{
      position: 'relative',
      borderRadius: 8,
      overflow: 'hidden',
      margin: '12px 0',
      border: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
    }}>
      {/* Header bar with language + copy */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '6px 12px',
        background: darkMode ? '#1e1e1e' : '#f0f0f0',
        borderBottom: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
        fontSize: 12,
      }}>
        <Text type="secondary" style={{ 
          fontFamily: 'monospace', 
          fontSize: 11, 
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
          color: darkMode ? '#888' : undefined,
        }}>
          {language || 'text'}
        </Text>
        <Button
          type="text"
          size="small"
          icon={copied ? <CheckOutlined style={{ color: '#52c41a' }} /> : <CopyOutlined />}
          onClick={handleCopy}
          style={{ 
            fontSize: 12, 
            height: 24,
            color: darkMode ? '#aaa' : undefined,
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <SyntaxHighlighter
        language={language || 'text'}
        style={darkMode ? oneDark : oneLight}
        customStyle={{
          margin: 0,
          padding: '16px',
          fontSize: 13,
          lineHeight: 1.6,
          background: darkMode ? '#141414' : '#fafafa',
          borderRadius: 0,
        }}
        wrapLongLines
      >
        {codeString}
      </SyntaxHighlighter>
    </div>
  )
}

// Inline code styling
function InlineCode({ children }) {
  const darkMode = useThemeStore((s) => s.darkMode)
  return (
    <code style={{
      padding: '2px 6px',
      borderRadius: 4,
      fontSize: '0.9em',
      fontFamily: '"SF Mono", "Fira Code", "Fira Mono", Menlo, Consolas, monospace',
      background: darkMode ? '#2a2a2a' : '#f5f5f5',
      border: darkMode ? '1px solid #404040' : '1px solid #e8e8e8',
      color: darkMode ? '#e06c75' : '#c41d7f',
    }}>
      {children}
    </code>
  )
}

// Styled table (LobeChat style)
function StyledTable({ children }) {
  const darkMode = useThemeStore((s) => s.darkMode)
  return (
    <div style={{ 
      overflowX: 'auto', 
      margin: '12px 0',
      borderRadius: 8,
      border: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
    }}>
      <table style={{
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: 13,
        lineHeight: 1.6,
      }}>
        {children}
      </table>
    </div>
  )
}

function StyledThead({ children }) {
  const darkMode = useThemeStore((s) => s.darkMode)
  return (
    <thead style={{
      background: darkMode ? '#1e1e1e' : '#fafafa',
      borderBottom: darkMode ? '2px solid #303030' : '2px solid #e8e8e8',
    }}>
      {children}
    </thead>
  )
}

function StyledTr({ children, isHeader }) {
  const darkMode = useThemeStore((s) => s.darkMode)
  if (isHeader) return <tr>{children}</tr>
  return (
    <tr style={{
      borderBottom: darkMode ? '1px solid #252525' : '1px solid #f0f0f0',
    }}>
      {children}
    </tr>
  )
}

function StyledTh({ children }) {
  const darkMode = useThemeStore((s) => s.darkMode)
  return (
    <th style={{
      padding: '10px 16px',
      textAlign: 'left',
      fontWeight: 600,
      fontSize: 12,
      textTransform: 'uppercase',
      letterSpacing: '0.3px',
      color: darkMode ? '#aaa' : '#666',
    }}>
      {children}
    </th>
  )
}

function StyledTd({ children }) {
  const darkMode = useThemeStore((s) => s.darkMode)
  return (
    <td style={{
      padding: '10px 16px',
      color: darkMode ? '#d4d4d4' : '#333',
    }}>
      {children}
    </td>
  )
}

// Main Markdown Renderer
export default function MarkdownRenderer({ content }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ node, inline, className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || '')
          if (!inline && match) {
            return <CodeBlock language={match[1]}>{children}</CodeBlock>
          }
          if (!inline && String(children).includes('\n')) {
            return <CodeBlock language="">{children}</CodeBlock>
          }
          return <InlineCode {...props}>{children}</InlineCode>
        },
        table({ children }) {
          return <StyledTable>{children}</StyledTable>
        },
        thead({ children }) {
          return <StyledThead>{children}</StyledThead>
        },
        tr({ children, isHeader }) {
          return <StyledTr isHeader={isHeader}>{children}</StyledTr>
        },
        th({ children }) {
          return <StyledTh>{children}</StyledTh>
        },
        td({ children }) {
          return <StyledTd>{children}</StyledTd>
        },
        // Styled links
        a({ children, href }) {
          return (
            <a href={href} target="_blank" rel="noopener noreferrer" style={{
              color: '#06AC38',
              textDecoration: 'none',
              borderBottom: '1px dashed #06AC38',
            }}>
              {children}
            </a>
          )
        },
        // Blockquotes
        blockquote({ children }) {
          return (
            <blockquote style={{
              margin: '12px 0',
              padding: '8px 16px',
              borderLeft: '4px solid #06AC38',
              background: 'rgba(6, 172, 56, 0.05)',
              borderRadius: '0 8px 8px 0',
            }}>
              {children}
            </blockquote>
          )
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
