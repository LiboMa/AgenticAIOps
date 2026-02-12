/**
 * FileDropZone - LobeChat-style drag & drop file upload area
 * 
 * UI-only for now (backend file upload is P1).
 * Shows drag overlay + file chips when files are staged.
 */
import { useState, useCallback } from 'react'
import { Tag, message as antMessage, Typography } from 'antd'
import { InboxOutlined, FileOutlined, CloseOutlined, CloudUploadOutlined } from '@ant-design/icons'
import useThemeStore from '../stores/themeStore'

const { Text } = Typography

export default function FileDropZone({ children, onFilesChange }) {
  const [isDragging, setIsDragging] = useState(false)
  const [files, setFiles] = useState([])
  const darkMode = useThemeStore((s) => s.darkMode)

  const handleDragEnter = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    // Only set false if leaving the container, not entering a child
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

    const droppedFiles = Array.from(e.dataTransfer.files)
    if (droppedFiles.length === 0) return

    // Validate file sizes (max 10MB per file)
    const validFiles = droppedFiles.filter(f => {
      if (f.size > 10 * 1024 * 1024) {
        antMessage.warning(`${f.name} exceeds 10MB limit`)
        return false
      }
      return true
    })

    if (validFiles.length > 0) {
      const newFiles = [...files, ...validFiles]
      setFiles(newFiles)
      onFilesChange?.(newFiles)
      antMessage.info(`${validFiles.length} file(s) staged (upload coming in P1)`)
    }
  }, [files, onFilesChange])

  const removeFile = (index) => {
    const newFiles = files.filter((_, i) => i !== index)
    setFiles(newFiles)
    onFilesChange?.(newFiles)
  }

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  }

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
            Drop files here
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Supports logs, configs, screenshots (max 10MB)
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
        }}>
          {files.map((file, index) => (
            <Tag
              key={`${file.name}-${index}`}
              icon={<FileOutlined />}
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
              }}
            >
              {file.name} ({formatSize(file.size)})
            </Tag>
          ))}
        </div>
      )}

      {children}
    </div>
  )
}
