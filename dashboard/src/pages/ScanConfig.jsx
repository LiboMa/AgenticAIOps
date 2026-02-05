import { useState, useEffect } from 'react'
import { Card, Select, Button, Checkbox, Row, Col, Spin, Alert, Typography, Space, Tag, Table, Progress, Badge, message, Tabs } from 'antd'
import { 
  CloudServerOutlined, 
  GlobalOutlined, 
  ScanOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
  DatabaseOutlined,
  CodeOutlined,
  LockOutlined,
  FolderOutlined,
  ClusterOutlined,
  CloudOutlined,
  ApiOutlined,
  HddOutlined,
  WifiOutlined,
} from '@ant-design/icons'

const { Title, Text, Paragraph } = Typography
const { Option } = Select

// All AWS Services organized by category (from AWS API)
const ALL_SERVICES = [
  // Compute
  { key: 'ec2', name: 'Amazon EC2', category: 'Compute', description: 'Elastic Compute Cloud - Virtual servers' },
  { key: 'lambda', name: 'AWS Lambda', category: 'Compute', description: 'Serverless compute' },
  { key: 'eks', name: 'Amazon EKS', category: 'Compute', description: 'Elastic Kubernetes Service' },
  { key: 'ecs', name: 'Amazon ECS', category: 'Compute', description: 'Elastic Container Service' },
  { key: 'lightsail', name: 'Amazon Lightsail', category: 'Compute', description: 'Simple virtual servers' },
  { key: 'batch', name: 'AWS Batch', category: 'Compute', description: 'Batch computing' },
  { key: 'elasticbeanstalk', name: 'Elastic Beanstalk', category: 'Compute', description: 'Web app deployment' },
  
  // Storage
  { key: 's3', name: 'Amazon S3', category: 'Storage', description: 'Simple Storage Service' },
  { key: 'ebs', name: 'Amazon EBS', category: 'Storage', description: 'Elastic Block Store' },
  { key: 'efs', name: 'Amazon EFS', category: 'Storage', description: 'Elastic File System' },
  { key: 'glacier', name: 'S3 Glacier', category: 'Storage', description: 'Archive storage' },
  { key: 'fsx', name: 'Amazon FSx', category: 'Storage', description: 'Managed file systems' },
  
  // Database
  { key: 'rds', name: 'Amazon RDS', category: 'Database', description: 'Relational Database Service' },
  { key: 'dynamodb', name: 'Amazon DynamoDB', category: 'Database', description: 'NoSQL database' },
  { key: 'elasticache', name: 'Amazon ElastiCache', category: 'Database', description: 'In-memory caching' },
  { key: 'redshift', name: 'Amazon Redshift', category: 'Database', description: 'Data warehouse' },
  { key: 'aurora', name: 'Amazon Aurora', category: 'Database', description: 'MySQL/PostgreSQL compatible' },
  { key: 'documentdb', name: 'Amazon DocumentDB', category: 'Database', description: 'MongoDB compatible' },
  
  // Networking
  { key: 'vpc', name: 'Amazon VPC', category: 'Networking', description: 'Virtual Private Cloud' },
  { key: 'elb', name: 'Elastic Load Balancing', category: 'Networking', description: 'Load balancers' },
  { key: 'cloudfront', name: 'Amazon CloudFront', category: 'Networking', description: 'CDN' },
  { key: 'route53', name: 'Amazon Route 53', category: 'Networking', description: 'DNS service' },
  { key: 'apigateway', name: 'Amazon API Gateway', category: 'Networking', description: 'API management' },
  { key: 'directconnect', name: 'AWS Direct Connect', category: 'Networking', description: 'Dedicated network' },
  
  // Monitoring
  { key: 'cloudwatch', name: 'Amazon CloudWatch', category: 'Monitoring', description: 'Monitoring and observability' },
  { key: 'cloudtrail', name: 'AWS CloudTrail', category: 'Monitoring', description: 'API activity logging' },
  { key: 'xray', name: 'AWS X-Ray', category: 'Monitoring', description: 'Distributed tracing' },
  
  // Security
  { key: 'iam', name: 'AWS IAM', category: 'Security', description: 'Identity and Access Management' },
  { key: 'kms', name: 'AWS KMS', category: 'Security', description: 'Key Management Service' },
  { key: 'secretsmanager', name: 'AWS Secrets Manager', category: 'Security', description: 'Secret management' },
  { key: 'waf', name: 'AWS WAF', category: 'Security', description: 'Web Application Firewall' },
  { key: 'guardduty', name: 'Amazon GuardDuty', category: 'Security', description: 'Threat detection' },
]

// Services that are currently supported (can be selected)
const SUPPORTED_SERVICES = ['ec2', 'lambda', 'eks', 's3', 'rds', 'iam', 'cloudwatch']

// Initial selected services
const INITIAL_SERVICES = ['ec2', 'lambda', 'eks', 's3', 'rds']

// Category colors
const CATEGORY_COLORS = {
  'Compute': '#1890ff',
  'Storage': '#52c41a',
  'Database': '#722ed1',
  'Networking': '#fa8c16',
  'Monitoring': '#eb2f96',
  'Security': '#f5222d',
}

// Category icons
const CATEGORY_ICONS = {
  'Compute': <CloudServerOutlined />,
  'Storage': <FolderOutlined />,
  'Database': <DatabaseOutlined />,
  'Networking': <WifiOutlined />,
  'Monitoring': <ScanOutlined />,
  'Security': <LockOutlined />,
}

function ScanConfig({ apiUrl, onScanComplete }) {
  const [account, setAccount] = useState(null)
  const [selectedRegion, setSelectedRegion] = useState('ap-southeast-1')
  const [selectedServices, setSelectedServices] = useState(INITIAL_SERVICES)
  const [scanning, setScanning] = useState(false)
  const [scanResults, setScanResults] = useState(null)
  const [error, setError] = useState(null)

  // Fetch account info on mount
  useEffect(() => {
    fetchAccountInfo()
  }, [apiUrl])

  const fetchAccountInfo = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/scanner/account`)
      const data = await response.json()
      setAccount(data)
    } catch (err) {
      console.error('Failed to fetch account:', err)
      setError('无法获取 AWS 账号信息，请检查 IAM 权限')
    }
  }

  const handleRegionChange = async (value) => {
    setSelectedRegion(value)
    try {
      await fetch(`${apiUrl}/api/scanner/region`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ region: value })
      })
    } catch (err) {
      console.error('Failed to set region:', err)
    }
  }

  const handleServiceToggle = (serviceKey, checked) => {
    if (checked) {
      setSelectedServices(prev => [...prev, serviceKey])
    } else {
      setSelectedServices(prev => prev.filter(s => s !== serviceKey))
    }
  }

  const handleSelectAll = () => {
    setSelectedServices(SUPPORTED_SERVICES)
  }

  const handleSelectNone = () => {
    setSelectedServices([])
  }

  const handleScan = async () => {
    if (selectedServices.length === 0) {
      message.warning('请至少选择一个服务')
      return
    }

    setScanning(true)
    setScanResults(null)
    setError(null)

    try {
      const results = {}
      for (const service of selectedServices) {
        if (SUPPORTED_SERVICES.includes(service)) {
          try {
            const response = await fetch(`${apiUrl}/api/scanner/service/${service}`)
            const data = await response.json()
            results[service] = data.data || data
          } catch (err) {
            results[service] = { error: err.message }
          }
        }
      }

      setScanResults(results)
      message.success(`扫描完成！已扫描 ${Object.keys(results).length} 个服务`)
      
      if (onScanComplete) {
        onScanComplete(results)
      }
    } catch (err) {
      setError('扫描失败: ' + err.message)
    } finally {
      setScanning(false)
    }
  }

  // Table columns for service selection
  const serviceColumns = [
    {
      title: '选择',
      dataIndex: 'select',
      key: 'select',
      width: 60,
      render: (_, record) => (
        <Checkbox
          checked={selectedServices.includes(record.key)}
          disabled={!SUPPORTED_SERVICES.includes(record.key)}
          onChange={(e) => handleServiceToggle(record.key, e.target.checked)}
        />
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 120,
      render: (category) => (
        <Space>
          <span style={{ color: CATEGORY_COLORS[category] }}>{CATEGORY_ICONS[category]}</span>
          <Text style={{ color: CATEGORY_COLORS[category] }}>{category}</Text>
        </Space>
      ),
      filters: [...new Set(ALL_SERVICES.map(s => s.category))].map(c => ({ text: c, value: c })),
      onFilter: (value, record) => record.category === value,
    },
    {
      title: '服务',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <span style={{ color: SUPPORTED_SERVICES.includes(record.key) ? 'inherit' : '#999' }}>
          {name}
        </span>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      render: (desc, record) => (
        <Text type="secondary" style={{ color: SUPPORTED_SERVICES.includes(record.key) ? undefined : '#ccc' }}>
          {desc}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (_, record) => (
        SUPPORTED_SERVICES.includes(record.key) 
          ? <Tag color="green">✅ 已支持</Tag>
          : <Tag color="default">⏳ Coming Soon</Tag>
      ),
    },
  ]

  // Table columns for scan results
  const resultColumns = [
    {
      title: '服务',
      dataIndex: 'service',
      key: 'service',
      render: (service) => (
        <Space>
          <CloudOutlined />
          <Text strong>{service.toUpperCase()}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (_, record) => (
        record.error 
          ? <Tag color="red">❌ Error</Tag>
          : <Tag color="green">✅ Success</Tag>
      ),
    },
    {
      title: '资源数量',
      dataIndex: 'count',
      key: 'count',
      render: (_, record) => {
        const count = record.data?.count || 
                     record.data?.instances?.length || 
                     record.data?.functions?.length || 
                     record.data?.buckets?.length ||
                     record.data?.clusters?.length || 0
        return <Text strong>{count}</Text>
      },
    },
    {
      title: '详情',
      dataIndex: 'details',
      key: 'details',
      render: (_, record) => {
        if (record.error) return <Text type="danger">{record.error}</Text>
        if (record.data?.status) {
          return `Running: ${record.data.status.running || 0}, Stopped: ${record.data.status.stopped || 0}`
        }
        if (record.data?.public_count > 0) {
          return <Tag color="orange">⚠️ {record.data.public_count} 公开</Tag>
        }
        return '-'
      },
    },
  ]

  // Prepare result data for table
  const resultData = scanResults ? Object.entries(scanResults).map(([service, data]) => ({
    key: service,
    service,
    data,
    error: data.error,
  })) : []

  // Popular regions for quick selection
  const popularRegions = [
    { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore)' },
    { value: 'us-east-1', label: 'US East (N. Virginia)' },
    { value: 'us-west-2', label: 'US West (Oregon)' },
    { value: 'eu-west-1', label: 'Europe (Ireland)' },
    { value: 'ap-northeast-1', label: 'Asia Pacific (Tokyo)' },
    { value: 'ap-northeast-2', label: 'Asia Pacific (Seoul)' },
    { value: 'eu-central-1', label: 'Europe (Frankfurt)' },
    { value: 'ap-south-1', label: 'Asia Pacific (Mumbai)' },
  ]

  return (
    <div style={{ padding: 24, maxHeight: 'calc(100vh - 100px)', overflow: 'auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <Space>
          <ScanOutlined style={{ fontSize: 24, color: '#06AC38' }} />
          <Title level={3} style={{ margin: 0 }}>AWS 资源扫描与监控</Title>
        </Space>
        <Paragraph type="secondary" style={{ marginTop: 8 }}>
          选择账号、区域和服务，扫描 AWS 资源并添加到监控
          <Text type="secondary" style={{ marginLeft: 8 }}>
            (数据源: AWS Regional Services API)
          </Text>
        </Paragraph>
      </div>

      {error && (
        <Alert 
          message="错误" 
          description={error} 
          type="error" 
          showIcon 
          closable 
          style={{ marginBottom: 16 }}
          onClose={() => setError(null)}
        />
      )}

      <Row gutter={24}>
        {/* Left: Account & Region & Actions */}
        <Col span={6}>
          {/* Account Info */}
          <Card title="🔐 AWS 账号" size="small" style={{ marginBottom: 16 }}>
            {account ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                <div>
                  <Text type="secondary">Account ID: </Text>
                  <Text strong copyable>{account.account_id}</Text>
                </div>
                <div>
                  <Text type="secondary">IAM Role: </Text>
                  <Tag color="blue">{account.arn?.split('/').pop() || 'Default'}</Tag>
                </div>
              </Space>
            ) : (
              <Spin size="small" /> 
            )}
          </Card>

          {/* Region Selection */}
          <Card title="🌍 选择区域" size="small" style={{ marginBottom: 16 }}>
            <Select
              value={selectedRegion}
              onChange={handleRegionChange}
              style={{ width: '100%' }}
              showSearch
              placeholder="选择 AWS 区域"
              optionFilterProp="children"
            >
              {popularRegions.map(region => (
                <Option key={region.value} value={region.value}>
                  <GlobalOutlined /> {region.value}
                </Option>
              ))}
            </Select>
          </Card>

          {/* Quick Actions */}
          <Card title="⚡ 操作" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <div>
                <Text type="secondary">已选择: </Text>
                <Badge count={selectedServices.length} style={{ backgroundColor: '#06AC38' }} />
                <Text type="secondary"> / {SUPPORTED_SERVICES.length} 个服务</Text>
              </div>
              <Button block size="small" onClick={handleSelectAll}>全选已支持</Button>
              <Button block size="small" onClick={handleSelectNone}>清空选择</Button>
              <Button 
                type="primary" 
                block
                size="large"
                icon={<ScanOutlined />}
                onClick={handleScan}
                loading={scanning}
                disabled={selectedServices.length === 0}
                style={{ marginTop: 8, background: '#06AC38', borderColor: '#06AC38' }}
              >
                {scanning ? '扫描中...' : '开始扫描'}
              </Button>
            </Space>
          </Card>
        </Col>

        {/* Right: Service Selection Table */}
        <Col span={18}>
          <Card 
            title={
              <Space>
                <CloudOutlined />
                <span>AWS 服务列表</span>
                <Tag color="green">{SUPPORTED_SERVICES.length} 个已支持</Tag>
                <Tag color="default">{ALL_SERVICES.length - SUPPORTED_SERVICES.length} 个 Coming Soon</Tag>
              </Space>
            }
            size="small"
          >
            <Table
              columns={serviceColumns}
              dataSource={ALL_SERVICES}
              rowKey="key"
              size="small"
              pagination={false}
              scroll={{ y: 400 }}
              rowClassName={(record) => 
                SUPPORTED_SERVICES.includes(record.key) ? '' : 'disabled-row'
              }
            />
          </Card>
        </Col>
      </Row>

      {/* Scan Progress */}
      {scanning && (
        <Card style={{ marginTop: 16 }}>
          <Progress percent={99} status="active" />
          <Text type="secondary">正在扫描 {selectedRegion} 区域的 {selectedServices.length} 个服务...</Text>
        </Card>
      )}

      {/* Scan Results Table */}
      {scanResults && (
        <Card title="📊 扫描结果" style={{ marginTop: 16 }}>
          <Table
            columns={resultColumns}
            dataSource={resultData}
            rowKey="key"
            size="small"
            pagination={false}
          />
        </Card>
      )}

      <style>{`
        .disabled-row {
          background-color: #fafafa;
        }
        .disabled-row td {
          color: #999 !important;
        }
      `}</style>
    </div>
  )
}

export default ScanConfig
