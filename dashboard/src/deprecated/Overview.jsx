import { useState, useEffect } from 'react'
import { Row, Col, Statistic, Card, Progress, Table, Tag, Space, Spin } from 'antd'
import { ProCard, StatisticCard } from '@ant-design/pro-components'
import {
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  RiseOutlined,
  FallOutlined,
  CloudServerOutlined,
  AlertOutlined,
  ToolOutlined,
  SafetyOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'

const { Divider } = StatisticCard

function Overview({ apiUrl }) {
  const [loading, setLoading] = useState(true)
  const [dashboardData, setDashboardData] = useState(null)
  const [healthData, setHealthData] = useState(null)

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      try {
        // Fetch dashboard data
        const [issuesRes, healthRes] = await Promise.all([
          fetch(`${apiUrl}/api/issues/dashboard`).then(r => r.json()).catch(() => ({})),
          fetch(`${apiUrl}/api/health/status`).then(r => r.json()).catch(() => ({})),
        ])
        setDashboardData(issuesRes)
        setHealthData(healthRes)
      } catch (err) {
        console.error('Failed to fetch overview data:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [apiUrl])

  // Metrics chart options
  const metricsChartOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { 
      data: ['CPU', 'Memory', 'Network'],
      textStyle: { color: '#fff' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00', '24:00'],
      axisLine: { lineStyle: { color: '#444' } },
      axisLabel: { color: '#aaa' },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#444' } },
      axisLabel: { color: '#aaa', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#333' } },
    },
    series: [
      {
        name: 'CPU',
        type: 'line',
        smooth: true,
        data: [32, 45, 67, 54, 48, 62, 45],
        itemStyle: { color: '#1677ff' },
        areaStyle: { color: 'rgba(22, 119, 255, 0.1)' },
      },
      {
        name: 'Memory',
        type: 'line',
        smooth: true,
        data: [45, 52, 58, 62, 68, 72, 65],
        itemStyle: { color: '#52c41a' },
        areaStyle: { color: 'rgba(82, 196, 26, 0.1)' },
      },
      {
        name: 'Network',
        type: 'line',
        smooth: true,
        data: [12, 18, 25, 32, 28, 22, 15],
        itemStyle: { color: '#faad14' },
        areaStyle: { color: 'rgba(250, 173, 20, 0.1)' },
      },
    ],
  }

  // Issue trend chart
  const issueTrendOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
      axisLine: { lineStyle: { color: '#444' } },
      axisLabel: { color: '#aaa' },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#444' } },
      axisLabel: { color: '#aaa' },
      splitLine: { lineStyle: { color: '#333' } },
    },
    series: [
      {
        name: '新增',
        type: 'bar',
        stack: 'total',
        data: [5, 8, 3, 12, 6, 2, 4],
        itemStyle: { color: '#ff4d4f' },
      },
      {
        name: '已修复',
        type: 'bar',
        stack: 'total',
        data: [4, 6, 5, 10, 8, 3, 5],
        itemStyle: { color: '#52c41a' },
      },
    ],
  }

  const statusCounts = dashboardData?.status_counts || {}
  const severityCounts = dashboardData?.severity_counts || {}

  return (
    <Spin spinning={loading}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* Top Stats Row */}
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={6}>
            <ProCard
              style={{ background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)' }}
              bodyStyle={{ padding: 20 }}
            >
              <Statistic
                title={<span style={{ color: '#aaa' }}>系统可用率</span>}
                value={99.95}
                precision={2}
                suffix="%"
                valueStyle={{ color: '#52c41a', fontSize: 32, fontWeight: 600 }}
                prefix={<SafetyOutlined />}
              />
              <div style={{ marginTop: 8 }}>
                <Tag color="success" icon={<RiseOutlined />}>+0.05%</Tag>
                <span style={{ color: '#888', fontSize: 12 }}>vs 昨日</span>
              </div>
            </ProCard>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <ProCard
              style={{ background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)' }}
              bodyStyle={{ padding: 20 }}
            >
              <Statistic
                title={<span style={{ color: '#aaa' }}>待处理问题</span>}
                value={statusCounts.open || 0}
                valueStyle={{ color: '#ff4d4f', fontSize: 32, fontWeight: 600 }}
                prefix={<AlertOutlined />}
              />
              <div style={{ marginTop: 8 }}>
                <Tag color="error">{severityCounts.high || 0} 高危</Tag>
                <Tag color="warning">{severityCounts.medium || 0} 中等</Tag>
              </div>
            </ProCard>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <ProCard
              style={{ background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)' }}
              bodyStyle={{ padding: 20 }}
            >
              <Statistic
                title={<span style={{ color: '#aaa' }}>今日已修复</span>}
                value={statusCounts.resolved || 0}
                valueStyle={{ color: '#52c41a', fontSize: 32, fontWeight: 600 }}
                prefix={<CheckCircleOutlined />}
              />
              <div style={{ marginTop: 8 }}>
                <Tag color="success" icon={<RiseOutlined />}>+23%</Tag>
                <span style={{ color: '#888', fontSize: 12 }}>修复率</span>
              </div>
            </ProCard>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <ProCard
              style={{ background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)' }}
              bodyStyle={{ padding: 20 }}
            >
              <Statistic
                title={<span style={{ color: '#aaa' }}>自动修复</span>}
                value={dashboardData?.auto_fixed_count || 8}
                valueStyle={{ color: '#1677ff', fontSize: 32, fontWeight: 600 }}
                prefix={<ToolOutlined />}
              />
              <div style={{ marginTop: 8 }}>
                <Progress percent={75} size="small" strokeColor="#1677ff" />
                <span style={{ color: '#888', fontSize: 12 }}>自动化率</span>
              </div>
            </ProCard>
          </Col>
        </Row>

        {/* Charts Row */}
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={16}>
            <ProCard
              title="资源使用趋势"
              extra={<Tag color="blue">实时</Tag>}
              style={{ background: '#141414' }}
              headStyle={{ borderBottom: '1px solid #303030' }}
            >
              <ReactECharts option={metricsChartOption} style={{ height: 300 }} />
            </ProCard>
          </Col>
          <Col xs={24} lg={8}>
            <ProCard
              title="问题趋势"
              style={{ background: '#141414' }}
              headStyle={{ borderBottom: '1px solid #303030' }}
            >
              <ReactECharts option={issueTrendOption} style={{ height: 300 }} />
            </ProCard>
          </Col>
        </Row>

        {/* Cluster Status */}
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <ProCard
              title="集群状态"
              extra={<Tag color="success">健康</Tag>}
              style={{ background: '#141414' }}
              headStyle={{ borderBottom: '1px solid #303030' }}
            >
              <Row gutter={[16, 16]}>
                <Col span={8}>
                  <Statistic
                    title="Nodes"
                    value={3}
                    suffix="/ 3"
                    valueStyle={{ color: '#52c41a' }}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="Pods"
                    value={28}
                    suffix="Running"
                    valueStyle={{ color: '#52c41a' }}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="Services"
                    value={12}
                    suffix="Active"
                    valueStyle={{ color: '#52c41a' }}
                  />
                </Col>
              </Row>
            </ProCard>
          </Col>
          <Col xs={24} lg={12}>
            <ProCard
              title="最近告警"
              extra={<a>查看全部</a>}
              style={{ background: '#141414' }}
              headStyle={{ borderBottom: '1px solid #303030' }}
            >
              <Table
                size="small"
                pagination={false}
                dataSource={[
                  { key: 1, severity: 'high', message: 'Pod OOMKilled', time: '5 min ago' },
                  { key: 2, severity: 'medium', message: 'CPU Throttling', time: '12 min ago' },
                  { key: 3, severity: 'low', message: 'Config Changed', time: '1 hour ago' },
                ]}
                columns={[
                  {
                    title: '级别',
                    dataIndex: 'severity',
                    width: 80,
                    render: (v) => (
                      <Tag color={v === 'high' ? 'red' : v === 'medium' ? 'orange' : 'blue'}>
                        {v.toUpperCase()}
                      </Tag>
                    ),
                  },
                  { title: '信息', dataIndex: 'message' },
                  { title: '时间', dataIndex: 'time', width: 100 },
                ]}
              />
            </ProCard>
          </Col>
        </Row>
      </Space>
    </Spin>
  )
}

export default Overview
