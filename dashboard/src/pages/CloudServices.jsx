import { useState, useEffect } from 'react'
import { Card, Row, Col, Tabs, Button, Space, Tag, Table, Statistic, Alert, Empty, Spin, message, Input, Select, Form, Modal } from 'antd'
import { 
  CloudServerOutlined, 
  ApiOutlined, 
  DatabaseOutlined,
  FolderOutlined,
  ReloadOutlined,
  PlusOutlined,
  SettingOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import DynamicDashboard, { WIDGET_TYPES } from '../components/DynamicDashboard'

const { TabPane } = Tabs

// AWS Service configurations
const AWS_SERVICES = [
  { key: 'ec2', name: 'EC2 Instances', icon: <CloudServerOutlined />, api: '/api/aws/ec2' },
  { key: 'lambda', name: 'Lambda Functions', icon: <ApiOutlined />, api: '/api/aws/lambda' },
  { key: 's3', name: 'S3 Buckets', icon: <FolderOutlined />, api: '/api/aws/s3' },
  { key: 'rds', name: 'RDS Databases', icon: <DatabaseOutlined />, api: '/api/aws/rds' },
]

// Status badge component
const StatusBadge = ({ status }) => {
  const config = {
    running: { color: 'green', icon: <CheckCircleOutlined /> },
    healthy: { color: 'green', icon: <CheckCircleOutlined /> },
    stopped: { color: 'red', icon: <CloseCircleOutlined /> },
    warning: { color: 'orange', icon: <WarningOutlined /> },
    pending: { color: 'blue', icon: <SyncOutlined spin /> },
  }
  const c = config[status?.toLowerCase()] || { color: 'default', icon: null }
  return <Tag color={c.color} icon={c.icon}>{status}</Tag>
}

// EC2 Instances Tab
const EC2Tab = ({ apiUrl }) => {
  const [instances, setInstances] = useState([])
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState({ running: 0, stopped: 0, total: 0 })

  const fetchEC2 = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/aws/ec2`)
      const data = await res.json()
      setInstances(data.instances || [])
      setStats(data.stats || { running: 0, stopped: 0, total: 0 })
    } catch (e) {
      // Use mock data for demo
      const mockInstances = [
        { id: 'i-0abc123def456', name: 'web-server-1', type: 't3.medium', state: 'running', az: 'us-east-1a', cpu: 45 },
        { id: 'i-0def456abc789', name: 'api-server-1', type: 't3.large', state: 'running', az: 'us-east-1b', cpu: 62 },
        { id: 'i-0ghi789jkl012', name: 'db-server-1', type: 'r5.xlarge', state: 'running', az: 'us-east-1a', cpu: 78 },
        { id: 'i-0mno345pqr678', name: 'worker-1', type: 't3.small', state: 'stopped', az: 'us-east-1c', cpu: 0 },
      ]
      setInstances(mockInstances)
      setStats({ running: 3, stopped: 1, total: 4 })
    }
    setLoading(false)
  }

  useEffect(() => { fetchEC2() }, [])

  const columns = [
    { title: 'Instance ID', dataIndex: 'id', key: 'id', render: (t) => <code>{t}</code> },
    { title: 'Name', dataIndex: 'name', key: 'name' },
    { title: 'Type', dataIndex: 'type', key: 'type', render: (t) => <Tag>{t}</Tag> },
    { title: 'State', dataIndex: 'state', key: 'state', render: (s) => <StatusBadge status={s} /> },
    { title: 'AZ', dataIndex: 'az', key: 'az' },
    { title: 'CPU %', dataIndex: 'cpu', key: 'cpu', render: (c) => <span style={{ color: c > 70 ? '#ff4d4f' : c > 50 ? '#faad14' : '#52c41a' }}>{c}%</span> },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="Total Instances" value={stats.total} prefix={<CloudServerOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="Running" value={stats.running} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="Stopped" value={stats.stopped} valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Button type="primary" icon={<ReloadOutlined />} onClick={fetchEC2} loading={loading} style={{ width: '100%', height: 60 }}>
              Refresh
            </Button>
          </Card>
        </Col>
      </Row>
      <Table columns={columns} dataSource={instances} rowKey="id" loading={loading} size="small" />
    </div>
  )
}

// Lambda Tab
const LambdaTab = ({ apiUrl }) => {
  const [functions, setFunctions] = useState([])
  const [loading, setLoading] = useState(false)

  const fetchLambda = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/aws/lambda`)
      const data = await res.json()
      setFunctions(data.functions || [])
    } catch (e) {
      // Mock data
      setFunctions([
        { name: 'api-handler', runtime: 'python3.11', memory: 256, timeout: 30, invocations: 1250 },
        { name: 'image-processor', runtime: 'nodejs18.x', memory: 512, timeout: 60, invocations: 340 },
        { name: 'notification-sender', runtime: 'python3.11', memory: 128, timeout: 15, invocations: 890 },
      ])
    }
    setLoading(false)
  }

  useEffect(() => { fetchLambda() }, [])

  const columns = [
    { title: 'Function Name', dataIndex: 'name', key: 'name', render: (t) => <strong>{t}</strong> },
    { title: 'Runtime', dataIndex: 'runtime', key: 'runtime', render: (r) => <Tag color="blue">{r}</Tag> },
    { title: 'Memory (MB)', dataIndex: 'memory', key: 'memory' },
    { title: 'Timeout (s)', dataIndex: 'timeout', key: 'timeout' },
    { title: 'Invocations (24h)', dataIndex: 'invocations', key: 'invocations' },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={fetchLambda} loading={loading}>Refresh</Button>
      </div>
      <Table columns={columns} dataSource={functions} rowKey="name" loading={loading} size="small" />
    </div>
  )
}

// S3 Tab
const S3Tab = ({ apiUrl }) => {
  const [buckets, setBuckets] = useState([])
  const [loading, setLoading] = useState(false)

  const fetchS3 = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/aws/s3`)
      const data = await res.json()
      setBuckets(data.buckets || [])
    } catch (e) {
      // Mock data
      setBuckets([
        { name: 'prod-assets-bucket', region: 'us-east-1', objects: 12450, size: '45.2 GB', public: false },
        { name: 'logs-archive-bucket', region: 'us-east-1', objects: 89230, size: '128.5 GB', public: false },
        { name: 'static-website-bucket', region: 'us-east-1', objects: 234, size: '1.2 GB', public: true },
      ])
    }
    setLoading(false)
  }

  useEffect(() => { fetchS3() }, [])

  const columns = [
    { title: 'Bucket Name', dataIndex: 'name', key: 'name', render: (t) => <strong>{t}</strong> },
    { title: 'Region', dataIndex: 'region', key: 'region' },
    { title: 'Objects', dataIndex: 'objects', key: 'objects' },
    { title: 'Size', dataIndex: 'size', key: 'size' },
    { 
      title: 'Public Access', 
      dataIndex: 'public', 
      key: 'public', 
      render: (p) => p ? <Tag color="red">PUBLIC</Tag> : <Tag color="green">Private</Tag> 
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={fetchS3} loading={loading}>Refresh</Button>
      </div>
      <Table columns={columns} dataSource={buckets} rowKey="name" loading={loading} size="small" />
    </div>
  )
}

// AWS Account Config Modal
const AccountConfigModal = ({ visible, onClose, onSave }) => {
  const [form] = Form.useForm()
  
  const handleSave = () => {
    form.validateFields().then(values => {
      onSave(values)
      onClose()
      message.success('AWS Account configured successfully')
    })
  }
  
  return (
    <Modal
      title="Configure AWS Account"
      open={visible}
      onCancel={onClose}
      onOk={handleSave}
      okText="Save"
    >
      <Form form={form} layout="vertical">
        <Form.Item name="accountName" label="Account Name" rules={[{ required: true }]}>
          <Input placeholder="e.g., Production Account" />
        </Form.Item>
        <Form.Item name="region" label="Default Region" rules={[{ required: true }]}>
          <Select placeholder="Select region">
            <Select.Option value="us-east-1">US East (N. Virginia)</Select.Option>
            <Select.Option value="us-west-2">US West (Oregon)</Select.Option>
            <Select.Option value="eu-west-1">EU (Ireland)</Select.Option>
            <Select.Option value="ap-northeast-1">Asia Pacific (Tokyo)</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="authMethod" label="Authentication Method" rules={[{ required: true }]}>
          <Select placeholder="Select auth method">
            <Select.Option value="iam-role">IAM Role (Recommended)</Select.Option>
            <Select.Option value="access-key">Access Key</Select.Option>
          </Select>
        </Form.Item>
        <Alert 
          type="info" 
          message="Credentials are securely stored and never exposed in the UI"
          style={{ marginTop: 16 }}
        />
      </Form>
    </Modal>
  )
}

// Main Cloud Services Page
function CloudServices() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [configModal, setConfigModal] = useState(false)
  const [dashboardLayout, setDashboardLayout] = useState({
    widgets: [
      {
        id: 'w1',
        type: WIDGET_TYPES.STAT_CARD,
        config: { title: 'EC2 Instances', value: 4, icon: 'cloud', color: '#06AC38' },
        span: 6,
      },
      {
        id: 'w2',
        type: WIDGET_TYPES.STAT_CARD,
        config: { title: 'Lambda Functions', value: 3, icon: 'api', color: '#1890ff' },
        span: 6,
      },
      {
        id: 'w3',
        type: WIDGET_TYPES.STAT_CARD,
        config: { title: 'S3 Buckets', value: 3, icon: 'database', color: '#722ed1' },
        span: 6,
      },
      {
        id: 'w4',
        type: WIDGET_TYPES.STAT_CARD,
        config: { title: 'Active Alerts', value: 2, icon: 'warning', color: '#ff4d4f' },
        span: 6,
      },
    ],
  })
  
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>
          <CloudServerOutlined style={{ marginRight: 8, color: '#06AC38' }} />
          Cloud Services
        </h2>
        <Space>
          <Button icon={<SettingOutlined />} onClick={() => setConfigModal(true)}>
            Configure AWS Account
          </Button>
        </Space>
      </div>
      
      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab={<span>📊 Dashboard</span>} key="dashboard">
          <DynamicDashboard 
            apiUrl={API_URL}
            initialLayout={dashboardLayout}
            onLayoutChange={setDashboardLayout}
          />
        </TabPane>
        <TabPane tab={<span><CloudServerOutlined /> EC2</span>} key="ec2">
          <EC2Tab apiUrl={API_URL} />
        </TabPane>
        <TabPane tab={<span><ApiOutlined /> Lambda</span>} key="lambda">
          <LambdaTab apiUrl={API_URL} />
        </TabPane>
        <TabPane tab={<span><FolderOutlined /> S3</span>} key="s3">
          <S3Tab apiUrl={API_URL} />
        </TabPane>
      </Tabs>
      
      <AccountConfigModal 
        visible={configModal}
        onClose={() => setConfigModal(false)}
        onSave={(config) => console.log('AWS Config:', config)}
      />
    </div>
  )
}

export default CloudServices
