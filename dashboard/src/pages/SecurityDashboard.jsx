import { useState, useEffect } from 'react'
import { Card, Table, Tag, Row, Col, Statistic, Collapse, Badge, Empty, Spin, Typography, Button, Space } from 'antd'
import { 
  SafetyCertificateOutlined, 
  LockOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  CloudServerOutlined,
  ApiOutlined,
  DatabaseOutlined,
  FolderOutlined,
  ReloadOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'

const { Title, Text } = Typography
const { Panel } = Collapse

// AWS Service icons
const SERVICE_ICONS = {
  ec2: <CloudServerOutlined />,
  lambda: <ApiOutlined />,
  s3: <FolderOutlined />,
  rds: <DatabaseOutlined />,
  iam: <LockOutlined />,
  security_hub: <SafetyCertificateOutlined />,
  guardduty: <WarningOutlined />,
}

// Mock security data (in real impl, from API)
const MOCK_SECURITY_DATA = {
  summary: {
    total: 12,
    critical: 2,
    high: 3,
    medium: 5,
    low: 2,
  },
  by_service: {
    iam: {
      name: 'IAM',
      icon: 'iam',
      findings: [
        { id: 1, title: 'Root account MFA not enabled', severity: 'critical', status: 'open' },
        { id: 2, title: 'Access keys older than 90 days', severity: 'high', status: 'open' },
        { id: 3, title: 'Unused IAM credentials', severity: 'medium', status: 'open' },
      ]
    },
    s3: {
      name: 'S3',
      icon: 's3',
      findings: [
        { id: 4, title: 'Public bucket detected: static-website-bucket', severity: 'high', status: 'open' },
        { id: 5, title: 'Bucket without encryption: backup-bucket', severity: 'medium', status: 'open' },
        { id: 6, title: 'No bucket versioning: logs-bucket', severity: 'low', status: 'open' },
      ]
    },
    ec2: {
      name: 'EC2',
      icon: 'ec2',
      findings: [
        { id: 7, title: 'Security group allows 0.0.0.0/0 on port 22', severity: 'critical', status: 'open' },
        { id: 8, title: 'Instance without IMDSv2', severity: 'medium', status: 'open' },
      ]
    },
    rds: {
      name: 'RDS',
      icon: 'rds',
      findings: [
        { id: 9, title: 'Public accessibility enabled', severity: 'high', status: 'open' },
        { id: 10, title: 'Encryption at rest disabled', severity: 'medium', status: 'open' },
      ]
    },
    lambda: {
      name: 'Lambda',
      icon: 'lambda',
      findings: [
        { id: 11, title: 'Function using deprecated runtime', severity: 'low', status: 'open' },
        { id: 12, title: 'Overly permissive execution role', severity: 'medium', status: 'open' },
      ]
    },
  }
}

// Severity tag
const SeverityTag = ({ severity }) => {
  const config = {
    critical: { color: '#cf1322', text: 'CRITICAL' },
    high: { color: '#ff4d4f', text: 'HIGH' },
    medium: { color: '#faad14', text: 'MEDIUM' },
    low: { color: '#52c41a', text: 'LOW' },
  }
  const cfg = config[severity] || config.low
  return <Tag color={cfg.color}>{cfg.text}</Tag>
}

function SecurityDashboard({ apiUrl }) {
  const [securityData, setSecurityData] = useState(MOCK_SECURITY_DATA)
  const [loading, setLoading] = useState(false)
  const [expandedServices, setExpandedServices] = useState(['iam', 's3'])

  const fetchSecurityData = async () => {
    setLoading(true)
    try {
      // In real implementation, fetch from API
      // const response = await fetch(`${apiUrl}/api/security/findings`)
      // const data = await response.json()
      // setSecurityData(data)
      
      // For now, use mock data
      await new Promise(resolve => setTimeout(resolve, 500))
      setSecurityData(MOCK_SECURITY_DATA)
    } catch (error) {
      console.error('Failed to fetch security data:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSecurityData()
  }, [])

  const columns = [
    {
      title: 'Finding',
      dataIndex: 'title',
      key: 'title',
      render: (title) => <Text>{title}</Text>,
    },
    {
      title: 'Severity',
      dataIndex: 'severity',
      key: 'severity',
      width: 120,
      render: (severity) => <SeverityTag severity={severity} />,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => (
        <Badge 
          status={status === 'open' ? 'error' : 'success'} 
          text={status === 'open' ? 'Open' : 'Resolved'}
        />
      ),
    },
  ]

  const summary = securityData.summary

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <SafetyCertificateOutlined style={{ fontSize: 24, color: '#06AC38' }} />
          <Title level={3} style={{ margin: 0 }}>Security Dashboard</Title>
        </Space>
        <Button icon={<ReloadOutlined />} onClick={fetchSecurityData} loading={loading}>
          Refresh
        </Button>
      </div>

      {/* Summary Stats */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic 
              title="Total Findings" 
              value={summary.total} 
              prefix={<SafetyCertificateOutlined />}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small">
            <Statistic 
              title="Critical" 
              value={summary.critical} 
              valueStyle={{ color: '#cf1322' }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small">
            <Statistic 
              title="High" 
              value={summary.high} 
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small">
            <Statistic 
              title="Medium" 
              value={summary.medium} 
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small">
            <Statistic 
              title="Low" 
              value={summary.low} 
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* Findings by Service */}
      <Card title="Security Findings by AWS Service" loading={loading}>
        <Collapse 
          activeKey={expandedServices}
          onChange={setExpandedServices}
        >
          {Object.entries(securityData.by_service).map(([key, service]) => {
            const criticalCount = service.findings.filter(f => f.severity === 'critical' || f.severity === 'high').length
            return (
              <Panel
                key={key}
                header={
                  <Space>
                    {SERVICE_ICONS[service.icon] || <CloudServerOutlined />}
                    <Text strong>{service.name}</Text>
                    <Badge 
                      count={service.findings.length} 
                      style={{ backgroundColor: criticalCount > 0 ? '#ff4d4f' : '#52c41a' }}
                    />
                    {criticalCount > 0 && (
                      <Tag color="red">{criticalCount} Critical/High</Tag>
                    )}
                  </Space>
                }
              >
                <Table
                  columns={columns}
                  dataSource={service.findings}
                  rowKey="id"
                  pagination={false}
                  size="small"
                />
              </Panel>
            )
          })}
        </Collapse>
        
        {Object.keys(securityData.by_service).length === 0 && (
          <Empty description="No security findings" />
        )}
      </Card>
    </div>
  )
}

export default SecurityDashboard
