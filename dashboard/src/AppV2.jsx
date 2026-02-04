/**
 * AgenticAIOps v2 - Agent-First Architecture
 * 
 * Simplified frontend with 3 core pages:
 * 1. Agent Chat (main) - Proactive AI assistant
 * 2. Observability List - Anomaly Detection + RCA
 * 3. Security Dashboard - AWS security by service
 */

import { useState, useEffect, lazy, Suspense } from 'react'
import { ConfigProvider, Layout, Menu, Badge, Button, Space, Spin, theme } from 'antd'
import {
  RobotOutlined,
  AlertOutlined,
  SafetyCertificateOutlined,
  BellOutlined,
} from '@ant-design/icons'

// Lazy load pages
const AgentChat = lazy(() => import('./pages/AgentChat'))
const ObservabilityList = lazy(() => import('./pages/ObservabilityList'))
const SecurityDashboard = lazy(() => import('./pages/SecurityDashboard'))

const { Header, Content, Sider } = Layout

// Theme configuration
const agenticTheme = {
  token: {
    colorPrimary: '#06AC38',
    colorSuccess: '#52c41a',
    colorWarning: '#faad14',
    colorError: '#ff4d4f',
    colorInfo: '#1890ff',
    borderRadius: 6,
    colorBgContainer: '#ffffff',
    colorBgLayout: '#f5f7fa',
  },
  algorithm: theme.defaultAlgorithm,
}

// Loading component
const PageLoading = () => (
  <div style={{ 
    display: 'flex', 
    justifyContent: 'center', 
    alignItems: 'center', 
    height: '100%',
    background: '#f5f7fa',
  }}>
    <Spin size="large" tip="Loading..." />
  </div>
)

function App() {
  const [currentPage, setCurrentPage] = useState('chat')
  const [alertCount, setAlertCount] = useState(0)
  const [collapsed, setCollapsed] = useState(false)
  
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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
    { 
      key: 'chat', 
      icon: <RobotOutlined />, 
      label: 'AI Assistant',
    },
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
    { 
      key: 'security', 
      icon: <SafetyCertificateOutlined />, 
      label: 'Security',
    },
  ]

  const renderContent = () => {
    return (
      <Suspense fallback={<PageLoading />}>
        {currentPage === 'chat' && <AgentChat apiUrl={API_URL} onNewAlert={handleNewAlert} />}
        {currentPage === 'observability' && <ObservabilityList apiUrl={API_URL} />}
        {currentPage === 'security' && <SecurityDashboard apiUrl={API_URL} />}
      </Suspense>
    )
  }

  return (
    <ConfigProvider theme={agenticTheme}>
      <Layout style={{ minHeight: '100vh' }}>
        {/* Sidebar Navigation */}
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          theme="light"
          style={{
            borderRight: '1px solid #e8e8e8',
          }}
        >
          {/* Logo */}
          <div style={{ 
            height: 64, 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: collapsed ? 'center' : 'flex-start',
            padding: collapsed ? 0 : '0 16px',
            borderBottom: '1px solid #e8e8e8',
          }}>
            <RobotOutlined style={{ fontSize: 24, color: '#06AC38' }} />
            {!collapsed && (
              <span style={{ marginLeft: 12, fontWeight: 600, fontSize: 16 }}>
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
            style={{ borderRight: 0, marginTop: 8 }}
          />
          
          {/* Proactive Status */}
          {!collapsed && (
            <div style={{ 
              position: 'absolute', 
              bottom: 60, 
              left: 0, 
              right: 0, 
              padding: 16,
              borderTop: '1px solid #e8e8e8',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Badge status="success" />
                <span style={{ fontSize: 12, color: '#666' }}>Agent Monitoring</span>
              </div>
            </div>
          )}
        </Sider>

        {/* Main Content */}
        <Layout>
          <Content style={{ 
            background: '#f5f7fa',
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
