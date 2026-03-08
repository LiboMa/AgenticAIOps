/**
 * OpsHub — Operations Hub (主视图)
 * "一眼看清系统健康状态"
 * 
 * Sections: HealthIssue List | Alert Feed | Incident Stats
 */

import { useState } from 'react'
import {
  Card, Table, Tag, Badge, Statistic, Row, Col, Timeline, Empty,
  Spin, Typography, Space, Tooltip, Segmented, Descriptions, Alert,
} from 'antd'
import {
  AlertOutlined, BugOutlined, CheckCircleOutlined, ClockCircleOutlined,
  FireOutlined, WarningOutlined, SearchOutlined,
} from '@ant-design/icons'
import { useHealthIssues, useAlertFeed, useIncidentStats, useAlertStats } from '../hooks/useApi'

const { Title, Text } = Typography

// Severity colors
const SEVERITY_COLOR = {
  critical: 'red',
  high: 'orange',
  medium: 'gold',
  low: 'green',
  info: 'blue',
}

// Status colors
const STATUS_COLOR = {
  open: 'red',
  investigating: 'orange',
  root_cause_identified: 'gold',
  fix_planned: 'blue',
  fix_approved: 'cyan',
  fix_executed: 'geekblue',
  resolved: 'green',
}

// Provider icons
const PROVIDER_COLOR = {
  cloudwatch: '#FF9900',
  datadog: '#632CA6',
  grafana: '#F46800',
  pagerduty: '#06AC38',
  generic: '#666',
}

function IncidentStatsCards() {
  const { data, isLoading, error } = useIncidentStats()

  if (error) return <Alert message="Stats unavailable" type="warning" showIcon />

  const stats = data || {}
  return (
    <Row gutter={[16, 16]}>
      <Col xs={12} sm={6}>
        <Card size="small" bordered={false} style={{ background: '#1a1a2e' }}>
          <Statistic
            title={<Text style={{ color: '#999' }}>Open</Text>}
            value={stats.open ?? 0}
            valueStyle={{ color: '#ff4d4f' }}
            prefix={<FireOutlined />}
            loading={isLoading}
          />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small" bordered={false} style={{ background: '#1a1a2e' }}>
          <Statistic
            title={<Text style={{ color: '#999' }}>Investigating</Text>}
            value={stats.investigating ?? 0}
            valueStyle={{ color: '#faad14' }}
            prefix={<SearchOutlined />}
            loading={isLoading}
          />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small" bordered={false} style={{ background: '#1a1a2e' }}>
          <Statistic
            title={<Text style={{ color: '#999' }}>Resolved</Text>}
            value={stats.resolved ?? 0}
            valueStyle={{ color: '#52c41a' }}
            prefix={<CheckCircleOutlined />}
            loading={isLoading}
          />
        </Card>
      </Col>
      <Col xs={12} sm={6}>
        <Card size="small" bordered={false} style={{ background: '#1a1a2e' }}>
          <Statistic
            title={<Text style={{ color: '#999' }}>Avg MTTR</Text>}
            value={stats.avg_mttr_minutes ?? '-'}
            suffix="min"
            valueStyle={{ color: '#1890ff' }}
            prefix={<ClockCircleOutlined />}
            loading={isLoading}
          />
        </Card>
      </Col>
    </Row>
  )
}

function HealthIssueList() {
  const { data, isLoading, error } = useHealthIssues()

  if (error) return <Alert message="Failed to load health issues" type="error" showIcon />

  const issues = Array.isArray(data) ? data : data?.issues || []

  const columns = [
    {
      title: 'Severity',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (s) => <Tag color={SEVERITY_COLOR[s] || 'default'}>{(s || 'unknown').toUpperCase()}</Tag>,
      sorter: (a, b) => {
        const order = { critical: 0, high: 1, medium: 2, low: 3, info: 4 }
        return (order[a.severity] ?? 5) - (order[b.severity] ?? 5)
      },
    },
    {
      title: 'Title',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 160,
      render: (s) => <Tag color={STATUS_COLOR[s] || 'default'}>{(s || '').replace(/_/g, ' ')}</Tag>,
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (t) => t ? new Date(t).toLocaleString() : '-',
      sorter: (a, b) => new Date(a.created_at) - new Date(b.created_at),
      defaultSortOrder: 'descend',
    },
  ]

  return (
    <Card
      title={<><BugOutlined /> Health Issues</>}
      size="small"
      bordered={false}
      style={{ background: '#1a1a2e' }}
    >
      {issues.length === 0 && !isLoading ? (
        <Empty description="No health issues" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table
          dataSource={issues}
          columns={columns}
          rowKey={(r) => r.id || r.issue_id || Math.random()}
          size="small"
          loading={isLoading}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          style={{ background: 'transparent' }}
        />
      )}
    </Card>
  )
}

function AlertFeed() {
  const { data, isLoading, error } = useAlertFeed(20)
  const { data: stats } = useAlertStats()

  if (error) return <Alert message="Alert feed unavailable" type="warning" showIcon />

  const alerts = data?.alerts || []

  return (
    <Card
      title={
        <Space>
          <AlertOutlined />
          <span>Alert Feed</span>
          {stats?.total > 0 && <Badge count={stats.total} style={{ backgroundColor: '#ff4d4f' }} />}
        </Space>
      }
      size="small"
      bordered={false}
      style={{ background: '#1a1a2e' }}
      extra={
        stats?.by_provider && (
          <Space size={4}>
            {Object.entries(stats.by_provider).map(([k, v]) => (
              <Tag key={k} color={PROVIDER_COLOR[k] || '#666'} style={{ margin: 0 }}>
                {k}: {v}
              </Tag>
            ))}
          </Space>
        )
      }
    >
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
      ) : alerts.length === 0 ? (
        <Empty description="No alerts" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Timeline
          items={alerts.slice(0, 15).map((a, i) => ({
            color: SEVERITY_COLOR[a.severity] || 'gray',
            children: (
              <div key={i}>
                <Space size={8}>
                  <Tag color={PROVIDER_COLOR[a.provider] || '#666'} style={{ fontSize: 11 }}>
                    {a.provider}
                  </Tag>
                  <Tag color={SEVERITY_COLOR[a.severity] || 'default'} style={{ fontSize: 11 }}>
                    {a.severity}
                  </Tag>
                </Space>
                <div style={{ marginTop: 4 }}>
                  <Text style={{ color: '#ddd', fontSize: 13 }}>{a.title || a.description}</Text>
                </div>
                {a.timestamp && (
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {new Date(a.timestamp).toLocaleString()}
                  </Text>
                )}
              </div>
            ),
          }))}
        />
      )}
    </Card>
  )
}

export default function OpsHub() {
  return (
    <div style={{ padding: '16px 24px' }}>
      <Title level={4} style={{ margin: '0 0 16px', color: '#eee' }}>
        🏠 Operations Hub
      </Title>

      {/* Stats row */}
      <IncidentStatsCards />

      {/* Main content */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <HealthIssueList />
        </Col>
        <Col xs={24} lg={10}>
          <AlertFeed />
        </Col>
      </Row>
    </div>
  )
}
