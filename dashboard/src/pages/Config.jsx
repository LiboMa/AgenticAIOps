/**
 * Config — Unified configuration (ScanConfig + Security + Skills)
 * Merges 3 existing pages into Tabs
 */

import { lazy, Suspense } from 'react'
import { Tabs, Typography, Spin } from 'antd'
import {
  ScanOutlined, SafetyCertificateOutlined, ToolOutlined, SettingOutlined,
} from '@ant-design/icons'

const { Title } = Typography

const ScanConfig = lazy(() => import('./ScanConfig'))
const SecurityDashboard = lazy(() => import('./SecurityDashboard'))
const Settings = lazy(() => import('./Settings'))

const Loading = () => (
  <div style={{ textAlign: 'center', padding: 48 }}>
    <Spin size="large" />
  </div>
)

export default function Config({ apiUrl }) {
  const items = [
    {
      key: 'scan',
      label: <><ScanOutlined /> Scan Config</>,
      children: (
        <Suspense fallback={<Loading />}>
          <ScanConfig apiUrl={apiUrl} />
        </Suspense>
      ),
    },
    {
      key: 'security',
      label: <><SafetyCertificateOutlined /> Security</>,
      children: (
        <Suspense fallback={<Loading />}>
          <SecurityDashboard apiUrl={apiUrl} />
        </Suspense>
      ),
    },
    {
      key: 'settings',
      label: <><SettingOutlined /> Settings</>,
      children: (
        <Suspense fallback={<Loading />}>
          <Settings apiUrl={apiUrl} />
        </Suspense>
      ),
    },
  ]

  return (
    <div style={{ padding: '16px 24px' }}>
      <Title level={4} style={{ margin: '0 0 16px', color: '#eee' }}>
        ⚙️ Configuration
      </Title>
      <Tabs items={items} defaultActiveKey="scan" />
    </div>
  )
}
