import { useState, lazy, Suspense } from 'react'
import { ConfigProvider, theme, App as AntApp, Spin } from 'antd'
import { ProLayout } from '@ant-design/pro-components'
import {
  DashboardOutlined,
  AlertOutlined,
  SearchOutlined,
  LineChartOutlined,
  SettingOutlined,
  RobotOutlined,
  CloudServerOutlined,
  ToolOutlined,
} from '@ant-design/icons'

// Lazy load pages for code splitting
const Overview = lazy(() => import('./pages/Overview'))
const IssueCenter = lazy(() => import('./pages/IssueCenter'))
const Diagnosis = lazy(() => import('./pages/Diagnosis'))
const Metrics = lazy(() => import('./pages/Metrics'))
const Settings = lazy(() => import('./pages/Settings'))

const { darkAlgorithm } = theme

// Enterprise color tokens
const enterpriseTheme = {
  token: {
    colorPrimary: '#1677ff',
    colorSuccess: '#52c41a',
    colorWarning: '#faad14',
    colorError: '#ff4d4f',
    colorInfo: '#1677ff',
    borderRadius: 6,
    wireframe: false,
  },
  algorithm: [darkAlgorithm],
}

// Navigation menu configuration
const menuConfig = {
  route: {
    path: '/',
    routes: [
      { path: '/overview', name: '概览', icon: <DashboardOutlined /> },
      { path: '/issues', name: '问题中心', icon: <AlertOutlined /> },
      { path: '/diagnosis', name: '智能诊断', icon: <SearchOutlined /> },
      { path: '/metrics', name: '监控指标', icon: <LineChartOutlined /> },
      { path: '/settings', name: '系统设置', icon: <SettingOutlined /> },
    ],
  },
}

// Loading fallback
const PageLoading = () => (
  <div style={{ 
    display: 'flex', 
    justifyContent: 'center', 
    alignItems: 'center', 
    height: '100%', 
    minHeight: 400 
  }}>
    <Spin size="large" tip="加载中..." />
  </div>
)

function App() {
  const [pathname, setPathname] = useState('/overview')
  const [collapsed, setCollapsed] = useState(false)
  
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

  // Render content based on pathname
  const renderContent = () => {
    const props = { apiUrl: API_URL }
    
    return (
      <Suspense fallback={<PageLoading />}>
        {pathname === '/overview' && <Overview {...props} />}
        {pathname === '/issues' && <IssueCenter {...props} />}
        {pathname === '/diagnosis' && <Diagnosis {...props} />}
        {pathname === '/metrics' && <Metrics {...props} />}
        {pathname === '/settings' && <Settings {...props} />}
      </Suspense>
    )
  }

  return (
    <ConfigProvider theme={enterpriseTheme}>
      <AntApp>
        <ProLayout
          title="AgenticAIOps"
          logo={<RobotOutlined style={{ fontSize: 28, color: '#1677ff' }} />}
          {...menuConfig}
          location={{ pathname }}
          collapsed={collapsed}
          onCollapse={setCollapsed}
          menuItemRender={(item, dom) => (
            <a onClick={() => setPathname(item.path || '/overview')}>
              {dom}
            </a>
          )}
          headerTitleRender={(logo, title) => (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {logo}
              <span style={{ 
                fontSize: 18, 
                fontWeight: 600,
                background: 'linear-gradient(90deg, #1677ff, #69b1ff)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
              }}>
                AgenticAIOps
              </span>
            </div>
          )}
          avatarProps={{
            src: 'https://gw.alipayobjects.com/zos/antfincdn/efFD%24IOql2/weixintupian_20170331104822.jpg',
            title: 'Admin',
            size: 'small',
          }}
          actionsRender={() => [
            <CloudServerOutlined key="cluster" style={{ fontSize: 18 }} />,
            <ToolOutlined key="tools" style={{ fontSize: 18 }} />,
          ]}
          menuFooterRender={(props) => {
            if (props?.collapsed) return undefined
            return (
              <div style={{ 
                textAlign: 'center', 
                padding: '12px 0',
                color: 'rgba(255,255,255,0.45)',
                fontSize: 12,
              }}>
                Enterprise Edition v2.0
              </div>
            )
          }}
          layout="side"
          fixSiderbar
          contentStyle={{
            padding: 24,
            minHeight: 'calc(100vh - 56px)',
          }}
        >
          {renderContent()}
        </ProLayout>
      </AntApp>
    </ConfigProvider>
  )
}

export default App
