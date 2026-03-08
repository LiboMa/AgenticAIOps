/**
 * Diagnose — Investigation Center
 * "深入分析一个问题"
 *
 * Phase 2: RCA Reports + Detail + Knowledge Search + SOP List
 * Phase 3: Topology (ReactFlow)
 */

import { useState } from 'react'
import {
  Card, Table, Tag, Empty, Alert, Typography, Space, Input, Button,
  Drawer, Descriptions, List, Spin, Divider, Row, Col, Badge, Timeline,
} from 'antd'
import {
  SearchOutlined, FileTextOutlined, ThunderboltOutlined,
  BulbOutlined, BookOutlined, CloseOutlined,
} from '@ant-design/icons'
import {
  useRCAReports, useRCADetail, useKnowledgeSearch, useSOPList,
} from '../hooks/useApi'

const { Title, Text, Paragraph } = Typography

const SEVERITY_COLOR = { critical: 'red', high: 'orange', medium: 'gold', low: 'green', info: 'blue' }

// ── RCA Detail Drawer ──
function RCADetailDrawer({ reportId, onClose }) {
  const { data, isLoading, error } = useRCADetail(reportId)

  if (!reportId) return null

  const report = data?.report || data || {}

  return (
    <Drawer
      title={<><FileTextOutlined /> RCA Report</>}
      open={!!reportId}
      onClose={onClose}
      width={640}
      styles={{ body: { background: '#0f0f1a' } }}
    >
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>
      ) : error ? (
        <Alert message="Failed to load report" type="error" />
      ) : (
        <>
          <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="ID">{report.id || reportId}</Descriptions.Item>
            <Descriptions.Item label="Severity">
              <Tag color={SEVERITY_COLOR[report.severity] || 'default'}>
                {(report.severity || 'N/A').toUpperCase()}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Title">{report.title || report.summary || '-'}</Descriptions.Item>
            <Descriptions.Item label="Created">{report.created_at ? new Date(report.created_at).toLocaleString() : '-'}</Descriptions.Item>
          </Descriptions>

          <Card size="small" title="Root Cause" bordered={false} style={{ background: '#1a1a2e', marginBottom: 12 }}>
            <Paragraph style={{ color: '#ddd', whiteSpace: 'pre-wrap' }}>
              {report.root_cause || report.analysis || 'No root cause identified'}
            </Paragraph>
          </Card>

          {report.recommendations && (
            <Card size="small" title="Recommendations" bordered={false} style={{ background: '#1a1a2e', marginBottom: 12 }}>
              {Array.isArray(report.recommendations) ? (
                <List
                  size="small"
                  dataSource={report.recommendations}
                  renderItem={(item, i) => (
                    <List.Item style={{ borderBottom: '1px solid #303030' }}>
                      <Text style={{ color: '#ccc' }}>{i + 1}. {typeof item === 'string' ? item : item.text || JSON.stringify(item)}</Text>
                    </List.Item>
                  )}
                />
              ) : (
                <Paragraph style={{ color: '#ddd' }}>{String(report.recommendations)}</Paragraph>
              )}
            </Card>
          )}

          {report.timeline && Array.isArray(report.timeline) && (
            <Card size="small" title="Timeline" bordered={false} style={{ background: '#1a1a2e' }}>
              <Timeline
                items={report.timeline.map((e) => ({
                  children: (
                    <div>
                      <Text style={{ color: '#aaa', fontSize: 11 }}>{e.timestamp || e.time}</Text>
                      <br />
                      <Text style={{ color: '#ddd' }}>{e.description || e.event || JSON.stringify(e)}</Text>
                    </div>
                  ),
                }))}
              />
            </Card>
          )}
        </>
      )}
    </Drawer>
  )
}

// ── Knowledge Search ──
function KnowledgeSearchPanel() {
  const [query, setQuery] = useState('')
  const { mutate: search, data, isPending } = useKnowledgeSearch()

  const results = data?.results || data?.cases || []

  return (
    <Card
      title={<><BulbOutlined /> Similar Cases (Knowledge Base)</>}
      size="small"
      bordered={false}
      style={{ background: '#1a1a2e' }}
    >
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input
          placeholder="Search knowledge base..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={() => query.trim() && search(query.trim())}
          prefix={<SearchOutlined style={{ color: '#666' }} />}
        />
        <Button
          type="primary"
          onClick={() => query.trim() && search(query.trim())}
          loading={isPending}
        >
          Search
        </Button>
      </Space.Compact>

      {results.length > 0 ? (
        <List
          size="small"
          dataSource={results.slice(0, 10)}
          renderItem={(item) => (
            <List.Item style={{ borderBottom: '1px solid #252540' }}>
              <List.Item.Meta
                title={<Text style={{ color: '#ddd' }}>{item.title || item.summary || 'Case'}</Text>}
                description={
                  <Space>
                    {item.score && <Tag color="blue">Score: {(item.score * 100).toFixed(0)}%</Tag>}
                    {item.severity && <Tag color={SEVERITY_COLOR[item.severity]}>{item.severity}</Tag>}
                    <Text style={{ color: '#888', fontSize: 12 }}>{item.description || item.root_cause || ''}</Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      ) : (
        <Empty description="Search to find similar cases" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
    </Card>
  )
}

// ── SOP Quick Actions ──
function SOPPanel() {
  const { data, isLoading, error } = useSOPList()

  if (error) return <Alert message="Failed to load SOPs" type="warning" showIcon />

  const sops = Array.isArray(data) ? data : data?.sops || data?.items || []

  return (
    <Card
      title={<><BookOutlined /> SOPs</>}
      size="small"
      bordered={false}
      style={{ background: '#1a1a2e' }}
    >
      {isLoading ? (
        <Spin />
      ) : sops.length === 0 ? (
        <Empty description="No SOPs available" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          size="small"
          dataSource={sops.slice(0, 15)}
          renderItem={(sop) => (
            <List.Item style={{ borderBottom: '1px solid #252540' }}>
              <List.Item.Meta
                title={<Text style={{ color: '#ddd' }}>{sop.name || sop.title || sop.id}</Text>}
                description={
                  <Space>
                    {sop.risk_level != null && (
                      <Tag color={sop.risk_level <= 1 ? 'green' : sop.risk_level <= 2 ? 'gold' : 'red'}>
                        L{sop.risk_level}
                      </Tag>
                    )}
                    <Text style={{ color: '#888', fontSize: 12 }}>{sop.description || sop.pattern || ''}</Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

// ── RCA Reports Table ──
function RCAReportList({ onSelect }) {
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
      render: (t, r) => (
        <a onClick={() => onSelect(r.id || r.report_id)} style={{ color: '#69b1ff' }}>
          {t || r.summary || r.id || '-'}
        </a>
      ),
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

// ── Main ──
export default function Diagnose() {
  const [selectedReport, setSelectedReport] = useState(null)

  return (
    <div style={{ padding: '16px 24px' }}>
      <Title level={4} style={{ margin: '0 0 16px', color: '#eee' }}>
        🔍 Diagnose
      </Title>

      <Row gutter={[16, 16]}>
        {/* Left: RCA Reports */}
        <Col xs={24} lg={14}>
          <RCAReportList onSelect={setSelectedReport} />
        </Col>

        {/* Right: Knowledge + SOP */}
        <Col xs={24} lg={10}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <KnowledgeSearchPanel />
            <SOPPanel />
          </Space>
        </Col>
      </Row>

      {/* RCA Detail Drawer */}
      <RCADetailDrawer reportId={selectedReport} onClose={() => setSelectedReport(null)} />
    </div>
  )
}
