import { useState, useEffect } from 'react'
import { Row, Col, Select, Space, Spin, Empty, Tag, Card, Typography } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import { ReloadOutlined, CloudOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'

const { Title, Text } = Typography

function Metrics({ apiUrl }) {
  const [loading, setLoading] = useState(true)
  const [namespace, setNamespace] = useState('default')
  const [metricsData, setMetricsData] = useState(null)

  useEffect(() => {
    const fetchMetrics = async () => {
      setLoading(true)
      try {
        const res = await fetch(`${apiUrl}/api/aci/telemetry/${namespace}`)
        const data = await res.json()
        setMetricsData(data)
      } catch (err) {
        console.error('Failed to fetch metrics:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchMetrics()
    const interval = setInterval(fetchMetrics, 60000)
    return () => clearInterval(interval)
  }, [apiUrl, namespace])

  // CPU Gauge Option
  const cpuGaugeOption = {
    series: [
      {
        type: 'gauge',
        startAngle: 200,
        endAngle: -20,
        min: 0,
        max: 100,
        splitNumber: 10,
        itemStyle: { color: '#06AC38' },
        progress: { show: true, roundCap: true, width: 12 },
        pointer: { show: false },
        axisLine: { roundCap: true, lineStyle: { width: 12, color: [[1, '#e8e8e8']] } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        title: { show: true, offsetCenter: [0, '70%'], fontSize: 14, color: '#666' },
        detail: { fontSize: 32, fontWeight: 600, color: '#333', offsetCenter: [0, '0%'], formatter: '{value}%' },
        data: [{ value: metricsData?.metrics?.data?.cpu_usage_percent || 45, name: 'CPU Usage' }],
      },
    ],
  }

  // Memory Gauge Option
  const memoryGaugeOption = {
    series: [
      {
        type: 'gauge',
        startAngle: 200,
        endAngle: -20,
        min: 0,
        max: 100,
        itemStyle: { color: '#0066FF' },
        progress: { show: true, roundCap: true, width: 12 },
        pointer: { show: false },
        axisLine: { roundCap: true, lineStyle: { width: 12, color: [[1, '#e8e8e8']] } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        title: { show: true, offsetCenter: [0, '70%'], fontSize: 14, color: '#666' },
        detail: { fontSize: 32, fontWeight: 600, color: '#333', offsetCenter: [0, '0%'], formatter: '{value}%' },
        data: [{ value: metricsData?.metrics?.data?.memory_usage_percent || 62, name: 'Memory Usage' }],
      },
    ],
  }

  // Network Chart Option
  const networkChartOption = {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: ['5m', '4m', '3m', '2m', '1m', 'now'],
      axisLine: { lineStyle: { color: '#e8e8e8' } },
      axisLabel: { color: '#666' },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: '#666', formatter: '{value} KB/s' },
      splitLine: { lineStyle: { color: '#f0f0f0' } },
    },
    series: [
      {
        name: 'Inbound',
        type: 'line',
        smooth: true,
        data: [120, 132, 101, 134, 190, 150],
        itemStyle: { color: '#06AC38' },
        areaStyle: { color: 'rgba(6, 172, 56, 0.1)' },
      },
      {
        name: 'Outbound',
        type: 'line',
        smooth: true,
        data: [80, 92, 81, 94, 120, 100],
        itemStyle: { color: '#F2A900' },
        areaStyle: { color: 'rgba(242, 169, 0, 0.1)' },
      },
    ],
  }

  // Events list
  const events = metricsData?.events?.data || []

  return (
    <Spin spinning={loading}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* Page Header */}
        <div style={{ marginBottom: 8 }}>
          <Title level={3} style={{ margin: 0 }}>Analytics</Title>
          <Text type="secondary">Real-time metrics and resource usage</Text>
        </div>

        {/* Namespace Selector */}
        <Card bordered={false}>
          <Space>
            <Text>Namespace:</Text>
            <Select
              value={namespace}
              onChange={setNamespace}
              style={{ width: 200 }}
              options={[
                { value: 'default', label: 'default' },
                { value: 'stress-test', label: 'stress-test' },
                { value: 'kube-system', label: 'kube-system' },
                { value: 'monitoring', label: 'monitoring' },
              ]}
            />
            <Tag color="green" icon={<CloudOutlined />}>Live</Tag>
          </Space>
        </Card>

        {/* Metrics Cards */}
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12} lg={6}>
            <Card bordered={false} title="CPU">
              <ReactECharts option={cpuGaugeOption} style={{ height: 180 }} />
            </Card>
          </Col>
          <Col xs={24} md={12} lg={6}>
            <Card bordered={false} title="Memory">
              <ReactECharts option={memoryGaugeOption} style={{ height: 180 }} />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card bordered={false} title="Network Traffic">
              <ReactECharts option={networkChartOption} style={{ height: 180 }} />
            </Card>
          </Col>
        </Row>

        {/* Events */}
        <Card 
          bordered={false}
          title="Recent Events"
          extra={<Tag>{events.length} events</Tag>}
        >
          {events.length > 0 ? (
            <div style={{ maxHeight: 300, overflow: 'auto' }}>
              {events.slice(0, 10).map((event, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '12px 16px',
                    borderBottom: '1px solid #f0f0f0',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <Space>
                    <Tag color={event.type === 'Warning' ? 'orange' : 'blue'}>
                      {event.type || 'Normal'}
                    </Tag>
                    <Text strong>{event.reason}</Text>
                    <Text type="secondary">{event.message?.substring(0, 80)}</Text>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {event.lastTimestamp ? new Date(event.lastTimestamp).toLocaleTimeString() : '-'}
                  </Text>
                </div>
              ))}
            </div>
          ) : (
            <Empty description="No events" />
          )}
        </Card>
      </Space>
    </Spin>
  )
}

export default Metrics
