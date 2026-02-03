import { useState, useEffect } from 'react'
import { Form, Input, Switch, Select, Button, message, Space, Tag, Table, Card, Typography, Divider } from 'antd'
import {
  SaveOutlined,
  ReloadOutlined,
  ClockCircleOutlined,
  CloudServerOutlined,
  ToolOutlined,
} from '@ant-design/icons'

const { Title, Text } = Typography

function Settings({ apiUrl }) {
  const [healthConfig, setHealthConfig] = useState({
    enabled: true,
    interval: 60,
  })
  const [runbooks, setRunbooks] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const [healthRes, runbooksRes] = await Promise.all([
          fetch(`${apiUrl}/api/health/status`).then(r => r.json()).catch(() => ({})),
          fetch(`${apiUrl}/api/runbooks`).then(r => r.json()).catch(() => ({ runbooks: [] })),
        ])
        
        if (healthRes.interval_seconds) {
          setHealthConfig({
            enabled: healthRes.enabled,
            interval: healthRes.interval_seconds,
          })
        }
        setRunbooks(runbooksRes.runbooks || [])
      } catch (err) {
        console.error('Failed to fetch settings:', err)
      }
    }

    fetchSettings()
  }, [apiUrl])

  const handleSaveHealth = () => {
    message.success('Health check configuration saved')
  }

  const runHealthCheck = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/health/check`)
      const data = await res.json()
      if (data.error) {
        message.error(data.error)
      } else {
        message.success(`Health check completed: ${data.status}`)
      }
    } catch (err) {
      message.error('Health check failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* Page Header */}
      <div style={{ marginBottom: 8 }}>
        <Title level={3} style={{ margin: 0 }}>Settings</Title>
        <Text type="secondary">Configure health checks and automation</Text>
      </div>

      {/* Health Check Settings */}
      <Card
        bordered={false}
        title={
          <Space>
            <ClockCircleOutlined />
            Health Check Configuration
          </Space>
        }
      >
        <Form layout="vertical">
          <Form.Item label="Enable Scheduled Checks">
            <Switch
              checked={healthConfig.enabled}
              onChange={(checked) => setHealthConfig({ ...healthConfig, enabled: checked })}
            />
          </Form.Item>
          <Form.Item label="Check Interval (seconds)">
            <Select
              value={healthConfig.interval}
              onChange={(value) => setHealthConfig({ ...healthConfig, interval: value })}
              style={{ width: 200 }}
              options={[
                { value: 30, label: '30 seconds' },
                { value: 60, label: '1 minute' },
                { value: 120, label: '2 minutes' },
                { value: 300, label: '5 minutes' },
              ]}
            />
          </Form.Item>
          <Form.Item label="Check Types">
            <Select
              mode="multiple"
              defaultValue={['pods', 'events']}
              style={{ width: '100%', maxWidth: 400 }}
              options={[
                { value: 'pods', label: 'Pod Status' },
                { value: 'nodes', label: 'Node Status' },
                { value: 'events', label: 'K8s Events' },
                { value: 'resources', label: 'Resource Usage' },
              ]}
            />
          </Form.Item>
          <Space>
            <Button 
              type="primary" 
              icon={<SaveOutlined />} 
              onClick={handleSaveHealth}
              style={{ background: '#06AC38', borderColor: '#06AC38' }}
            >
              Save Configuration
            </Button>
            <Button icon={<ReloadOutlined />} onClick={runHealthCheck} loading={loading}>
              Run Check Now
            </Button>
          </Space>
        </Form>
      </Card>

      {/* Runbooks */}
      <Card
        bordered={false}
        title={
          <Space>
            <ToolOutlined />
            Auto-Remediation Runbooks
          </Space>
        }
        extra={<Tag color="blue">{runbooks.length} available</Tag>}
      >
        <Table
          dataSource={runbooks}
          rowKey="id"
          pagination={false}
          columns={[
            {
              title: 'ID',
              dataIndex: 'id',
              width: 200,
              render: (id) => <code>{id}</code>,
            },
            {
              title: 'Name',
              dataIndex: 'name',
            },
            {
              title: 'Trigger Pattern',
              dataIndex: 'triggers',
              render: (triggers) => (
                <Space>
                  {triggers?.map((t, i) => (
                    <Tag key={i} color="blue">{t.pattern_id || JSON.stringify(t)}</Tag>
                  ))}
                </Space>
              ),
            },
            {
              title: 'Steps',
              dataIndex: 'step_count',
              width: 80,
              render: (count) => <Tag>{count || 0}</Tag>,
            },
            {
              title: 'Rollback',
              dataIndex: 'has_rollback',
              width: 100,
              render: (has) => (
                <Tag color={has ? 'green' : 'default'}>{has ? 'Supported' : 'None'}</Tag>
              ),
            },
          ]}
        />
      </Card>

      {/* Cluster Settings */}
      <Card
        bordered={false}
        title={
          <Space>
            <CloudServerOutlined />
            Cluster Configuration
          </Space>
        }
      >
        <Form layout="vertical">
          <Form.Item label="Current Cluster">
            <Input value="testing-cluster" disabled style={{ width: 300 }} />
          </Form.Item>
          <Form.Item label="Region">
            <Input value="ap-southeast-1" disabled style={{ width: 300 }} />
          </Form.Item>
          <Form.Item label="API Server">
            <Input value={apiUrl} disabled style={{ width: 400 }} />
          </Form.Item>
        </Form>
      </Card>
    </Space>
  )
}

export default Settings
