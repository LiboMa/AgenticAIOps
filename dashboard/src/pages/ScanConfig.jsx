import { useState, useEffect } from 'react'
import { Card, Select, Button, Checkbox, Row, Col, Spin, Alert, Typography, Space, Tag, Divider, Progress, Collapse, Badge, message, Tabs } from 'antd'
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
const { Panel } = Collapse

// AWS Service Categories and Initial Services
const SERVICE_CATEGORIES = {
  compute: {
    name: 'Compute',
    icon: <CloudServerOutlined />,
    color: '#1890ff',
    services: [
      { key: 'ec2', name: 'Amazon EC2', description: 'Elastic Compute Cloud - Virtual servers' },
      { key: 'lambda', name: 'AWS Lambda', description: 'Serverless compute' },
      { key: 'eks', name: 'Amazon EKS', description: 'Elastic Kubernetes Service' },
      { key: 'ecs', name: 'Amazon ECS', description: 'Elastic Container Service' },
      { key: 'autoscaling', name: 'Auto Scaling', description: 'Automatic scaling' },
    ]
  },
  storage: {
    name: 'Storage',
    icon: <FolderOutlined />,
    color: '#52c41a',
    services: [
      { key: 's3', name: 'Amazon S3', description: 'Simple Storage Service' },
      { key: 'ebs', name: 'Amazon EBS', description: 'Elastic Block Store' },
      { key: 'efs', name: 'Amazon EFS', description: 'Elastic File System' },
      { key: 'glacier', name: 'S3 Glacier', description: 'Archive storage' },
    ]
  },
  database: {
    name: 'Database',
    icon: <DatabaseOutlined />,
    color: '#722ed1',
    services: [
      { key: 'rds', name: 'Amazon RDS', description: 'Relational Database Service' },
      { key: 'dynamodb', name: 'Amazon DynamoDB', description: 'NoSQL database' },
      { key: 'elasticache', name: 'ElastiCache', description: 'In-memory caching' },
      { key: 'redshift', name: 'Amazon Redshift', description: 'Data warehouse' },
    ]
  },
  networking: {
    name: 'Networking',
    icon: <WifiOutlined />,
    color: '#fa8c16',
    services: [
      { key: 'vpc', name: 'Amazon VPC', description: 'Virtual Private Cloud' },
      { key: 'elb', name: 'Elastic Load Balancing', description: 'Load balancers' },
      { key: 'cloudfront', name: 'CloudFront', description: 'CDN' },
      { key: 'route53', name: 'Route 53', description: 'DNS service' },
      { key: 'apigateway', name: 'API Gateway', description: 'API management' },
    ]
  },
  monitoring: {
    name: 'Monitoring',
    icon: <ScanOutlined />,
    color: '#eb2f96',
    services: [
      { key: 'cloudwatch', name: 'CloudWatch', description: 'Monitoring and observability' },
      { key: 'cloudtrail', name: 'CloudTrail', description: 'API activity logging' },
    ]
  },
  security: {
    name: 'Security',
    icon: <LockOutlined />,
    color: '#f5222d',
    services: [
      { key: 'iam', name: 'IAM', description: 'Identity and Access Management' },
      { key: 'kms', name: 'KMS', description: 'Key Management Service' },
      { key: 'secretsmanager', name: 'Secrets Manager', description: 'Secret management' },
    ]
  },
}

// Initial selected services (as requested by Ma Ronnie)
const INITIAL_SERVICES = ['ec2', 'lambda', 'eks', 's3', 'rds', 'vpc', 'cloudwatch']

function ScanConfig({ apiUrl, onScanComplete }) {
  const [account, setAccount] = useState(null)
  const [regions, setRegions] = useState([])
  const [awsRegionServices, setAwsRegionServices] = useState(null)
  const [selectedRegion, setSelectedRegion] = useState('ap-southeast-1')
  const [selectedServices, setSelectedServices] = useState(INITIAL_SERVICES)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanResults, setScanResults] = useState(null)
  const [error, setError] = useState(null)
  const [activeCategory, setActiveCategory] = useState(['compute', 'storage', 'database', 'networking'])

  // Fetch account info and regions on mount
  useEffect(() => {
    fetchAccountInfo()
    fetchRegions()
    fetchAwsRegionServices()
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

  const fetchRegions = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/scanner/regions`)
      const data = await response.json()
      setRegions(data.all || [])
      setSelectedRegion(data.current || 'ap-southeast-1')
    } catch (err) {
      console.error('Failed to fetch regions:', err)
    }
  }

  const fetchAwsRegionServices = async () => {
    try {
      // Fetch from AWS official API
      const response = await fetch('https://api.regional-table.region-services.aws.a2z.com/index.json')
      const data = await response.json()
      setAwsRegionServices(data)
      console.log('AWS Region Services loaded:', data.prices?.length, 'entries')
    } catch (err) {
      console.error('Failed to fetch AWS region services:', err)
      // Non-blocking - we have fallback categories
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

  const handleServiceToggle = (serviceKey) => {
    setSelectedServices(prev => 
      prev.includes(serviceKey)
        ? prev.filter(s => s !== serviceKey)
        : [...prev, serviceKey]
    )
  }

  const handleCategoryToggle = (categoryKey) => {
    const categoryServices = SERVICE_CATEGORIES[categoryKey].services.map(s => s.key)
    const allSelected = categoryServices.every(s => selectedServices.includes(s))
    
    if (allSelected) {
      // Deselect all in category
      setSelectedServices(prev => prev.filter(s => !categoryServices.includes(s)))
    } else {
      // Select all in category
      setSelectedServices(prev => [...new Set([...prev, ...categoryServices])])
    }
  }

  const handleSelectAll = () => {
    const allServices = Object.values(SERVICE_CATEGORIES).flatMap(cat => cat.services.map(s => s.key))
    setSelectedServices(allServices)
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
      // Scan each selected service that we support
      const supportedServices = ['ec2', 'lambda', 's3', 'rds', 'eks', 'iam', 'cloudwatch']
      const servicesToScan = selectedServices.filter(s => supportedServices.includes(s))
      
      const results = {}
      for (const service of servicesToScan) {
        try {
          const response = await fetch(`${apiUrl}/api/scanner/service/${service}`)
          const data = await response.json()
          results[service] = data.data || data
        } catch (err) {
          results[service] = { error: err.message }
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

  const getCategorySelectedCount = (categoryKey) => {
    const categoryServices = SERVICE_CATEGORIES[categoryKey].services.map(s => s.key)
    return categoryServices.filter(s => selectedServices.includes(s)).length
  }

  const renderServiceCard = (service, categoryColor) => {
    const isSelected = selectedServices.includes(service.key)
    const isSupported = ['ec2', 'lambda', 's3', 'rds', 'eks', 'iam', 'cloudwatch'].includes(service.key)
    
    return (
      <Col span={12} key={service.key}>
        <Card 
          hoverable={isSupported}
          size="small"
          onClick={() => isSupported && handleServiceToggle(service.key)}
          style={{ 
            cursor: isSupported ? 'pointer' : 'not-allowed',
            borderColor: isSelected ? categoryColor : '#d9d9d9',
            background: isSelected ? `${categoryColor}10` : '#fff',
            opacity: isSupported ? 1 : 0.5,
          }}
        >
          <Space>
            <Checkbox 
              checked={isSelected} 
              disabled={!isSupported}
              onClick={e => e.stopPropagation()}
              onChange={() => isSupported && handleServiceToggle(service.key)}
            />
            <div>
              <Text strong style={{ fontSize: 13 }}>{service.name}</Text>
              {!isSupported && <Tag color="default" style={{ marginLeft: 4 }}>Soon</Tag>}
              <br />
              <Text type="secondary" style={{ fontSize: 11 }}>{service.description}</Text>
            </div>
          </Space>
        </Card>
      </Col>
    )
  }

  const renderScanResults = () => {
    if (!scanResults) return null

    return (
      <Card title="📊 扫描结果" style={{ marginTop: 24 }}>
        <Row gutter={[16, 16]}>
          {Object.entries(scanResults).map(([service, data]) => {
            const count = data.count || data.instances?.length || data.functions?.length || data.buckets?.length || data.clusters?.length || 0
            const hasError = !!data.error

            return (
              <Col span={8} key={service}>
                <Card 
                  size="small" 
                  style={{ 
                    borderColor: hasError ? '#ff4d4f' : '#52c41a',
                    background: hasError ? '#fff2f0' : '#f6ffed'
                  }}
                >
                  <Space>
                    <CloudOutlined />
                    <Text strong>{service.toUpperCase()}</Text>
                  </Space>
                  <div style={{ marginTop: 8 }}>
                    {hasError ? (
                      <Tag color="red">Error</Tag>
                    ) : (
                      <Tag color="green">{count} 资源</Tag>
                    )}
                  </div>
                  {data.status && (
                    <div style={{ marginTop: 4, fontSize: 12, color: '#666' }}>
                      Running: {data.status.running || 0}, Stopped: {data.status.stopped || 0}
                    </div>
                  )}
                  {data.public_count > 0 && (
                    <Tag color="orange" style={{ marginTop: 4 }}>⚠️ {data.public_count} 公开</Tag>
                  )}
                </Card>
              </Col>
            )
          })}
        </Row>
      </Card>
    )
  }

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
        {/* Left: Account & Region */}
        <Col span={8}>
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
                  <GlobalOutlined /> {region.value} - {region.label}
                </Option>
              ))}
            </Select>
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                数据来源: AWS Regional Services API
              </Text>
            </div>
          </Card>

          {/* Quick Actions */}
          <Card title="⚡ 快速操作" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button block onClick={handleSelectAll}>全选所有服务</Button>
              <Button block onClick={handleSelectNone}>清空选择</Button>
              <Divider style={{ margin: '12px 0' }} />
              <Button 
                type="primary" 
                block
                size="large"
                icon={<ScanOutlined />}
                onClick={handleScan}
                loading={scanning}
                disabled={selectedServices.length === 0}
                style={{ background: '#06AC38', borderColor: '#06AC38' }}
              >
                {scanning ? '扫描中...' : `开始扫描 (${selectedServices.length} 服务)`}
              </Button>
            </Space>
          </Card>
        </Col>

        {/* Right: Service Selection */}
        <Col span={16}>
          <Card 
            title={
              <Space>
                <CloudOutlined />
                <span>选择要监控的 AWS 服务</span>
                <Badge count={selectedServices.length} style={{ backgroundColor: '#06AC38' }} />
              </Space>
            }
            size="small"
          >
            <Collapse 
              activeKey={activeCategory}
              onChange={setActiveCategory}
              bordered={false}
            >
              {Object.entries(SERVICE_CATEGORIES).map(([categoryKey, category]) => {
                const selectedCount = getCategorySelectedCount(categoryKey)
                const totalCount = category.services.length
                
                return (
                  <Panel
                    key={categoryKey}
                    header={
                      <Space>
                        <span style={{ color: category.color }}>{category.icon}</span>
                        <Text strong>{category.name}</Text>
                        <Tag color={selectedCount === totalCount ? 'green' : selectedCount > 0 ? 'blue' : 'default'}>
                          {selectedCount}/{totalCount}
                        </Tag>
                        <Button 
                          size="small" 
                          type="link"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleCategoryToggle(categoryKey)
                          }}
                        >
                          {selectedCount === totalCount ? '取消全选' : '全选'}
                        </Button>
                      </Space>
                    }
                  >
                    <Row gutter={[8, 8]}>
                      {category.services.map(service => renderServiceCard(service, category.color))}
                    </Row>
                  </Panel>
                )
              })}
            </Collapse>
          </Card>
        </Col>
      </Row>

      {/* Scan Progress */}
      {scanning && (
        <Card style={{ marginTop: 16 }}>
          <Progress percent={99} status="active" />
          <Text type="secondary">正在扫描 {selectedRegion} 区域的资源...</Text>
        </Card>
      )}

      {/* Scan Results */}
      {renderScanResults()}
    </div>
  )
}

export default ScanConfig
