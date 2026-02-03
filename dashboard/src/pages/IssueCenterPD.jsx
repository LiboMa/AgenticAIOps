import { useState, useEffect, useCallback } from 'react'
import { 
  Table, Tag, Button, Space, Modal, Descriptions, Card, Typography, Input, Select,
  message, Badge, Tabs, Timeline, Avatar, Row, Col, Statistic, Divider
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  SearchOutlined,
  ReloadOutlined,
  EyeOutlined,
  UserOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'

const { Title, Text } = Typography
const { TabPane } = Tabs

const severityConfig = {
  low: { color: 'blue', label: 'Low', priority: 'P4' },
  medium: { color: 'orange', label: 'Medium', priority: 'P3' },
  high: { color: 'red', label: 'High', priority: 'P2' },
  critical: { color: 'magenta', label: 'Critical', priority: 'P1' },
}

const statusConfig = {
  open: { color: '#CC2936', bg: '#fff2f0', label: 'Triggered' },
  in_progress: { color: '#F2A900', bg: '#fffbe6', label: 'Acknowledged' },
  resolved: { color: '#06AC38', bg: '#f6ffed', label: 'Resolved' },
  closed: { color: '#666', bg: '#fafafa', label: 'Closed' },
}

function IssueCenter({ apiUrl }) {
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(false)
  const [dashboardData, setDashboardData] = useState({})
  const [selectedIssue, setSelectedIssue] = useState(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [fixLoading, setFixLoading] = useState({})
  const [activeTab, setActiveTab] = useState('triggered')

  const fetchIssues = useCallback(async () => {
    setLoading(true)
    try {
      const [issuesRes, dashboardRes] = await Promise.all([
        fetch(`${apiUrl}/api/issues?limit=100`).then(r => r.json()),
        fetch(`${apiUrl}/api/issues/dashboard`).then(r => r.json()),
      ])
      setIssues(issuesRes.issues || [])
      setDashboardData(dashboardRes)
    } catch (err) {
      message.error('Failed to fetch incidents')
    } finally {
      setLoading(false)
    }
  }, [apiUrl])

  useEffect(() => {
    fetchIssues()
    const interval = setInterval(fetchIssues, 30000)
    return () => clearInterval(interval)
  }, [fetchIssues])

  const handleAutoFix = async (issue) => {
    setFixLoading(prev => ({ ...prev, [issue.id]: true }))
    try {
      const res = await fetch(`${apiUrl}/api/issues/${issue.id}/fix`, { method: 'POST' })
      const result = await res.json()
      if (result.status === 'initiated') {
        message.success(`Auto-remediation started: ${result.runbook_id}`)
      } else {
        message.warning(result.message || 'No runbook available')
      }
      setTimeout(fetchIssues, 2000)
    } catch (err) {
      message.error('Remediation request failed')
    } finally {
      setFixLoading(prev => ({ ...prev, [issue.id]: false }))
    }
  }

  const handleAcknowledge = async (issueId) => {
    try {
      await fetch(`${apiUrl}/api/issues/${issueId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'in_progress' }),
      })
      message.success('Incident acknowledged')
      fetchIssues()
    } catch (err) {
      message.error('Update failed')
    }
  }

  const handleResolve = async (issueId) => {
    try {
      await fetch(`${apiUrl}/api/issues/${issueId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'resolved' }),
      })
      message.success('Incident resolved')
      fetchIssues()
      setDetailVisible(false)
    } catch (err) {
      message.error('Update failed')
    }
  }

  const columns = [
    {
      title: 'Status',
      dataIndex: 'status',
      width: 130,
      render: (status) => {
        const config = statusConfig[status] || statusConfig.open
        return (
          <Tag 
            style={{ 
              background: config.bg, 
              color: config.color, 
              border: `1px solid ${config.color}`,
              borderRadius: 12,
              padding: '2px 12px',
            }}
          >
            {config.label}
          </Tag>
        )
      },
    },
    {
      title: 'Priority',
      dataIndex: 'severity',
      width: 80,
      render: (severity) => {
        const config = severityConfig[severity] || severityConfig.low
        return (
          <Tag color={config.color} style={{ fontWeight: 600 }}>
            {config.priority}
          </Tag>
        )
      },
    },
    {
      title: 'Incident',
      dataIndex: 'title',
      render: (title, record) => (
        <div>
          <a 
            onClick={() => { setSelectedIssue(record); setDetailVisible(true); }}
            style={{ fontWeight: 500 }}
          >
            {title}
          </a>
          <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
            {record.resource_type}/{record.resource_name} • {record.namespace}
          </div>
        </div>
      ),
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      width: 140,
      render: (time) => (
        <Space>
          <ClockCircleOutlined style={{ color: '#999' }} />
          <Text type="secondary" style={{ fontSize: 13 }}>
            {time ? new Date(time).toLocaleString() : '-'}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Actions',
      width: 200,
      render: (_, record) => (
        <Space>
          {record.status === 'open' && (
            <Button size="small" onClick={() => handleAcknowledge(record.id)}>
              Acknowledge
            </Button>
          )}
          {record.status === 'open' && record.auto_fixable && (
            <Button 
              size="small" 
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={fixLoading[record.id]}
              onClick={() => handleAutoFix(record)}
              style={{ background: '#06AC38', borderColor: '#06AC38' }}
            >
              Auto Fix
            </Button>
          )}
          {record.status === 'in_progress' && (
            <Button 
              size="small" 
              type="primary"
              onClick={() => handleResolve(record.id)}
              style={{ background: '#06AC38', borderColor: '#06AC38' }}
            >
              Resolve
            </Button>
          )}
        </Space>
      ),
    },
  ]

  const statusCounts = dashboardData.status_counts || {}

  // Filter issues by tab
  const filteredIssues = issues.filter(i => {
    if (activeTab === 'triggered') return i.status === 'open'
    if (activeTab === 'acknowledged') return i.status === 'in_progress'
    if (activeTab === 'resolved') return i.status === 'resolved' || i.status === 'closed'
    return true
  })

  return (
    <div>
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>Incidents</Title>
        <Text type="secondary">Manage and respond to operational incidents</Text>
      </div>

      {/* Stats Bar */}
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Row gutter={32}>
          <Col>
            <Statistic 
              title="Triggered" 
              value={statusCounts.open || 0}
              valueStyle={{ color: '#CC2936' }}
            />
          </Col>
          <Col><Divider type="vertical" style={{ height: 50 }} /></Col>
          <Col>
            <Statistic 
              title="Acknowledged" 
              value={statusCounts.in_progress || 0}
              valueStyle={{ color: '#F2A900' }}
            />
          </Col>
          <Col><Divider type="vertical" style={{ height: 50 }} /></Col>
          <Col>
            <Statistic 
              title="Resolved Today" 
              value={statusCounts.resolved || 0}
              valueStyle={{ color: '#06AC38' }}
            />
          </Col>
          <Col><Divider type="vertical" style={{ height: 50 }} /></Col>
          <Col>
            <Statistic 
              title="Total" 
              value={issues.length}
              valueStyle={{ color: '#666' }}
            />
          </Col>
        </Row>
      </Card>

      {/* Incidents Table with Tabs */}
      <Card 
        bordered={false}
        bodyStyle={{ padding: 0 }}
        extra={
          <Button 
            icon={<ReloadOutlined />} 
            onClick={fetchIssues}
            loading={loading}
          >
            Refresh
          </Button>
        }
      >
        <Tabs 
          activeKey={activeTab} 
          onChange={setActiveTab}
          style={{ marginBottom: 0 }}
          tabBarStyle={{ padding: '0 16px', marginBottom: 0 }}
        >
          <TabPane 
            tab={<Badge count={statusCounts.open || 0} offset={[10, 0]}>Triggered</Badge>} 
            key="triggered" 
          />
          <TabPane 
            tab={<Badge count={statusCounts.in_progress || 0} offset={[10, 0]}>Acknowledged</Badge>} 
            key="acknowledged" 
          />
          <TabPane tab="Resolved" key="resolved" />
          <TabPane tab="All" key="all" />
        </Tabs>
        
        <Table
          columns={columns}
          dataSource={filteredIssues}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          style={{ borderTop: '1px solid #f0f0f0' }}
        />
      </Card>

      {/* Detail Modal */}
      <Modal
        title={
          <Space>
            <Tag color={statusConfig[selectedIssue?.status]?.color}>
              {statusConfig[selectedIssue?.status]?.label}
            </Tag>
            <span>{selectedIssue?.title}</span>
          </Space>
        }
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        width={700}
        footer={[
          selectedIssue?.status === 'open' && (
            <Button key="ack" onClick={() => handleAcknowledge(selectedIssue?.id)}>
              Acknowledge
            </Button>
          ),
          selectedIssue?.status === 'open' && selectedIssue?.auto_fixable && (
            <Button 
              key="fix" 
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={() => handleAutoFix(selectedIssue)}
              loading={fixLoading[selectedIssue?.id]}
              style={{ background: '#06AC38', borderColor: '#06AC38' }}
            >
              Auto Fix
            </Button>
          ),
          selectedIssue?.status !== 'resolved' && (
            <Button 
              key="resolve" 
              type="primary"
              onClick={() => handleResolve(selectedIssue?.id)}
            >
              Resolve
            </Button>
          ),
          <Button key="close" onClick={() => setDetailVisible(false)}>Close</Button>,
        ]}
      >
        {selectedIssue && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="ID">{selectedIssue.id}</Descriptions.Item>
            <Descriptions.Item label="Priority">
              <Tag color={severityConfig[selectedIssue.severity]?.color}>
                {severityConfig[selectedIssue.severity]?.priority}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Namespace">{selectedIssue.namespace}</Descriptions.Item>
            <Descriptions.Item label="Resource">
              {selectedIssue.resource_type}/{selectedIssue.resource_name}
            </Descriptions.Item>
            <Descriptions.Item label="Description" span={2}>
              {selectedIssue.description || 'No description'}
            </Descriptions.Item>
            {selectedIssue.root_cause && (
              <Descriptions.Item label="Root Cause" span={2}>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                  {selectedIssue.root_cause}
                </pre>
              </Descriptions.Item>
            )}
            {selectedIssue.remediation && (
              <Descriptions.Item label="Remediation" span={2}>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                  {selectedIssue.remediation}
                </pre>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="Created">
              {selectedIssue.created_at ? new Date(selectedIssue.created_at).toLocaleString() : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="Updated">
              {selectedIssue.updated_at ? new Date(selectedIssue.updated_at).toLocaleString() : '-'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}

export default IssueCenter
