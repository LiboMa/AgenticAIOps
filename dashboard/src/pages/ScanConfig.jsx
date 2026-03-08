import { useState, useEffect, useMemo } from 'react'
import { Card, Select, Button, Checkbox, Row, Col, Spin, Alert, Typography, Space, Tag, Table, Progress, Badge, message } from 'antd'
import { 
  CloudServerOutlined, 
  GlobalOutlined, 
  ScanOutlined,
  DatabaseOutlined,
  LockOutlined,
  FolderOutlined,
  WifiOutlined,
  CloudOutlined,
} from '@ant-design/icons'

const { Title, Text, Paragraph } = Typography
const { Option } = Select

// Services that are currently supported (can be selected and scanned)
const SUPPORTED_SERVICES = ['ec2', 'lambda', 'eks', 's3', 'rds', 'iam', 'cloudwatch', 'vpc', 'elb', 'route53', 'dynamodb', 'ecs', 'elasticache']

// Service to category mapping
const SERVICE_CATEGORY_MAP = {
  'Amazon EC2': 'Compute',
  'Amazon Elastic Compute Cloud (Amazon EC2)': 'Compute',
  'AWS Lambda': 'Compute',
  'Amazon Elastic Kubernetes Service (EKS)': 'Compute',
  'Amazon EKS': 'Compute',
  'Amazon Elastic Container Service': 'Compute',
  'Amazon ECS': 'Compute',
  'AWS Batch': 'Compute',
  'Amazon Lightsail': 'Compute',
  'AWS Elastic Beanstalk': 'Compute',
  
  'Amazon Simple Storage Service (S3)': 'Storage',
  'Amazon S3': 'Storage',
  'Amazon Elastic Block Store (EBS)': 'Storage',
  'Amazon EBS': 'Storage',
  'Amazon Elastic File System (EFS)': 'Storage',
  'Amazon EFS': 'Storage',
  'Amazon S3 Glacier': 'Storage',
  'AWS Storage Gateway': 'Storage',
  
  'Amazon RDS': 'Database',
  'Amazon Relational Database Service (RDS)': 'Database',
  'Amazon DynamoDB': 'Database',
  'Amazon ElastiCache': 'Database',
  'Amazon Redshift': 'Database',
  'Amazon Aurora': 'Database',
  'Amazon DocumentDB': 'Database',
  'Amazon Neptune': 'Database',
  
  'Amazon Virtual Private Cloud (VPC)': 'Networking',
  'Amazon VPC': 'Networking',
  'Elastic Load Balancing': 'Networking',
  'Amazon CloudFront': 'Networking',
  'Amazon Route 53': 'Networking',
  'Amazon API Gateway': 'Networking',
  'AWS Direct Connect': 'Networking',
  'AWS Transit Gateway': 'Networking',
  
  'Amazon CloudWatch': 'Monitoring',
  'AWS CloudTrail': 'Monitoring',
  'AWS X-Ray': 'Monitoring',
  'AWS Config': 'Monitoring',
  
  'AWS Identity and Access Management (IAM)': 'Security',
  'AWS IAM': 'Security',
  'AWS Key Management Service (KMS)': 'Security',
  'AWS KMS': 'Security',
  'AWS Secrets Manager': 'Security',
  'AWS WAF': 'Security',
  'Amazon GuardDuty': 'Security',
  'AWS Shield': 'Security',
}

// Service name to key mapping
const SERVICE_KEY_MAP = {
  'Amazon EC2': 'ec2',
  'Amazon Elastic Compute Cloud (Amazon EC2)': 'ec2',
  'AWS Lambda': 'lambda',
  'Amazon Elastic Kubernetes Service (EKS)': 'eks',
  'Amazon EKS': 'eks',
  'Amazon Simple Storage Service (S3)': 's3',
  'Amazon S3': 's3',
  'Amazon RDS': 'rds',
  'Amazon Relational Database Service (RDS)': 'rds',
  'Amazon CloudWatch': 'cloudwatch',
  'AWS Identity and Access Management (IAM)': 'iam',
  'AWS IAM': 'iam',
  'Amazon DynamoDB': 'dynamodb',
  'Amazon ElastiCache': 'elasticache',
  'Amazon VPC': 'vpc',
  'Amazon Virtual Private Cloud (VPC)': 'vpc',
  'Elastic Load Balancing': 'elb',
  'Amazon CloudFront': 'cloudfront',
  'Amazon Route 53': 'route53',
  'Amazon ECS': 'ecs',
  'Amazon Elastic Container Service': 'ecs',
}

// Category colors and icons
const CATEGORY_CONFIG = {
  'Compute': { color: '#1890ff', icon: <CloudServerOutlined /> },
  'Storage': { color: '#52c41a', icon: <FolderOutlined /> },
  'Database': { color: '#722ed1', icon: <DatabaseOutlined /> },
  'Networking': { color: '#fa8c16', icon: <WifiOutlined /> },
  'Monitoring': { color: '#eb2f96', icon: <ScanOutlined /> },
  'Security': { color: '#f5222d', icon: <LockOutlined /> },
  'Other': { color: '#666', icon: <CloudOutlined /> },
}

function ScanConfig({ apiUrl, onScanComplete }) {
  const [account, setAccount] = useState(null)
  const [awsServices, setAwsServices] = useState([])
  const [loadingServices, setLoadingServices] = useState(true)
  const [selectedRegion, setSelectedRegion] = useState('ap-southeast-1')
  const [selectedServices, setSelectedServices] = useState(['ec2', 's3', 'rds', 'lambda', 'eks'])
  const [scanning, setScanning] = useState(false)
  const [scanResults, setScanResults] = useState(null)
  const [error, setError] = useState(null)

  // Fetch account info and AWS services on mount
  useEffect(() => {
    fetchAccountInfo()
    fetchAwsServices()
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

  const fetchAwsServices = async () => {
    setLoadingServices(true)
    try {
      // Fetch from AWS Regional Services API
      const response = await fetch('https://api.regional-table.region-services.aws.a2z.com/index.json')
      const data = await response.json()
      
      // Parse and deduplicate services
      const servicesMap = new Map()
      
      for (const item of data.prices || []) {
        const serviceName = item.attributes?.['aws:serviceName']
        const serviceUrl = item.attributes?.['aws:serviceUrl']
        
        if (serviceName && !servicesMap.has(serviceName)) {
          const category = SERVICE_CATEGORY_MAP[serviceName] || 'Other'
          const key = SERVICE_KEY_MAP[serviceName] || serviceName.toLowerCase().replace(/[^a-z0-9]/g, '')
          
          servicesMap.set(serviceName, {
            key,
            name: serviceName,
            category,
            url: serviceUrl,
            supported: SUPPORTED_SERVICES.includes(key),
          })
        }
      }
      
      // Convert to array and sort by category then name
      const services = Array.from(servicesMap.values())
        .filter(s => ['Compute', 'Storage', 'Database', 'Networking', 'Monitoring', 'Security'].includes(s.category))
        .sort((a, b) => {
          const categoryOrder = ['Compute', 'Storage', 'Database', 'Networking', 'Monitoring', 'Security']
          const catDiff = categoryOrder.indexOf(a.category) - categoryOrder.indexOf(b.category)
          if (catDiff !== 0) return catDiff
          return a.name.localeCompare(b.name)
        })
      
      setAwsServices(services)
      console.log(`Loaded ${services.length} AWS services from API`)
    } catch (err) {
      console.error('Failed to fetch AWS services:', err)
      message.warning('无法加载 AWS 服务列表，使用默认列表')
      // Fallback to minimal list
      setAwsServices([
        { key: 'ec2', name: 'Amazon EC2', category: 'Compute', supported: true },
        { key: 'lambda', name: 'AWS Lambda', category: 'Compute', supported: true },
        { key: 'eks', name: 'Amazon EKS', category: 'Compute', supported: true },
        { key: 's3', name: 'Amazon S3', category: 'Storage', supported: true },
        { key: 'rds', name: 'Amazon RDS', category: 'Database', supported: true },
        { key: 'cloudwatch', name: 'Amazon CloudWatch', category: 'Monitoring', supported: true },
        { key: 'iam', name: 'AWS IAM', category: 'Security', supported: true },
      ])
    } finally {
      setLoadingServices(false)
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

  const handleSelectAllSupported = () => {
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
      const servicesToScan = selectedServices.filter(s => SUPPORTED_SERVICES.includes(s))
      
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

  // Statistics
  const stats = useMemo(() => {
    const supported = awsServices.filter(s => s.supported).length
    const total = awsServices.length
    return { supported, total, coming: total - supported }
  }, [awsServices])

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
          disabled={!record.supported}
          onChange={(e) => handleServiceToggle(record.key, e.target.checked)}
        />
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 130,
      render: (category) => {
        const config = CATEGORY_CONFIG[category] || CATEGORY_CONFIG['Other']
        return (
          <Space>
            <span style={{ color: config.color }}>{config.icon}</span>
            <Text style={{ color: config.color }}>{category}</Text>
          </Space>
        )
      },
      filters: ['Compute', 'Storage', 'Database', 'Networking', 'Monitoring', 'Security'].map(c => ({ text: c, value: c })),
      onFilter: (value, record) => record.category === value,
    },
    {
      title: '服务名称',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <a 
          href={record.url} 
          target="_blank" 
          rel="noopener noreferrer"
          style={{ color: record.supported ? '#1890ff' : '#999' }}
        >
          {name}
        </a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (_, record) => (
        record.supported 
          ? <Tag color="green">✅ 已支持</Tag>
          : <Tag color="default">⏳ Coming Soon</Tag>
      ),
      filters: [
        { text: '已支持', value: true },
        { text: 'Coming Soon', value: false },
      ],
      onFilter: (value, record) => record.supported === value,
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
        const data = record.data
        if (record.error) return <Text type="danger">-</Text>
        const count = data?.count || 
                     data?.instances?.length || 
                     data?.functions?.length || 
                     data?.buckets?.length ||
                     data?.clusters?.length ||
                     data?.vpcs?.length ||
                     data?.load_balancers?.length ||
                     data?.hosted_zones?.length ||
                     data?.alarms?.length || 0
        return <Text strong>{count}</Text>
      },
    },
    {
      title: '详情',
      dataIndex: 'details',
      key: 'details',
      render: (_, record) => {
        if (record.error) return <Text type="danger">{record.error}</Text>
        const data = record.data
        
        // EC2
        if (data?.status) {
          return (
            <Space>
              <Tag color="green">Running: {data.status.running || 0}</Tag>
              <Tag color="default">Stopped: {data.status.stopped || 0}</Tag>
            </Space>
          )
        }
        // S3
        if (data?.public_count > 0) {
          return <Tag color="orange">⚠️ {data.public_count} 公开访问</Tag>
        }
        // ELB
        if (data?.status?.active !== undefined) {
          return <Tag color="green">Active: {data.status.active}</Tag>
        }
        // IAM
        if (data?.users_without_mfa?.length > 0) {
          return <Tag color="orange">⚠️ {data.users_without_mfa.length} 用户无 MFA</Tag>
        }
        // CloudWatch
        if (data?.by_state?.ALARM > 0) {
          return <Tag color="red">🚨 {data.by_state.ALARM} 告警</Tag>
        }
        // Route53
        if (data?.health_checks_count > 0) {
          return <Tag color="blue">{data.health_checks_count} Health Checks</Tag>
        }
        return <Tag color="green">✅ 正常</Tag>
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

  // Popular regions
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
          数据来源: <a href="https://api.regional-table.region-services.aws.a2z.com/index.json" target="_blank" rel="noopener noreferrer">
            AWS Regional Services API
          </a>
          {!loadingServices && ` (${stats.total} 服务, ${stats.supported} 已支持)`}
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
                <Text type="secondary"> / {stats.supported} 可用</Text>
              </div>
              <Button block size="small" onClick={handleSelectAllSupported}>全选已支持</Button>
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
                {loadingServices ? (
                  <Spin size="small" />
                ) : (
                  <>
                    <Tag color="green">{stats.supported} 已支持</Tag>
                    <Tag color="default">{stats.coming} Coming Soon</Tag>
                  </>
                )}
              </Space>
            }
            size="small"
          >
            {loadingServices ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Spin size="large" tip="正在从 AWS API 加载服务列表..." />
              </div>
            ) : (
              <Table
                columns={serviceColumns}
                dataSource={awsServices}
                rowKey="key"
                size="small"
                pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 个服务` }}
                scroll={{ y: 400 }}
                rowClassName={(record) => record.supported ? '' : 'disabled-row'}
              />
            )}
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
        <Card title={`📊 扫描结果 (${selectedRegion})`} style={{ marginTop: 16 }}>
          <Table
            columns={resultColumns}
            dataSource={resultData}
            rowKey="key"
            size="small"
            pagination={false}
            expandable={{
              expandedRowRender: (record) => {
                const data = record.data
                if (record.error) return <Text type="danger">{record.error}</Text>
                
                // EC2 instances
                if (record.service === 'ec2' && data.instances) {
                  return (
                    <Table
                      columns={[
                        { title: 'Instance ID', dataIndex: 'id', key: 'id', render: (text) => <Text copyable>{text}</Text> },
                        { title: 'Name', dataIndex: 'name', key: 'name' },
                        { title: 'Type', dataIndex: 'type', key: 'type' },
                        { title: 'State', dataIndex: 'state', key: 'state', render: (state) => (
                          <Tag color={state === 'running' ? 'green' : state === 'stopped' ? 'default' : 'orange'}>{state}</Tag>
                        )},
                        { title: 'Private IP', dataIndex: 'private_ip', key: 'private_ip' },
                      ]}
                      dataSource={data.instances}
                      rowKey="id"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // Lambda functions
                if (record.service === 'lambda' && data.functions) {
                  return (
                    <Table
                      columns={[
                        { title: 'Function Name', dataIndex: 'name', key: 'name' },
                        { title: 'Runtime', dataIndex: 'runtime', key: 'runtime' },
                        { title: 'Memory', dataIndex: 'memory', key: 'memory', render: (m) => `${m} MB` },
                        { title: 'Timeout', dataIndex: 'timeout', key: 'timeout', render: (t) => `${t}s` },
                      ]}
                      dataSource={data.functions}
                      rowKey="name"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // S3 buckets
                if (record.service === 's3' && data.buckets) {
                  return (
                    <Table
                      columns={[
                        { title: 'Bucket Name', dataIndex: 'name', key: 'name' },
                        { title: 'Public', dataIndex: 'public', key: 'public', render: (p) => (
                          p ? <Tag color="orange">⚠️ Public</Tag> : <Tag color="green">Private</Tag>
                        )},
                      ]}
                      dataSource={data.buckets}
                      rowKey="name"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // RDS instances
                if (record.service === 'rds' && data.instances) {
                  return (
                    <Table
                      columns={[
                        { title: 'DB Identifier', dataIndex: 'id', key: 'id' },
                        { title: 'Engine', dataIndex: 'engine', key: 'engine' },
                        { title: 'Class', dataIndex: 'class', key: 'class' },
                        { title: 'Status', dataIndex: 'status', key: 'status', render: (s) => (
                          <Tag color={s === 'available' ? 'green' : 'orange'}>{s}</Tag>
                        )},
                        { title: 'Public', dataIndex: 'public', key: 'public', render: (p) => (
                          p ? <Tag color="orange">⚠️ Yes</Tag> : <Tag>No</Tag>
                        )},
                      ]}
                      dataSource={data.instances}
                      rowKey="id"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // VPC
                if (record.service === 'vpc' && data.vpcs) {
                  return (
                    <Table
                      columns={[
                        { title: 'VPC ID', dataIndex: 'id', key: 'id', render: (text) => <Text copyable>{text}</Text> },
                        { title: 'Name', dataIndex: 'name', key: 'name' },
                        { title: 'CIDR', dataIndex: 'cidr', key: 'cidr' },
                        { title: 'State', dataIndex: 'state', key: 'state' },
                        { title: 'Default', dataIndex: 'is_default', key: 'is_default', render: (d) => d ? '✅' : '' },
                      ]}
                      dataSource={data.vpcs}
                      rowKey="id"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // ELB
                if (record.service === 'elb' && data.load_balancers) {
                  return (
                    <Table
                      columns={[
                        { title: 'Name', dataIndex: 'name', key: 'name' },
                        { title: 'Type', dataIndex: 'type', key: 'type' },
                        { title: 'Scheme', dataIndex: 'scheme', key: 'scheme' },
                        { title: 'State', dataIndex: 'state', key: 'state', render: (s) => (
                          <Tag color={s === 'active' ? 'green' : 'orange'}>{s}</Tag>
                        )},
                        { title: 'DNS', dataIndex: 'dns_name', key: 'dns_name', ellipsis: true },
                      ]}
                      dataSource={data.load_balancers}
                      rowKey="name"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // DynamoDB
                if (record.service === 'dynamodb' && data.tables) {
                  return (
                    <Table
                      columns={[
                        { title: 'Table Name', dataIndex: 'name', key: 'name' },
                        { title: 'Status', dataIndex: 'status', key: 'status', render: (s) => (
                          <Tag color={s === 'ACTIVE' ? 'green' : 'orange'}>{s}</Tag>
                        )},
                        { title: 'Billing', dataIndex: 'billing_mode', key: 'billing_mode' },
                        { title: 'RCU', dataIndex: 'read_capacity', key: 'read_capacity' },
                        { title: 'WCU', dataIndex: 'write_capacity', key: 'write_capacity' },
                        { title: 'Items', dataIndex: 'item_count', key: 'item_count' },
                      ]}
                      dataSource={data.tables}
                      rowKey="name"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // ECS
                if (record.service === 'ecs' && data.clusters) {
                  return (
                    <Table
                      columns={[
                        { title: 'Cluster', dataIndex: 'name', key: 'name' },
                        { title: 'Status', dataIndex: 'status', key: 'status', render: (s) => (
                          <Tag color={s === 'ACTIVE' ? 'green' : 'orange'}>{s}</Tag>
                        )},
                        { title: 'Running Tasks', dataIndex: 'running_tasks', key: 'running_tasks' },
                        { title: 'Pending Tasks', dataIndex: 'pending_tasks', key: 'pending_tasks' },
                        { title: 'Services', dataIndex: 'active_services', key: 'active_services' },
                      ]}
                      dataSource={data.clusters}
                      rowKey="name"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // ElastiCache
                if (record.service === 'elasticache' && data.clusters) {
                  return (
                    <Table
                      columns={[
                        { title: 'Cluster ID', dataIndex: 'id', key: 'id' },
                        { title: 'Engine', dataIndex: 'engine', key: 'engine' },
                        { title: 'Version', dataIndex: 'engine_version', key: 'engine_version' },
                        { title: 'Status', dataIndex: 'status', key: 'status', render: (s) => (
                          <Tag color={s === 'available' ? 'green' : 'orange'}>{s}</Tag>
                        )},
                        { title: 'Node Type', dataIndex: 'node_type', key: 'node_type' },
                        { title: 'Nodes', dataIndex: 'num_nodes', key: 'num_nodes' },
                      ]}
                      dataSource={data.clusters}
                      rowKey="id"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // EKS
                if (record.service === 'eks' && data.clusters) {
                  return (
                    <Table
                      columns={[
                        { title: 'Cluster Name', dataIndex: 'name', key: 'name' },
                        { title: 'Version', dataIndex: 'version', key: 'version' },
                        { title: 'Status', dataIndex: 'status', key: 'status', render: (s) => (
                          <Tag color={s === 'ACTIVE' ? 'green' : 'orange'}>{s}</Tag>
                        )},
                      ]}
                      dataSource={data.clusters}
                      rowKey="name"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // IAM
                if (record.service === 'iam') {
                  return (
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <div><Text strong>Users:</Text> {data.users_count || 0}</div>
                      <div><Text strong>Roles:</Text> {data.roles_count || 0}</div>
                      {data.users_without_mfa?.length > 0 && (
                        <div>
                          <Text type="danger" strong>⚠️ Users without MFA:</Text>
                          {data.users_without_mfa.map((u, i) => <Tag key={i} color="orange">{u}</Tag>)}
                        </div>
                      )}
                    </Space>
                  )
                }
                
                // Route53
                if (record.service === 'route53' && data.hosted_zones) {
                  return (
                    <Table
                      columns={[
                        { title: 'Zone ID', dataIndex: 'id', key: 'id' },
                        { title: 'Name', dataIndex: 'name', key: 'name' },
                        { title: 'Private', dataIndex: 'private', key: 'private', render: (p) => p ? '✅' : '' },
                        { title: 'Records', dataIndex: 'record_count', key: 'record_count' },
                      ]}
                      dataSource={data.hosted_zones}
                      rowKey="id"
                      size="small"
                      pagination={false}
                    />
                  )
                }
                
                // CloudWatch
                if (record.service === 'cloudwatch' && data.alarms) {
                  return (
                    <div>
                      <Space style={{ marginBottom: 8 }}>
                        <Tag color="green">OK: {data.by_state?.OK || 0}</Tag>
                        <Tag color="red">ALARM: {data.by_state?.ALARM || 0}</Tag>
                        <Tag color="default">Insufficient: {data.by_state?.INSUFFICIENT_DATA || 0}</Tag>
                      </Space>
                      <Table
                        columns={[
                          { title: 'Alarm Name', dataIndex: 'name', key: 'name' },
                          { title: 'State', dataIndex: 'state', key: 'state', render: (s) => (
                            <Tag color={s === 'OK' ? 'green' : s === 'ALARM' ? 'red' : 'default'}>{s}</Tag>
                          )},
                          { title: 'Metric', dataIndex: 'metric', key: 'metric' },
                          { title: 'Namespace', dataIndex: 'namespace', key: 'namespace' },
                        ]}
                        dataSource={data.alarms}
                        rowKey="name"
                        size="small"
                        pagination={false}
                      />
                    </div>
                  )
                }
                
                // Default: show JSON
                return <pre style={{ fontSize: 12, maxHeight: 200, overflow: 'auto' }}>{JSON.stringify(data, null, 2)}</pre>
              },
              rowExpandable: (record) => !record.error,
            }}
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
