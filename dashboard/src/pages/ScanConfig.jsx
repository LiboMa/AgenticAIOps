import { useState, useEffect } from 'react'
import { Card, Select, Button, Checkbox, Row, Col, Spin, Alert, Typography, Space, Tag, Divider, Progress, List, Badge, message } from 'antd'
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
} from '@ant-design/icons'

const { Title, Text, Paragraph } = Typography
const { Option } = Select

// AWS Service definitions
const AWS_SERVICES = [
  { key: 'ec2', name: 'EC2', icon: <CloudServerOutlined />, description: 'Elastic Compute Cloud instances' },
  { key: 'lambda', name: 'Lambda', icon: <CodeOutlined />, description: 'Serverless functions' },
  { key: 's3', name: 'S3', icon: <FolderOutlined />, description: 'Simple Storage Service buckets' },
  { key: 'rds', name: 'RDS', icon: <DatabaseOutlined />, description: 'Relational databases' },
  { key: 'eks', name: 'EKS', icon: <ClusterOutlined />, description: 'Elastic Kubernetes Service' },
  { key: 'iam', name: 'IAM', icon: <LockOutlined />, description: 'Identity and Access Management' },
  { key: 'cloudwatch', name: 'CloudWatch', icon: <ScanOutlined />, description: 'Monitoring and alarms' },
]

function ScanConfig({ apiUrl, onScanComplete }) {
  const [account, setAccount] = useState(null)
  const [regions, setRegions] = useState([])
  const [selectedRegion, setSelectedRegion] = useState('ap-southeast-1')
  const [selectedServices, setSelectedServices] = useState(['ec2', 'lambda', 's3', 'rds'])
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanResults, setScanResults] = useState(null)
  const [error, setError] = useState(null)

  // Fetch account info and regions on mount
  useEffect(() => {
    fetchAccountInfo()
    fetchRegions()
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

  const handleSelectAll = () => {
    setSelectedServices(AWS_SERVICES.map(s => s.key))
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
      // Scan each selected service
      const results = {}
      for (const service of selectedServices) {
        try {
          const response = await fetch(`${apiUrl}/api/scanner/service/${service}`)
          const data = await response.json()
          results[service] = data.data || data
        } catch (err) {
          results[service] = { error: err.message }
        }
      }

      setScanResults(results)
      message.success('扫描完成！')
      
      if (onScanComplete) {
        onScanComplete(results)
      }
    } catch (err) {
      setError('扫描失败: ' + err.message)
    } finally {
      setScanning(false)
    }
  }

  const renderScanResults = () => {
    if (!scanResults) return null

    return (
      <Card title="📊 扫描结果" style={{ marginTop: 24 }}>
        <Row gutter={[16, 16]}>
          {Object.entries(scanResults).map(([service, data]) => {
            const serviceInfo = AWS_SERVICES.find(s => s.key === service)
            const count = data.count || data.instances?.length || data.functions?.length || data.buckets?.length || 0
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
                    {serviceInfo?.icon}
                    <Text strong>{serviceInfo?.name || service}</Text>
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

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <Space>
          <ScanOutlined style={{ fontSize: 24, color: '#06AC38' }} />
          <Title level={3} style={{ margin: 0 }}>AWS 资源扫描</Title>
        </Space>
        <Paragraph type="secondary" style={{ marginTop: 8 }}>
          选择账号、区域和服务，扫描您的 AWS 资源进行监控
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

      {/* Account Info */}
      <Card title="🔐 AWS 账号" style={{ marginBottom: 16 }}>
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
      <Card title="🌍 选择区域" style={{ marginBottom: 16 }}>
        <Select
          value={selectedRegion}
          onChange={handleRegionChange}
          style={{ width: 300 }}
          showSearch
          placeholder="选择 AWS 区域"
        >
          <Option value="ap-southeast-1">
            <GlobalOutlined /> ap-southeast-1 (Singapore)
          </Option>
          <Option value="us-east-1">
            <GlobalOutlined /> us-east-1 (N. Virginia)
          </Option>
          <Option value="us-west-2">
            <GlobalOutlined /> us-west-2 (Oregon)
          </Option>
          <Option value="eu-west-1">
            <GlobalOutlined /> eu-west-1 (Ireland)
          </Option>
          <Option value="ap-northeast-1">
            <GlobalOutlined /> ap-northeast-1 (Tokyo)
          </Option>
          {regions.filter(r => !['ap-southeast-1', 'us-east-1', 'us-west-2', 'eu-west-1', 'ap-northeast-1'].includes(r.name)).map(region => (
            <Option key={region.name} value={region.name}>
              <GlobalOutlined /> {region.name}
            </Option>
          ))}
        </Select>
      </Card>

      {/* Service Selection */}
      <Card 
        title="☁️ 选择服务" 
        extra={
          <Space>
            <Button size="small" onClick={handleSelectAll}>全选</Button>
            <Button size="small" onClick={handleSelectNone}>清空</Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Row gutter={[16, 16]}>
          {AWS_SERVICES.map(service => (
            <Col span={8} key={service.key}>
              <Card 
                hoverable
                size="small"
                onClick={() => handleServiceToggle(service.key)}
                style={{ 
                  cursor: 'pointer',
                  borderColor: selectedServices.includes(service.key) ? '#06AC38' : '#d9d9d9',
                  background: selectedServices.includes(service.key) ? '#f6ffed' : '#fff',
                }}
              >
                <Space>
                  <Checkbox checked={selectedServices.includes(service.key)} />
                  {service.icon}
                  <div>
                    <Text strong>{service.name}</Text>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>{service.description}</Text>
                  </div>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* Scan Button */}
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <div>
            <Text>已选择 </Text>
            <Badge count={selectedServices.length} style={{ backgroundColor: '#06AC38' }} />
            <Text> 个服务</Text>
          </div>
          <Button 
            type="primary" 
            size="large"
            icon={<ScanOutlined />}
            onClick={handleScan}
            loading={scanning}
            disabled={selectedServices.length === 0}
            style={{ background: '#06AC38', borderColor: '#06AC38' }}
          >
            {scanning ? '扫描中...' : '开始扫描'}
          </Button>
        </Space>

        {scanning && (
          <div style={{ marginTop: 16 }}>
            <Progress percent={99} status="active" />
            <Text type="secondary">正在扫描 {selectedRegion} 区域的资源...</Text>
          </div>
        )}
      </Card>

      {/* Scan Results */}
      {renderScanResults()}
    </div>
  )
}

export default ScanConfig
