import { useState, useEffect } from 'react'
import { Form, Input, Switch, Select, Button, message, Divider, Space, Tag, Table } from 'antd'
import { ProCard, ProList } from '@ant-design/pro-components'
import {
  SaveOutlined,
  ReloadOutlined,
  ClockCircleOutlined,
  CloudServerOutlined,
  ToolOutlined,
} from '@ant-design/icons'

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
    message.success('健康检查配置已保存')
  }

  const runHealthCheck = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/health/check`)
      const data = await res.json()
      if (data.error) {
        message.error(data.error)
      } else {
        message.success(`健康检查完成: ${data.status}`)
      }
    } catch (err) {
      message.error('健康检查失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* Health Check Settings */}
      <ProCard
        title={
          <Space>
            <ClockCircleOutlined />
            健康检查配置
          </Space>
        }
        style={{ background: '#141414' }}
        headStyle={{ borderBottom: '1px solid #303030' }}
      >
        <Form layout="vertical">
          <Form.Item label="启用定时检查">
            <Switch
              checked={healthConfig.enabled}
              onChange={(checked) => setHealthConfig({ ...healthConfig, enabled: checked })}
            />
          </Form.Item>
          <Form.Item label="检查间隔 (秒)">
            <Select
              value={healthConfig.interval}
              onChange={(value) => setHealthConfig({ ...healthConfig, interval: value })}
              style={{ width: 200 }}
              options={[
                { value: 30, label: '30 秒' },
                { value: 60, label: '1 分钟' },
                { value: 120, label: '2 分钟' },
                { value: 300, label: '5 分钟' },
              ]}
            />
          </Form.Item>
          <Form.Item label="检查类型">
            <Select
              mode="multiple"
              defaultValue={['pods', 'events']}
              style={{ width: '100%', maxWidth: 400 }}
              options={[
                { value: 'pods', label: 'Pods 状态' },
                { value: 'nodes', label: 'Nodes 状态' },
                { value: 'events', label: 'K8s 事件' },
                { value: 'resources', label: '资源使用' },
              ]}
            />
          </Form.Item>
          <Space>
            <Button type="primary" icon={<SaveOutlined />} onClick={handleSaveHealth}>
              保存配置
            </Button>
            <Button icon={<ReloadOutlined />} onClick={runHealthCheck} loading={loading}>
              立即检查
            </Button>
          </Space>
        </Form>
      </ProCard>

      {/* Runbooks */}
      <ProCard
        title={
          <Space>
            <ToolOutlined />
            自动修复 Runbook
          </Space>
        }
        extra={<Tag color="blue">{runbooks.length} 个可用</Tag>}
        style={{ background: '#141414' }}
        headStyle={{ borderBottom: '1px solid #303030' }}
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
              title: '名称',
              dataIndex: 'name',
            },
            {
              title: '触发规则',
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
              title: '步骤数',
              dataIndex: 'step_count',
              width: 80,
              render: (count) => <Tag>{count || 0}</Tag>,
            },
            {
              title: '回滚',
              dataIndex: 'has_rollback',
              width: 80,
              render: (has) => (
                <Tag color={has ? 'green' : 'default'}>{has ? '支持' : '无'}</Tag>
              ),
            },
          ]}
        />
      </ProCard>

      {/* Cluster Settings */}
      <ProCard
        title={
          <Space>
            <CloudServerOutlined />
            集群配置
          </Space>
        }
        style={{ background: '#141414' }}
        headStyle={{ borderBottom: '1px solid #303030' }}
      >
        <Form layout="vertical">
          <Form.Item label="当前集群">
            <Input value="testing-cluster" disabled style={{ width: 300 }} />
          </Form.Item>
          <Form.Item label="区域">
            <Input value="ap-southeast-1" disabled style={{ width: 300 }} />
          </Form.Item>
          <Form.Item label="API Server">
            <Input value={apiUrl} disabled style={{ width: 400 }} />
          </Form.Item>
        </Form>
      </ProCard>
    </Space>
  )
}

export default Settings
