/**
 * AgenticAIOps v2 - Agent-First Architecture
 * 
 * Enhanced with:
 * - Dark mode toggle (Antd theme.darkAlgorithm)
 * - LobeChat-inspired layout
 */

import { useState, useEffect, lazy, Suspense } from 'react'
import { ConfigProvider, Layout, Menu, Badge, Button, Space, Spin, theme, Tooltip, Switch } from 'antd'
import {
  RobotOutlined,
  AlertOutlined,
  SafetyCertificateOutlined,
  BellOutlined,
  ScanOutlined,
  MoonOutlined,
  SunOutlined,
} from '@ant-design/icons'
import useThemeStore from './stores/themeStore'

// Lazy load pages
const AgentChat = lazy(() => import('./pages/AgentChat'))
const ObservabilityList = lazy(() => import('./pages/ObservabilityList'))
const SecurityDashboard = lazy(() => import('./pages/SecurityDashboard'))
const ScanConfig = lazy(() => import('./pages/ScanConfig'))

const { Content, Sider } = Layout

// Loading component
const PageLoading = ({ darkMode }) => (
  <div style={{ 
    display: 'flex', 
    justifyContent: 'center', 
    alignItems: 'center', 
    height: '100%',
    background: darkMode ? '#0a0a0a' : '#f5f7fa',
  }}>
    <Spin size="large" tip="Loading..." />
  </div>
)

function App() {
  const [currentPage, setCurrentPage] = useState('chat')
  const [alertCount, setAlertCount] = useState(0)
  const [collapsed, setCollapsed] = useState(false)
  
  const darkMode = useThemeStore((s) => s.darkMode)
  const toggleDarkMode = useThemeStore((s) => s.toggleDarkMode)
  
  const API_URL = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8000`

  // Build Antd theme config dynamically
  const agenticTheme = {
    token: {
      colorPrimary: '#06AC38',
      colorSuccess: '#52c41a',
      colorWarning: '#faad14',
      colorError: '#ff4d4f',
      colorInfo: '#1890ff',
      borderRadius: 6,
    },
    algorithm: darkMode ? theme.darkAlgorithm : theme.defaultAlgorithm,
  }

  // Sync body background for dark mode
  useEffect(() => {
    document.body.style.background = darkMode ? '#0a0a0a' : '#f5f7fa'
    document.body.style.colorScheme = darkMode ? 'dark' : 'light'
  }, [darkMode])

  // Fetch initial alert count
  useEffect(() => {
    const fetchAlerts = async () => {
      try {
        const response = await fetch(`${API_URL}/api/issues/dashboard`)
        const data = await response.json()
        const detected = data.stats?.by_status?.detected || 0
        setAlertCount(detected)
      } catch (error) {
        console.error('Failed to fetch alerts:', error)
      }
    }
    fetchAlerts()
    const interval = setInterval(fetchAlerts, 30000)
    return () => clearInterval(interval)
  }, [API_URL])

  const handleNewAlert = () => {
    setAlertCount(prev => prev + 1)
  }

  const menuItems = [
    { key: 'chat', icon: <RobotOutlined />, label: 'AI Assistant' },
    { key: 'scan', icon: <ScanOutlined />, label: 'Scan & Monitor' },
    { 
      key: 'observability', 
      icon: <AlertOutlined />, 
      label: (
        <Space>
          Observability
          {alertCount > 0 && <Badge count={alertCount} size="small" />}
        </Space>
      ),
    },
    { key: 'security', icon: <SafetyCertificateOutlined />, label: 'Security' },
  ]

  const renderContent = () => (
    <Suspense fallback={<PageLoading darkMode={darkMode} />}>
      {currentPage === 'chat' && <AgentChat apiUrl={API_URL} onNewAlert={handleNewAlert} />}
      {currentPage === 'scan' && <ScanConfig apiUrl={API_URL} />}
      {currentPage === 'observability' && <ObservabilityList apiUrl={API_URL} />}
      {currentPage === 'security' && <SecurityDashboard apiUrl={API_URL} />}
    </Suspense>
  )

  return (
    <ConfigProvider theme={agenticTheme}>
      <Layout style={{ minHeight: '100vh' }}>
        {/* Sidebar */}
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          theme={darkMode ? 'dark' : 'light'}
          style={{
            borderRight: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
            background: darkMode ? '#141414' : '#fff',
          }}
        >
          {/* Logo */}
          <div style={{ 
            height: 64, 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: collapsed ? 'center' : 'flex-start',
            padding: collapsed ? 0 : '0 16px',
            borderBottom: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
          }}>
            <RobotOutlined style={{ fontSize: 24, color: '#06AC38' }} />
            {!collapsed && (
              <span style={{ 
                marginLeft: 12, 
                fontWeight: 600, 
                fontSize: 16,
                color: darkMode ? '#e8e8e8' : undefined,
              }}>
                AgenticAIOps
              </span>
            )}
          </div>
          
          {/* Menu */}
          <Menu
            mode="inline"
            selectedKeys={[currentPage]}
            onClick={({ key }) => setCurrentPage(key)}
            items={menuItems}
            theme={darkMode ? 'dark' : 'light'}
            style={{ borderRight: 0, marginTop: 8 }}
          />
          
          {/* Bottom section: theme toggle + status */}
          <div style={{ 
            position: 'absolute', 
            bottom: 60, 
            left: 0, 
            right: 0, 
            padding: collapsed ? '8px' : '12px 16px',
            borderTop: darkMode ? '1px solid #303030' : '1px solid #e8e8e8',
          }}>
            {/* Dark mode toggle */}
            <div style={{ 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: collapsed ? 'center' : 'space-between',
              marginBottom: collapsed ? 0 : 12,
            }}>
              {collapsed ? (
                <Tooltip title={darkMode ? 'Light mode' : 'Dark mode'} placement="right">
                  <Button 
                    type="text" 
                    icon={darkMode ? <SunOutlined /> : <MoonOutlined />}
                    onClick={toggleDarkMode}
                    style={{ color: darkMode ? '#e8e8e8' : '#666' }}
                  />
                </Tooltip>
              ) : (
                <>
                  <Space size={8}>
                    {darkMode ? <MoonOutlined style={{ color: '#e8e8e8' }} /> : <SunOutlined style={{ color: '#faad14' }} />}
                    <span style={{ fontSize: 12, color: darkMode ? '#aaa' : '#666' }}>
                      {darkMode ? 'Dark' : 'Light'}
                    </span>
                  </Space>
                  <Switch
                    checked={darkMode}
                    onChange={toggleDarkMode}
                    size="small"
                    checkedChildren={<MoonOutlined />}
                    unCheckedChildren={<SunOutlined />}
                  />
                </>
              )}
            </div>
            
            {/* Status */}
            {!collapsed && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Badge status="success" />
                <span style={{ fontSize: 12, color: darkMode ? '#666' : '#666' }}>Agent Monitoring</span>
              </div>
            )}
          </div>
        </Sider>

        {/* Main Content */}
        <Layout style={{ background: darkMode ? '#0a0a0a' : '#f5f7fa' }}>
          <Content style={{ 
            background: darkMode ? '#0a0a0a' : '#f5f7fa',
            height: 'calc(100vh)',
            overflow: 'auto',
            padding: currentPage === 'chat' ? 16 : 0,
          }}>
            {renderContent()}
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  )
}

export default App
