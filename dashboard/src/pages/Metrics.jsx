import { useState, useEffect } from 'react'
import { Row, Col, Select, Space, Spin, Empty, Tag } from 'antd'
import { ProCard, StatisticCard } from '@ant-design/pro-components'
import { ReloadOutlined, CloudOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'

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
    backgroundColor: 'transparent',
    series: [
      {
        type: 'gauge',
        startAngle: 200,
        endAngle: -20,
        min: 0,
        max: 100,
        splitNumber: 10,
        itemStyle: {
          color: '#1677ff',
        },
        progress: {
          show: true,
          roundCap: true,
          width: 12,
        },
        pointer: { show: false },
        axisLine: {
          roundCap: true,
          lineStyle: { width: 12, color: [[1, '#303030']] },
        },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        title: {
          show: true,
          offsetCenter: [0, '70%'],
          fontSize: 14,
          color: '#aaa',
        },
        detail: {
          fontSize: 32,
          fontWeight: 600,
          color: '#fff',
          offsetCenter: [0, '0%'],
          formatter: '{value}%',
        },
        data: [{ value: metricsData?.metrics?.data?.cpu_usage_percent || 45, name: 'CPU Usage' }],
      },
    ],
  }

  // Memory Gauge Option
  const memoryGaugeOption = {
    backgroundColor: 'transparent',
    series: [
      {
        type: 'gauge',
        startAngle: 200,
        endAngle: -20,
        min: 0,
        max: 100,
        itemStyle: { color: '#52c41a' },
        progress: { show: true, roundCap: true, width: 12 },
        pointer: { show: false },
        axisLine: { roundCap: true, lineStyle: { width: 12, color: [[1, '#303030']] } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        title: { show: true, offsetCenter: [0, '70%'], fontSize: 14, color: '#aaa' },
        detail: { fontSize: 32, fontWeight: 600, color: '#fff', offsetCenter: [0, '0%'], formatter: '{value}%' },
        data: [{ value: metricsData?.metrics?.data?.memory_usage_percent || 62, name: 'Memory Usage' }],
      },
    ],
  }

  // Network Chart Option
  const networkChartOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: ['5m', '4m', '3m', '2m', '1m', 'now'],
      axisLine: { lineStyle: { color: '#444' } },
      axisLabel: { color: '#aaa' },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#444' } },
      axisLabel: { color: '#aaa', formatter: '{value} KB/s' },
      splitLine: { lineStyle: { color: '#333' } },
    },
    series: [
      {
        name: 'Inbound',
        type: 'line',
        smooth: true,
        data: [120, 132, 101, 134, 190, 150],
        itemStyle: { color: '#1677ff' },
        areaStyle: { color: 'rgba(22, 119, 255, 0.1)' },
      },
      {
        name: 'Outbound',
        type: 'line',
        smooth: true,
        data: [80, 92, 81, 94, 120, 100],
        itemStyle: { color: '#faad14' },
        areaStyle: { color: 'rgba(250, 173, 20, 0.1)' },
      },
    ],
  }

  // Events list
  const events = metricsData?.events?.data || []

  return (
    <Spin spinning={loading}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* Namespace Selector */}
        <ProCard
          title="监控指标"
          extra={
            <Space>
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
              <Tag color="blue" icon={<CloudOutlined />}>实时</Tag>
            </Space>
          }
          style={{ background: '#141414' }}
          headStyle={{ borderBottom: '1px solid #303030' }}
        >
          <Row gutter={[16, 16]}>
            <Col xs={24} md={12} lg={6}>
              <ProCard style={{ background: '#1a1a2e' }}>
                <ReactECharts option={cpuGaugeOption} style={{ height: 200 }} />
              </ProCard>
            </Col>
            <Col xs={24} md={12} lg={6}>
              <ProCard style={{ background: '#1a1a2e' }}>
                <ReactECharts option={memoryGaugeOption} style={{ height: 200 }} />
              </ProCard>
            </Col>
            <Col xs={24} lg={12}>
              <ProCard title="网络流量" style={{ background: '#1a1a2e' }}>
                <ReactECharts option={networkChartOption} style={{ height: 170 }} />
              </ProCard>
            </Col>
          </Row>
        </ProCard>

        {/* Events */}
        <ProCard
          title="最近事件"
          extra={<Tag>{events.length} 个事件</Tag>}
          style={{ background: '#141414' }}
          headStyle={{ borderBottom: '1px solid #303030' }}
        >
          {events.length > 0 ? (
            <div style={{ maxHeight: 300, overflow: 'auto' }}>
              {events.slice(0, 10).map((event, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '12px 16px',
                    borderBottom: '1px solid #303030',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <Space>
                    <Tag color={event.type === 'Warning' ? 'orange' : 'blue'}>
                      {event.type || 'Normal'}
                    </Tag>
                    <span style={{ color: '#fff' }}>{event.reason}</span>
                    <span style={{ color: '#888' }}>{event.message?.substring(0, 80)}</span>
                  </Space>
                  <span style={{ color: '#666', fontSize: 12 }}>
                    {event.lastTimestamp ? new Date(event.lastTimestamp).toLocaleTimeString() : '-'}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <Empty description="暂无事件" />
          )}
        </ProCard>
      </Space>
    </Spin>
  )
}

export default Metrics
