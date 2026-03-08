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
  const [issues, setIssues] = useState([])

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      try {
        const [dashRes, issuesRes] = await Promise.all([
          fetch(`${apiUrl}/api/issues/dashboard`).then(r => r.json()),
          fetch(`${apiUrl}/api/issues?limit=10`).then(r => r.json()),
        ])
        setDashboardData(dashRes)
        setIssues(issuesRes.issues || [])
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

  const stats = dashboardData.stats || {}
  const statusCounts = stats.by_status || {}
  const activeIssues = dashboardData.active_issues || []
  const resolvedToday = dashboardData.resolved_today || []

  // Calculate system status
  const openCount = statusCounts.detected || 0
  const fixedCount = statusCounts.fixed || 0
  const systemStatus = openCount === 0 ? 'Operational' : openCount > 2 ? 'Degraded' : 'Minor Issues'
  const systemColor = openCount === 0 ? '#06AC38' : openCount > 2 ? '#CC2936' : '#F2A900'

  // Incident trend chart - use real data if available
  const trendChartOption = {
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Today'],
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
        data: [0, 0, 0, 0, 0, 0, stats.detected_24h || 0],
        itemStyle: { color: '#CC2936' },
        barWidth: 16,
      },
      {
        name: 'Resolved',
        type: 'bar',
        data: [0, 0, 0, 0, 0, 0, stats.resolved_24h || 0],
        itemStyle: { color: '#06AC38' },
        barWidth: 16,
      },
    ],
  }

  // Map issues to recent incidents format
  const recentIncidents = issues.slice(0, 5).map(issue => ({
    id: issue.id,
    title: issue.title,
    severity: issue.severity,
    time: issue.created_at ? new Date(issue.created_at).toLocaleString() : '-',
    status: issue.status === 'detected' ? 'triggered' : 
            issue.status === 'in_progress' ? 'acknowledged' : 'resolved',
  }))

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
          <Card bordered={false} style={{ borderLeft: `4px solid ${systemColor}` }}>
            <Statistic
              title="System Status"
              value={systemStatus}
              valueStyle={{ color: systemColor, fontSize: 20 }}
              prefix={openCount === 0 ? <CheckCircleOutlined /> : <WarningOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {openCount === 0 ? 'All systems operational' : `${openCount} active issues`}
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #CC2936' }}>
            <Statistic
              title="Open Incidents"
              value={openCount}
              valueStyle={{ color: '#CC2936', fontSize: 28 }}
              prefix={<CloseCircleOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              Require attention
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #F2A900' }}>
            <Statistic
              title="In Progress"
              value={statusCounts.in_progress || 0}
              valueStyle={{ color: '#F2A900', fontSize: 28 }}
              prefix={<WarningOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>Being investigated</Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #06AC38' }}>
            <Statistic
              title="Auto-Resolved"
              value={fixedCount}
              valueStyle={{ color: '#06AC38', fontSize: 28 }}
              prefix={<ThunderboltOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              <Tag color="green">Today: {stats.resolved_24h || 0}</Tag>
            </Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {/* Active Issues */}
        <Col xs={24} lg={12}>
          <Card title="Active Issues" bordered={false} extra={<Tag color="red">{activeIssues.length}</Tag>}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {activeIssues.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 24, color: '#999' }}>
                  <CheckCircleOutlined style={{ fontSize: 32, marginBottom: 8 }} />
                  <div>No active issues</div>
                </div>
              ) : (
                activeIssues.slice(0, 5).map((issue, idx) => (
                  <div 
                    key={issue.id}
                    style={{ 
                      display: 'flex', 
                      justifyContent: 'space-between', 
                      alignItems: 'center',
                      padding: '8px 12px',
                      background: '#fafafa',
                      borderRadius: 4,
                      borderLeft: '3px solid #CC2936',
                    }}
                  >
                    <Space>
                      <Tag color="red">{issue.type || 'unknown'}</Tag>
                      <Text strong>{issue.title}</Text>
                    </Space>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {issue.namespace}
                    </Text>
                  </div>
                ))
              )}
            </div>
          </Card>
        </Col>

        {/* Incident Trend */}
        <Col xs={24} lg={12}>
          <Card title="Today's Activity" bordered={false}>
            <ReactECharts option={trendChartOption} style={{ height: 240 }} />
          </Card>
        </Col>
      </Row>

      {/* Recent Incidents */}
      <Card 
        title="Recent Incidents" 
        bordered={false} 
        style={{ marginTop: 16 }}
        extra={<Tag>{stats.total || 0} total</Tag>}
      >
        <Table
          dataSource={recentIncidents}
          rowKey="id"
          pagination={false}
          loading={loading}
          locale={{ emptyText: 'No incidents' }}
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
                const colors = { high: 'red', medium: 'orange', low: 'blue', critical: 'magenta' }
                return <Tag color={colors[sev] || 'default'}>{(sev || 'unknown').toUpperCase()}</Tag>
              },
            },
            {
              title: 'Incident',
              dataIndex: 'title',
              render: (title, record) => (
                <div>
                  <Text strong style={{ color: '#1890ff' }}>{record.id?.substring(0, 8)}</Text>
                  <br />
                  <Text>{title}</Text>
                </div>
              ),
            },
            {
              title: 'Time',
              dataIndex: 'time',
              width: 180,
              render: (time) => <Text type="secondary">{time}</Text>,
            },
          ]}
        />
      </Card>
    </div>
  )
}

export default Overview
