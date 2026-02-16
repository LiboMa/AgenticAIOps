/**
 * FileDropZone - Drag & drop file upload with actual file reading
 *
 * Reads file content as text, stores in staged files for sending.
 */
import { useState, useCallback, useRef } from 'react'
import { Tag, message as antMessage, Typography, Button, Tooltip } from 'antd'
import { InboxOutlined, FileOutlined, FileTextOutlined, FileImageOutlined, FilePdfOutlined, CloseOutlined, CloudUploadOutlined, PaperClipOutlined } from '@ant-design/icons'
import useThemeStore from '../stores/themeStore'

const { Text } = Typography

const getFileIcon = (filename) => {
  const ext = filename?.split('.').pop()?.toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) return <FileImageOutlined style={{ color: '#52c41a' }} />
  if (['pdf'].includes(ext)) return <FilePdfOutlined style={{ color: '#ff4d4f' }} />
  if (['txt', 'md', 'log', 'yaml', 'yml', 'json', 'xml', 'csv', 'conf', 'cfg', 'ini', 'sh', 'py', 'js', 'ts'].includes(ext)) return <FileTextOutlined style={{ color: '#1890ff' }} />
  return <FileOutlined style={{ color: '#666' }} />
}

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB

export default function FileDropZone({ children, onFilesChange }) {
  const [isDragging, setIsDragging] = useState(false)
  const [files, setFiles] = useState([])
  const darkMode = useThemeStore((s) => s.darkMode)
  const fileInputRef = useRef(null)

  const processFile = useCallback((file) => {
    if (file.size > MAX_FILE_SIZE) {
      antMessage.warning(`${file.name} exceeds 10MB limit`)
      return
    }

    // Read file content
    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target.result
      const fileObj = {
        name: file.name,
        size: file.size,
        type: file.type,
        content: typeof content === 'string' ? content.substring(0, 50000) : '',
        raw: file, // Keep raw File for FormData upload
      }
      setFiles(prev => {
        const next = [...prev, fileObj]
        onFilesChange?.(next)
        return next
      })
      antMessage.success(`${file.name} attached`)
    }
    reader.onerror = () => antMessage.error(`Failed to read ${file.name}`)

    // Use readAsText for text files, readAsDataURL for images
    const ext = file.name.split('.').pop()?.toLowerCase()
    const imageExts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
    if (imageExts.includes(ext)) {
      reader.readAsDataURL(file)
    } else {
      reader.readAsText(file)
    }
  }, [onFilesChange])

  const handleDragEnter = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.currentTarget.contains(e.relatedTarget)) return
    setIsDragging(false)
  }, [])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    Array.from(e.dataTransfer.files).forEach(processFile)
  }, [processFile])

  const handleFileSelect = useCallback((e) => {
    Array.from(e.target.files).forEach(processFile)
    e.target.value = '' // Reset input
  }, [processFile])

  const removeFile = (index) => {
    setFiles(prev => {
      const next = prev.filter((_, i) => i !== index)
      onFilesChange?.(next)
      return next
    })
  }

  const clearFiles = () => {
    setFiles([])
    onFilesChange?.([])
  }

  // Expose clearFiles via ref
  FileDropZone.clearFiles = clearFiles

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      style={{ position: 'relative' }}
    >
      {/* Drag overlay */}
      {isDragging && (
        <div style={{
          position: 'absolute',
          inset: 0,
          zIndex: 100,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          background: darkMode
            ? 'rgba(6, 172, 56, 0.15)'
            : 'rgba(6, 172, 56, 0.08)',
          border: '2px dashed #06AC38',
          borderRadius: 12,
          backdropFilter: 'blur(4px)',
        }}>
          <CloudUploadOutlined style={{ fontSize: 48, color: '#06AC38' }} />
          <Text strong style={{ fontSize: 16, color: '#06AC38' }}>
            Drop files here to attach
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Supports logs, configs, YAML, JSON, scripts (max 10MB)
          </Text>
        </div>
      )}

      {/* File chips */}
      {files.length > 0 && (
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 6,
          padding: '8px 12px',
          borderBottom: darkMode ? '1px solid #303030' : '1px solid #f0f0f0',
          background: darkMode ? '#1a1a1a' : '#f9f9f9',
          alignItems: 'center',
        }}>
          {files.map((file, index) => (
            <Tag
              key={`${file.name}-${index}`}
              icon={getFileIcon(file.name)}
              closable
              onClose={() => removeFile(index)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                padding: '4px 8px',
                borderRadius: 6,
                background: darkMode ? '#1e1e1e' : '#f5f5f5',
                border: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
                fontSize: 12,
                maxWidth: 200,
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {file.name}
              </span>
              <span style={{ color: '#999', flexShrink: 0 }}>({formatSize(file.size)})</span>
            </Tag>
          ))}
          {files.length > 1 && (
            <Button type="link" size="small" onClick={clearFiles} style={{ fontSize: 11, padding: 0 }}>
              Clear all
            </Button>
          )}
        </div>
      )}

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".txt,.log,.yaml,.yml,.json,.md,.csv,.xml,.conf,.cfg,.ini,.sh,.py,.js,.ts,.jsx,.tsx,.html,.sql,.toml,.env,.tf,.hcl"
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

      {children}
    </div>
  )
}

// Export helper to open file picker programmatically
FileDropZone.triggerFilePicker = null
