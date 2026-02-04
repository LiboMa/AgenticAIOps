import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, Space, Tabs, Statistic, Row, Col, Badge, Empty, Spin, Typography, Tooltip, Modal } from 'antd'
import { 
  AlertOutlined, 
  SearchOutlined, 
  CheckCircleOutlined, 
  ExclamationCircleOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  EyeOutlined,
  BugOutlined,
} from '@ant-design/icons'

const { Title, Text, Paragraph } = Typography
const { TabPane } = Tabs

// Severity colors
const SEVERITY_CONFIG = {
  high: { color: '#ff4d4f', tag: 'red', icon: <ExclamationCircleOutlined /> },
  medium: { color: '#faad14', tag: 'orange', icon: <ClockCircleOutlined /> },
  low: { color: '#52c41a', tag: 'green', icon: <CheckCircleOutlined /> },
}

// RCA Detail Modal
const RCAModal = ({ visible, issue, onClose }) => {
  if (!issue) return null
  
  return (
    <Modal
      title={
        <Space>
          <BugOutlined style={{ color: '#06AC38' }} />
          Root Cause Analysis
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={[
        <Button key="close" onClick={onClose}>Close</Button>
      ]}
      width={700}
    >
      <div style={{ padding: '16px 0' }}>
        <Title level={5}>{issue.title}</Title>
        
        <Card size="small" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col span={8}>
              <Statistic title="Severity" value={issue.severity?.toUpperCase()} valueStyle={{ color: SEVERITY_CONFIG[issue.severity]?.color }} />
            </Col>
            <Col span={8}>
              <Statistic title="Resource" value={issue.resource_name || 'N/A'} />
            </Col>
            <Col span={8}>
              <Statistic title="Namespace" value={issue.namespace || 'N/A'} />
            </Col>
          </Row>
        </Card>
        
        <Title level={5}>🔍 Analysis</Title>
        <Paragraph>{issue.description || 'No detailed description available.'}</Paragraph>
        
        <Title level={5}>🎯 Root Cause</Title>
        <Card size="small" style={{ background: '#f6ffed', marginBottom: 16 }}>
          <Text>{issue.root_cause || 'Pattern matching in progress...'}</Text>
        </Card>
        
        <Title level={5}>💡 Recommendation</Title>
        <Paragraph>{issue.remediation || 'Review the affected resource and take appropriate action.'}</Paragraph>
        
        {issue.pattern_id && (
          <>
            <Title level={5}>📋 Pattern ID</Title>
            <Tag color="blue">{issue.pattern_id}</Tag>
          </>
        )}
      </div>
    </Modal>
  )
}

function ObservabilityList({ apiUrl }) {
  const [issues, setIssues] = useState([])
  const [stats, setStats] = useState({ total: 0, by_severity: {}, by_status: {} })
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('anomalies')
  const [selectedIssue, setSelectedIssue] = useState(null)
  const [rcaModalVisible, setRcaModalVisible] = useState(false)

  const fetchIssues = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${apiUrl}/api/issues/dashboard`)
      const data = await response.json()
      setIssues(data.issues || [])
      setStats(data.stats || { total: 0, by_severity: {}, by_status: {} })
    } catch (error) {
      console.error('Failed to fetch issues:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchIssues()
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchIssues, 30000)
    return () => clearInterval(interval)
  }, [apiUrl])

  const showRCA = (issue) => {
    setSelectedIssue(issue)
    setRcaModalVisible(true)
  }

  const anomalyColumns = [
    {
      title: 'Severity',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (severity) => (
        <Tag color={SEVERITY_CONFIG[severity]?.tag || 'default'} icon={SEVERITY_CONFIG[severity]?.icon}>
          {severity?.toUpperCase()}
        </Tag>
      ),
      filters: [
        { text: 'High', value: 'high' },
        { text: 'Medium', value: 'medium' },
        { text: 'Low', value: 'low' },
      ],
      onFilter: (value, record) => record.severity === value,
    },
    {
      title: 'Issue',
      dataIndex: 'title',
      key: 'title',
      render: (title, record) => (
        <div>
          <Text strong>{title}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.resource_type}: {record.resource_name}
          </Text>
        </div>
      ),
    },
    {
      title: 'Namespace',
      dataIndex: 'namespace',
      key: 'namespace',
      width: 120,
      render: (ns) => <Tag>{ns || 'default'}</Tag>,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => (
        <Badge 
          status={status === 'detected' ? 'processing' : status === 'fixed' ? 'success' : 'default'} 
          text={status}
        />
      ),
    },
    {
      title: 'Detected',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (date) => new Date(date).toLocaleString(),
    },
    {
      title: 'Action',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Tooltip title="View RCA">
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => showRCA(record)}
          >
            RCA
          </Button>
        </Tooltip>
      ),
    },
  ]

  const rcaColumns = [
    {
      title: 'Issue',
      dataIndex: 'title',
      key: 'title',
    },
    {
      title: 'Root Cause',
      dataIndex: 'root_cause',
      key: 'root_cause',
      render: (cause) => cause || <Text type="secondary">Analyzing...</Text>,
    },
    {
      title: 'Pattern',
      dataIndex: 'pattern_id',
      key: 'pattern_id',
      render: (pattern) => pattern ? <Tag color="blue">{pattern}</Tag> : '-',
    },
    {
      title: 'Confidence',
      key: 'confidence',
      render: () => (
        <Tag color="green">High</Tag>
      ),
    },
  ]

  const anomalies = issues.filter(i => i.status === 'detected')
  const rcaResults = issues.filter(i => i.root_cause)

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <AlertOutlined style={{ fontSize: 24, color: '#06AC38' }} />
          <Title level={3} style={{ margin: 0 }}>Observability List</Title>
        </Space>
        <Button icon={<ReloadOutlined />} onClick={fetchIssues} loading={loading}>
          Refresh
        </Button>
      </div>

      {/* Stats */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic 
              title="Total Issues" 
              value={stats.total} 
              prefix={<AlertOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic 
              title="High Severity" 
              value={stats.by_severity?.high || 0} 
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic 
              title="Active" 
              value={stats.by_status?.detected || 0} 
              valueStyle={{ color: '#1890ff' }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic 
              title="Resolved" 
              value={stats.by_status?.fixed || 0} 
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* Tabs */}
      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab}>
          <TabPane 
            tab={
              <Space>
                <AlertOutlined />
                Anomaly Detection
                <Badge count={anomalies.length} style={{ backgroundColor: '#ff4d4f' }} />
              </Space>
            } 
            key="anomalies"
          >
            <Table
              columns={anomalyColumns}
              dataSource={anomalies}
              rowKey="id"
              loading={loading}
              pagination={{ pageSize: 10 }}
              locale={{ emptyText: <Empty description="No anomalies detected" /> }}
            />
          </TabPane>
          
          <TabPane 
            tab={
              <Space>
                <SearchOutlined />
                RCA Results
                <Badge count={rcaResults.length} style={{ backgroundColor: '#52c41a' }} />
              </Space>
            } 
            key="rca"
          >
            <Table
              columns={rcaColumns}
              dataSource={rcaResults}
              rowKey="id"
              loading={loading}
              pagination={{ pageSize: 10 }}
              locale={{ emptyText: <Empty description="No RCA results yet" /> }}
            />
          </TabPane>
        </Tabs>
      </Card>

      {/* RCA Modal */}
      <RCAModal 
        visible={rcaModalVisible}
        issue={selectedIssue}
        onClose={() => setRcaModalVisible(false)}
      />
    </div>
  )
}

export default ObservabilityList
