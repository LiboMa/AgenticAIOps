import { useState, useEffect, lazy, Suspense } from 'react'
import { ConfigProvider, Layout, Menu, Avatar, Dropdown, Badge, Button, Space, Spin, theme, Drawer } from 'antd'
import {
  DashboardOutlined,
  AlertOutlined,
  SearchOutlined,
  LineChartOutlined,
  SettingOutlined,
  BellOutlined,
  UserOutlined,
  RobotOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import ChatPanelPD from './components/ChatPanelPD'

// Lazy load pages - PagerDuty style
const Overview = lazy(() => import('./pages/OverviewPD'))
const IssueCenter = lazy(() => import('./pages/IssueCenterPD'))
const Diagnosis = lazy(() => import('./pages/Diagnosis'))
const Metrics = lazy(() => import('./pages/Metrics'))
const Settings = lazy(() => import('./pages/Settings'))

const { Header, Content, Footer } = Layout

// PagerDuty-inspired theme (light mode, green accent)
const pagerDutyTheme = {
  token: {
    colorPrimary: '#06AC38',        // PagerDuty green
    colorSuccess: '#06AC38',
    colorWarning: '#F2A900',
    colorError: '#CC2936',
    colorInfo: '#0066FF',
    borderRadius: 4,
    colorBgContainer: '#ffffff',
    colorBgLayout: '#f5f7fa',
  },
  algorithm: theme.defaultAlgorithm,  // Light mode
}

// Loading component
const PageLoading = () => (
  <div style={{ 
    display: 'flex', 
    justifyContent: 'center', 
    alignItems: 'center', 
    height: 400,
    background: '#fff',
  }}>
    <Spin size="large" />
  </div>
)

function App() {
  const [currentPage, setCurrentPage] = useState('overview')
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const [openIssues, setOpenIssues] = useState(0)
  const [chatVisible, setChatVisible] = useState(false)
  const [chatWidth, setChatWidth] = useState(420)

  useEffect(() => {
    // Fetch open issues count
    fetch(`${API_URL}/api/issues/dashboard`)
      .then(r => r.json())
      .then(data => {
        const stats = data.stats || {}
        setOpenIssues(stats.by_status?.detected || 0)
      })
      .catch(() => {})
  }, [])

  const menuItems = [
    { key: 'overview', icon: <DashboardOutlined />, label: 'Overview' },
    { 
      key: 'issues', 
      icon: <AlertOutlined />, 
      label: (
        <Space>
          Incidents
          {openIssues > 0 && <Badge count={openIssues} size="small" />}
        </Space>
      ),
    },
    { key: 'diagnosis', icon: <SearchOutlined />, label: 'Diagnostics' },
    { key: 'metrics', icon: <LineChartOutlined />, label: 'Analytics' },
    { key: 'settings', icon: <SettingOutlined />, label: 'Settings' },
  ]

  const userMenu = {
    items: [
      { key: 'profile', label: 'Profile' },
      { key: 'logout', label: 'Sign Out' },
    ],
  }

  const renderContent = () => {
    const props = { apiUrl: API_URL }
    return (
      <Suspense fallback={<PageLoading />}>
        {currentPage === 'overview' && <Overview {...props} />}
        {currentPage === 'issues' && <IssueCenter {...props} />}
        {currentPage === 'diagnosis' && <Diagnosis {...props} />}
        {currentPage === 'metrics' && <Metrics {...props} />}
        {currentPage === 'settings' && <Settings {...props} />}
      </Suspense>
    )
  }

  return (
    <ConfigProvider theme={pagerDutyTheme}>
      <Layout style={{ minHeight: '100vh' }}>
        {/* Top Navigation - PagerDuty style */}
        <Header style={{ 
          background: '#1F1F1F',  // Dark header
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'sticky',
          top: 0,
          zIndex: 100,
        }}>
          {/* Logo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
            <div style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: 8,
              color: '#fff',
            }}>
              <div style={{
                width: 32,
                height: 32,
                background: '#06AC38',
                borderRadius: 6,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 700,
                fontSize: 16,
              }}>
                A
              </div>
              <span style={{ 
                fontSize: 18, 
                fontWeight: 600,
                letterSpacing: '-0.5px',
              }}>
                AgenticAIOps
              </span>
            </div>

            {/* Main Navigation */}
            <Menu
              mode="horizontal"
              selectedKeys={[currentPage]}
              onClick={({ key }) => setCurrentPage(key)}
              items={menuItems}
              style={{ 
                background: 'transparent', 
                border: 'none',
                flex: 1,
              }}
              theme="dark"
            />
          </div>

          {/* Right Actions */}
          <Space size="middle">
            {/* AI Assistant Button */}
            <Button 
              type="text" 
              icon={<RobotOutlined style={{ fontSize: 18, color: chatVisible ? '#06AC38' : '#fff' }} />}
              onClick={() => setChatVisible(!chatVisible)}
              style={{ 
                background: chatVisible ? 'rgba(6, 172, 56, 0.2)' : 'transparent',
                borderRadius: 4,
              }}
            />
            <Badge count={openIssues} size="small">
              <Button 
                type="text" 
                icon={<BellOutlined style={{ fontSize: 18, color: '#fff' }} />}
              />
            </Badge>
            <Dropdown menu={userMenu} placement="bottomRight">
              <Avatar 
                size="small" 
                style={{ background: '#06AC38', cursor: 'pointer' }}
                icon={<UserOutlined />}
              />
            </Dropdown>
          </Space>
        </Header>

        {/* Main Content */}
        <Content style={{ 
          padding: '24px',
          paddingLeft: 'max(24px, 3vw)',
          paddingRight: 'max(24px, 3vw)',
          background: '#f5f7fa',
          minHeight: 'calc(100vh - 64px - 48px)',
        }}>
          {renderContent()}
        </Content>

        {/* Footer */}
        <Footer style={{ 
          textAlign: 'center', 
          background: '#fff',
          borderTop: '1px solid #e8e8e8',
          padding: '12px 24px',
          color: '#666',
          fontSize: 13,
        }}>
          AgenticAIOps Platform © 2026 | Powered by AI-driven Operations
        </Footer>

        {/* Resizable Chat Drawer */}
        <Drawer
          title={
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
              <Space>
                <RobotOutlined style={{ color: '#06AC38' }} />
                <span>AI Assistant</span>
              </Space>
              <Space size="small">
                <Button 
                  size="small" 
                  type="text"
                  onClick={() => setChatWidth(chatWidth === 420 ? 600 : 420)}
                  style={{ fontSize: 12, color: '#666' }}
                >
                  {chatWidth === 420 ? '↔️ Expand' : '↔️ Collapse'}
                </Button>
              </Space>
            </div>
          }
          placement="right"
          width={chatWidth}
          onClose={() => setChatVisible(false)}
          open={chatVisible}
          closeIcon={<CloseOutlined />}
          bodyStyle={{ padding: 0, height: 'calc(100vh - 55px)' }}
          style={{ transition: 'width 0.2s' }}
        >
          {/* Resize handle */}
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: 6,
              cursor: 'ew-resize',
              background: 'transparent',
              zIndex: 10,
            }}
            onMouseDown={(e) => {
              e.preventDefault()
              const startX = e.clientX
              const startWidth = chatWidth
              
              const onMouseMove = (moveEvent) => {
                const diff = startX - moveEvent.clientX
                const newWidth = Math.min(800, Math.max(320, startWidth + diff))
                setChatWidth(newWidth)
              }
              
              const onMouseUp = () => {
                document.removeEventListener('mousemove', onMouseMove)
                document.removeEventListener('mouseup', onMouseUp)
              }
              
              document.addEventListener('mousemove', onMouseMove)
              document.addEventListener('mouseup', onMouseUp)
            }}
          />
          <div style={{ height: '100%', padding: 12 }}>
            <ChatPanelPD apiUrl={API_URL} />
          </div>
        </Drawer>
      </Layout>
    </ConfigProvider>
  )
}

export default App
