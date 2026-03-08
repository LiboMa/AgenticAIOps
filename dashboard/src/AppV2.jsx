/**
 * AgenticAIOps v2 - Agent-First Architecture
 * 
 * 3 Core Views: Ops Hub | Diagnose | Agent Console
 * + Config (merged settings)
 * Design: 简約·克制·Solid
 */

import { useState, useEffect, lazy, Suspense } from 'react'
import { ConfigProvider, Layout, Menu, Badge, Button, Space, Spin, theme, Tooltip, Switch } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RobotOutlined,
  DashboardOutlined,
  SearchOutlined,
  SettingOutlined,
  MoonOutlined,
  SunOutlined,
} from '@ant-design/icons'
import useThemeStore from './stores/themeStore'

// Lazy load pages
const OpsHub = lazy(() => import('./pages/OpsHub'))
const Diagnose = lazy(() => import('./pages/Diagnose'))
const AgentChat = lazy(() => import('./pages/AgentChat'))
const Config = lazy(() => import('./pages/Config'))

const { Content, Sider } = Layout

// React Query client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 10_000,
    },
  },
})

// Loading component
const PageLoading = ({ darkMode }) => (
  <div style={{ 
    display: 'flex', 
    justifyContent: 'center', 
    alignItems: 'center', 
    height: '100%',
    background: darkMode ? '#0a0a0a' : '#f5f7fa',
  }}>
    <Spin size="large" />
  </div>
)

function App() {
  const [currentPage, setCurrentPage] = useState('ops')
  const [collapsed, setCollapsed] = useState(false)
  
  const darkMode = useThemeStore((s) => s.darkMode)
  const toggleDarkMode = useThemeStore((s) => s.toggleDarkMode)
  
  const API_URL = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8000`

  // Antd theme
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

  // Sync body background
  useEffect(() => {
    document.body.style.background = darkMode ? '#0a0a0a' : '#f5f7fa'
    document.body.style.colorScheme = darkMode ? 'dark' : 'light'
  }, [darkMode])

  const menuItems = [
    { key: 'ops', icon: <DashboardOutlined />, label: 'Ops Hub' },
    { key: 'diagnose', icon: <SearchOutlined />, label: 'Diagnose' },
    { key: 'chat', icon: <RobotOutlined />, label: 'Agent Console' },
    { key: 'config', icon: <SettingOutlined />, label: 'Config' },
  ]

  const renderContent = () => (
    <Suspense fallback={<PageLoading darkMode={darkMode} />}>
      {currentPage === 'ops' && <OpsHub />}
      {currentPage === 'diagnose' && <Diagnose />}
      {currentPage === 'chat' && <AgentChat apiUrl={API_URL} />}
      {currentPage === 'config' && <Config apiUrl={API_URL} />}
    </Suspense>
  )

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider theme={agenticTheme}>
        <Layout style={{ minHeight: '100vh' }}>
          {/* Sidebar */}
          <Sider
            collapsible
            collapsed={collapsed}
            onCollapse={setCollapsed}
            theme="dark"
            style={{
              borderRight: '1px solid #303030',
              background: '#141414',
            }}
          >
            {/* Logo */}
            <div style={{ 
              height: 64, 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: collapsed ? 'center' : 'flex-start',
              padding: collapsed ? 0 : '0 16px',
              borderBottom: '1px solid #303030',
            }}>
              <RobotOutlined style={{ fontSize: 24, color: '#06AC38' }} />
              {!collapsed && (
                <span style={{ 
                  marginLeft: 12, 
                  fontWeight: 600, 
                  fontSize: 16,
                  color: '#e8e8e8',
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
              theme="dark"
              style={{ borderRight: 0, marginTop: 8 }}
            />
            
            {/* Bottom: theme toggle */}
            <div style={{ 
              position: 'absolute', 
              bottom: 60, 
              left: 0, 
              right: 0, 
              padding: collapsed ? '8px' : '12px 16px',
              borderTop: '1px solid #303030',
            }}>
              <div style={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: collapsed ? 'center' : 'space-between',
              }}>
                {collapsed ? (
                  <Tooltip title={darkMode ? 'Light mode' : 'Dark mode'} placement="right">
                    <Button 
                      type="text" 
                      icon={darkMode ? <SunOutlined /> : <MoonOutlined />}
                      onClick={toggleDarkMode}
                      style={{ color: '#e8e8e8' }}
                    />
                  </Tooltip>
                ) : (
                  <>
                    <Space size={8}>
                      <MoonOutlined style={{ color: '#e8e8e8' }} />
                      <span style={{ fontSize: 12, color: '#aaa' }}>
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
              {!collapsed && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
                  <Badge status="success" />
                  <span style={{ fontSize: 12, color: '#666' }}>Agent Online</span>
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
            }}>
              {renderContent()}
            </Content>
          </Layout>
        </Layout>
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default App
