import { useState, useEffect } from 'react'
import { Row, Col, Card, Statistic, Table, Tag, Space, Progress, Typography, Timeline, Avatar } from 'antd'
import {
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  RiseOutlined,
  FallOutlined,
  ThunderboltOutlined,
  SafetyOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'

const { Title, Text } = Typography

function Overview({ apiUrl }) {
  const [loading, setLoading] = useState(true)
  const [dashboardData, setDashboardData] = useState({})

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      try {
        const res = await fetch(`${apiUrl}/api/issues/dashboard`)
        const data = await res.json()
        setDashboardData(data)
      } catch (err) {
        console.error('Failed to fetch data:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [apiUrl])

  const statusCounts = dashboardData.status_counts || {}
  const severityCounts = dashboardData.severity_counts || {}

  // Incident trend chart - PagerDuty style
  const trendChartOption = {
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
      axisLine: { lineStyle: { color: '#e8e8e8' } },
      axisLabel: { color: '#666' },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: '#666' },
      splitLine: { lineStyle: { color: '#f0f0f0' } },
    },
    series: [
      {
        name: 'Triggered',
        type: 'bar',
        data: [5, 8, 3, 12, 6, 2, 4],
        itemStyle: { color: '#CC2936' },
        barWidth: 16,
      },
      {
        name: 'Resolved',
        type: 'bar',
        data: [4, 6, 5, 10, 8, 3, 5],
        itemStyle: { color: '#06AC38' },
        barWidth: 16,
      },
    ],
  }

  // Service health - PagerDuty style
  const services = [
    { name: 'API Gateway', status: 'healthy', incidents: 0 },
    { name: 'Database Cluster', status: 'warning', incidents: 2 },
    { name: 'Cache Layer', status: 'healthy', incidents: 0 },
    { name: 'Message Queue', status: 'healthy', incidents: 0 },
    { name: 'Auth Service', status: 'critical', incidents: 1 },
  ]

  const recentIncidents = [
    { id: 'INC-001', title: 'High CPU on prod-api-01', severity: 'high', time: '5 min ago', status: 'triggered' },
    { id: 'INC-002', title: 'OOMKilled in stress-test ns', severity: 'medium', time: '12 min ago', status: 'acknowledged' },
    { id: 'INC-003', title: 'Network latency spike', severity: 'low', time: '1 hour ago', status: 'resolved' },
  ]

  return (
    <div>
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>Operations Overview</Title>
        <Text type="secondary">Real-time status of your infrastructure</Text>
      </div>

      {/* Status Cards - PagerDuty style */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #06AC38' }}>
            <Statistic
              title="All Systems"
              value="Operational"
              valueStyle={{ color: '#06AC38', fontSize: 20 }}
              prefix={<CheckCircleOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>99.9% uptime this month</Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #CC2936' }}>
            <Statistic
              title="Open Incidents"
              value={statusCounts.open || 0}
              valueStyle={{ color: '#CC2936', fontSize: 28 }}
              prefix={<CloseCircleOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              <Tag color="red">{severityCounts.high || 0} Critical</Tag>
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #F2A900' }}>
            <Statistic
              title="Acknowledged"
              value={statusCounts.in_progress || 0}
              valueStyle={{ color: '#F2A900', fontSize: 28 }}
              prefix={<WarningOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>Being investigated</Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #0066FF' }}>
            <Statistic
              title="Auto-Resolved"
              value={8}
              valueStyle={{ color: '#0066FF', fontSize: 28 }}
              prefix={<ThunderboltOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              <Tag color="blue" icon={<RiseOutlined />}>+23% efficiency</Tag>
            </Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {/* Service Health */}
        <Col xs={24} lg={12}>
          <Card title="Service Health" bordered={false}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {services.map((service, idx) => (
                <div 
                  key={idx}
                  style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    alignItems: 'center',
                    padding: '8px 12px',
                    background: '#fafafa',
                    borderRadius: 4,
                  }}
                >
                  <Space>
                    <div style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: service.status === 'healthy' ? '#06AC38' 
                        : service.status === 'warning' ? '#F2A900' : '#CC2936',
                    }} />
                    <Text strong>{service.name}</Text>
                  </Space>
                  <Space>
                    {service.incidents > 0 && (
                      <Tag color={service.status === 'warning' ? 'orange' : 'red'}>
                        {service.incidents} incident{service.incidents > 1 ? 's' : ''}
                      </Tag>
                    )}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {service.status === 'healthy' ? 'Operational' : 
                       service.status === 'warning' ? 'Degraded' : 'Outage'}
                    </Text>
                  </Space>
                </div>
              ))}
            </div>
          </Card>
        </Col>

        {/* Incident Trend */}
        <Col xs={24} lg={12}>
          <Card title="Incident Trend (7 Days)" bordered={false}>
            <ReactECharts option={trendChartOption} style={{ height: 240 }} />
          </Card>
        </Col>
      </Row>

      {/* Recent Incidents */}
      <Card 
        title="Recent Incidents" 
        bordered={false} 
        style={{ marginTop: 16 }}
        extra={<a href="#" onClick={() => {}}>View All →</a>}
      >
        <Table
          dataSource={recentIncidents}
          rowKey="id"
          pagination={false}
          columns={[
            {
              title: 'Status',
              dataIndex: 'status',
              width: 120,
              render: (status) => {
                const config = {
                  triggered: { color: '#CC2936', text: 'Triggered' },
                  acknowledged: { color: '#F2A900', text: 'Acknowledged' },
                  resolved: { color: '#06AC38', text: 'Resolved' },
                }
                const c = config[status] || config.triggered
                return (
                  <Tag color={c.color} style={{ borderRadius: 12 }}>
                    {c.text}
                  </Tag>
                )
              },
            },
            {
              title: 'Severity',
              dataIndex: 'severity',
              width: 100,
              render: (sev) => {
                const colors = { high: 'red', medium: 'orange', low: 'blue' }
                return <Tag color={colors[sev]}>{sev.toUpperCase()}</Tag>
              },
            },
            {
              title: 'Incident',
              dataIndex: 'title',
              render: (title, record) => (
                <div>
                  <Text strong style={{ color: '#1890ff' }}>{record.id}</Text>
                  <br />
                  <Text>{title}</Text>
                </div>
              ),
            },
            {
              title: 'Time',
              dataIndex: 'time',
              width: 120,
              render: (time) => <Text type="secondary">{time}</Text>,
            },
          ]}
        />
      </Card>
    </div>
  )
}

export default Overview
