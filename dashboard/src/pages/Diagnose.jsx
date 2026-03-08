/**
 * Diagnose — Investigation Center
 * "深入分析一个问题"
 * 
 * Phase 1: RCA Reports list
 * Phase 2: Topology Graph + Propagation Overlay
 */

import { Card, Table, Tag, Empty, Alert, Typography, Space } from 'antd'
import { SearchOutlined, FileTextOutlined } from '@ant-design/icons'
import { useRCAReports } from '../hooks/useApi'

const { Title, Text, Paragraph } = Typography

const SEVERITY_COLOR = {
  critical: 'red',
  high: 'orange',
  medium: 'gold',
  low: 'green',
}

function RCAReportList() {
  const { data, isLoading, error } = useRCAReports()

  if (error) return <Alert message="Failed to load RCA reports" type="error" showIcon />

  const reports = Array.isArray(data) ? data : data?.reports || []

  const columns = [
    {
      title: 'Severity',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (s) => <Tag color={SEVERITY_COLOR[s] || 'default'}>{(s || 'N/A').toUpperCase()}</Tag>,
    },
    {
      title: 'Title',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (t, r) => t || r.summary || r.id || '-',
    },
    {
      title: 'Root Cause',
      dataIndex: 'root_cause',
      key: 'root_cause',
      ellipsis: true,
      render: (t) => <Text style={{ color: '#ccc' }}>{t || '-'}</Text>,
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
      title={<><FileTextOutlined /> RCA Reports</>}
      size="small"
      bordered={false}
      style={{ background: '#1a1a2e' }}
    >
      {reports.length === 0 && !isLoading ? (
        <Empty description="No RCA reports yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table
          dataSource={reports}
          columns={columns}
          rowKey={(r) => r.id || r.report_id || Math.random()}
          size="small"
          loading={isLoading}
          pagination={{ pageSize: 10 }}
        />
      )}
    </Card>
  )
}

export default function Diagnose() {
  return (
    <div style={{ padding: '16px 24px' }}>
      <Title level={4} style={{ margin: '0 0 16px', color: '#eee' }}>
        🔍 Diagnose
      </Title>

      {/* Topology placeholder */}
      <Card
        size="small"
        bordered={false}
        style={{ background: '#1a1a2e', marginBottom: 16, textAlign: 'center', padding: 24 }}
      >
        <SearchOutlined style={{ fontSize: 32, color: '#444', marginBottom: 8 }} />
        <Paragraph style={{ color: '#666' }}>
          Topology visualization coming in Phase 2 (ReactFlow)
        </Paragraph>
      </Card>

      {/* RCA Reports */}
      <RCAReportList />
    </div>
  )
}
