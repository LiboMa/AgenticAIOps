import { useState, useEffect, useCallback } from 'react'
import { 
  Card, Row, Col, Statistic, Table, Tag, Space, Button, Typography, Timeline, 
  Progress, Badge, Tabs, Descriptions, message, Empty, Spin, Alert, Tooltip
} from 'antd'
import {
  ThunderboltOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  SafetyOutlined,
  BulbOutlined,
  HistoryOutlined,
  RocketOutlined,
  ExperimentOutlined,
  ReloadOutlined,
  BookOutlined,
  RiseOutlined,
  FallOutlined,
} from '@ant-design/icons'

const { Title, Text } = Typography
const { TabPane } = Tabs

function Automation({ apiUrl }) {
  const [loading, setLoading] = useState(false)
  const [runbooks, setRunbooks] = useState([])
  const [executions, setExecutions] = useState([])
  const [feedbackStats, setFeedbackStats] = useState({})
  const [bridgeHistory, setBridgeHistory] = useState([])
  const [approvals, setApprovals] = useState([])
  const [safetyStats, setSafetyStats] = useState({})
  const [incidentStats, setIncidentStats] = useState({})

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const endpoints = [
        `${apiUrl}/api/runbooks`,
        `${apiUrl}/api/runbooks/executions`,
        `${apiUrl}/api/rca/bridge/stats`,
        `${apiUrl}/api/rca/bridge/history`,
        `${apiUrl}/api/safety/approvals`,
        `${apiUrl}/api/safety/stats`,
        `${apiUrl}/api/incident/stats`,
      ]
      const results = await Promise.allSettled(endpoints.map(url => fetch(url).then(r => r.json())))
      
      if (results[0].status === 'fulfilled') setRunbooks(results[0].value.runbooks || results[0].value || [])
      if (results[1].status === 'fulfilled') setExecutions(results[1].value.executions || results[1].value || [])
      if (results[2].status === 'fulfilled') setFeedbackStats(results[2].value)
      if (results[3].status === 'fulfilled') setBridgeHistory(results[3].value.history || results[3].value || [])
      if (results[4].status === 'fulfilled') setApprovals(results[4].value.approvals || [])
      if (results[5].status === 'fulfilled') setSafetyStats(results[5].value)
      if (results[6].status === 'fulfilled') setIncidentStats(results[6].value)
    } catch (err) {
      console.error('Failed to fetch automation data:', err)
    } finally {
      setLoading(false)
    }
  }, [apiUrl])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleApprove = async (approvalId) => {
    try {
      const res = await fetch(`${apiUrl}/api/safety/approve/${approvalId}`, { method: 'POST' })
      const result = await res.json()
      if (result.success) {
        message.success(`Approved: ${approvalId}`)
        fetchData()
      } else {
        message.error(result.error || 'Approval failed')
      }
    } catch (err) {
      message.error('Failed to approve')
    }
  }

  const handleReject = async (approvalId) => {
    try {
      const res = await fetch(`${apiUrl}/api/safety/reject/${approvalId}`, { method: 'POST' })
      const result = await res.json()
      if (result.success) {
        message.info(`Rejected: ${approvalId}`)
        fetchData()
      }
    } catch (err) {
      message.error('Failed to reject')
    }
  }

  // Stats
  const stats = feedbackStats || {}
  const successRate = stats.success_rate ? (stats.success_rate * 100).toFixed(0) : 0
  const learnedMappings = stats.learned_mappings || {}
  const learnedCount = Object.keys(learnedMappings).reduce(
    (sum, k) => sum + Object.keys(learnedMappings[k]).length, 0
  )

  return (
    <div>
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          <RocketOutlined style={{ color: '#06AC38', marginRight: 8 }} />
          Automation & Remediation
        </Title>
        <Text type="secondary">L4 AgenticOps — Auto-detect, Auto-fix, Auto-learn</Text>
      </div>

      {/* Stats Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card bordered={false} style={{ borderTop: '3px solid #06AC38' }}>
            <Statistic
              title="Runbooks"
              value={Array.isArray(runbooks) ? runbooks.length : 0}
              prefix={<BookOutlined style={{ color: '#06AC38' }} />}
              suffix="available"
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card bordered={false} style={{ borderTop: '3px solid #1890ff' }}>
            <Statistic
              title="Executions"
              value={Array.isArray(executions) ? executions.length : 0}
              prefix={<ThunderboltOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card bordered={false} style={{ borderTop: '3px solid #52c41a' }}>
            <Statistic
              title="Success Rate"
              value={successRate}
              suffix="%"
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card bordered={false} style={{ borderTop: '3px solid #722ed1' }}>
            <Statistic
              title="Learned Patterns"
              value={learnedCount}
              prefix={<BulbOutlined style={{ color: '#722ed1' }} />}
              suffix="mappings"
            />
          </Card>
        </Col>
      </Row>

      {/* Pending Approvals Alert */}
      {approvals.length > 0 && (
        <Alert
          message={`${approvals.length} Pending Approval(s)`}
          description="High-risk SOP executions require manual approval before proceeding."
          type="warning"
          showIcon
          icon={<SafetyOutlined />}
          style={{ marginBottom: 16 }}
          action={
            <Button size="small" onClick={() => document.getElementById('approvals-tab')?.click()}>
              Review
            </Button>
          }
        />
      )}

      {/* Main Tabs */}
      <Card bordered={false} bodyStyle={{ padding: 0 }}>
        <Tabs defaultActiveKey="runbooks" tabBarStyle={{ padding: '0 16px' }}>
          {/* Runbooks Tab */}
          <TabPane tab={<span><BookOutlined /> Runbooks ({Array.isArray(runbooks) ? runbooks.length : 0})</span>} key="runbooks">
            <Table
              dataSource={Array.isArray(runbooks) ? runbooks : []}
              rowKey="id"
              loading={loading}
              pagination={false}
              locale={{ emptyText: <Empty description="No runbooks loaded" /> }}
              columns={[
                {
                  title: 'Runbook',
                  dataIndex: 'name',
                  render: (name, record) => (
                    <div>
                      <Text strong>{name || record.id}</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 12 }}>{record.description}</Text>
                    </div>
                  ),
                },
                {
                  title: 'Triggers',
                  dataIndex: 'triggers',
                  render: (triggers) => (
                    <Space wrap>
                      {(triggers || []).map((t, i) => (
                        <Tag key={i} color="blue">{t.pattern_id || JSON.stringify(t)}</Tag>
                      ))}
                    </Space>
                  ),
                },
                {
                  title: 'Steps',
                  dataIndex: 'steps',
                  width: 80,
                  render: (steps) => <Tag>{(steps || []).length} steps</Tag>,
                },
                {
                  title: 'Rollback',
                  dataIndex: 'rollback',
                  width: 80,
                  render: (rollback) => rollback?.length > 0 ? 
                    <Tag color="green">✓ Yes</Tag> : <Tag>No</Tag>,
                },
              ]}
            />
          </TabPane>

          {/* Executions Tab */}
          <TabPane tab={<span><ThunderboltOutlined /> Executions ({Array.isArray(executions) ? executions.length : 0})</span>} key="executions">
            <Table
              dataSource={Array.isArray(executions) ? executions : []}
              rowKey="execution_id"
              loading={loading}
              pagination={{ pageSize: 10 }}
              locale={{ emptyText: <Empty description="No executions yet — auto-fix an issue to start" /> }}
              columns={[
                {
                  title: 'Execution',
                  dataIndex: 'execution_id',
                  width: 100,
                  render: (id) => <Text code>{id?.substring(0, 8)}</Text>,
                },
                {
                  title: 'Runbook',
                  dataIndex: 'runbook_id',
                  render: (id) => <Tag color="blue">{id}</Tag>,
                },
                {
                  title: 'Status',
                  dataIndex: 'status',
                  width: 100,
                  render: (status) => {
                    const config = {
                      success: { color: 'green', icon: <CheckCircleOutlined /> },
                      failed: { color: 'red', icon: <CloseCircleOutlined /> },
                      running: { color: 'processing', icon: <SyncOutlined spin /> },
                      rolled_back: { color: 'orange', icon: <HistoryOutlined /> },
                    }
                    const c = config[status] || config.running
                    return <Tag color={c.color} icon={c.icon}>{status}</Tag>
                  },
                },
                {
                  title: 'Issue',
                  dataIndex: 'issue_id',
                  render: (id) => id ? <Text type="secondary">{id?.substring(0, 8)}</Text> : '-',
                },
                {
                  title: 'Time',
                  dataIndex: 'started_at',
                  width: 160,
                  render: (t) => t ? new Date(t).toLocaleString() : '-',
                },
              ]}
            />
          </TabPane>

          {/* Approvals Tab */}
          <TabPane 
            tab={
              <span id="approvals-tab">
                <SafetyOutlined /> 
                Approvals
                {approvals.length > 0 && <Badge count={approvals.length} style={{ marginLeft: 8 }} />}
              </span>
            } 
            key="approvals"
          >
            {approvals.length === 0 ? (
              <Empty description="No pending approvals" style={{ padding: 40 }} />
            ) : (
              <Table
                dataSource={approvals}
                rowKey="approval_id"
                pagination={false}
                columns={[
                  {
                    title: 'SOP',
                    dataIndex: 'sop_id',
                    render: (id) => <Tag color="orange">{id}</Tag>,
                  },
                  {
                    title: 'Risk Level',
                    dataIndex: 'risk_level',
                    render: (level) => {
                      const colors = { L0: 'green', L1: 'blue', L2: 'orange', L3: 'red' }
                      return <Tag color={colors[level] || 'default'}>{level}</Tag>
                    },
                  },
                  {
                    title: 'Requested',
                    dataIndex: 'requested_at',
                    render: (t) => t ? new Date(t).toLocaleString() : '-',
                  },
                  {
                    title: 'Actions',
                    render: (_, record) => (
                      <Space>
                        <Button 
                          type="primary" size="small"
                          style={{ background: '#06AC38', borderColor: '#06AC38' }}
                          onClick={() => handleApprove(record.approval_id)}
                        >
                          Approve
                        </Button>
                        <Button size="small" danger onClick={() => handleReject(record.approval_id)}>
                          Reject
                        </Button>
                      </Space>
                    ),
                  },
                ]}
              />
            )}
          </TabPane>

          {/* Learning Tab */}
          <TabPane tab={<span><BulbOutlined /> Learning</span>} key="learning">
            <Row gutter={[16, 16]} style={{ padding: 16 }}>
              <Col span={12}>
                <Card title="Feedback Summary" size="small">
                  <Descriptions column={1} size="small">
                    <Descriptions.Item label="Total Feedbacks">{stats.total_feedbacks || 0}</Descriptions.Item>
                    <Descriptions.Item label="Successful">
                      <Text type="success">{stats.successful || 0}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="Failed">
                      <Text type="danger">{stats.failed || 0}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="Root Cause Confirmed">{stats.root_cause_confirmed || 0}</Descriptions.Item>
                    <Descriptions.Item label="Avg Resolution">
                      {stats.avg_resolution_seconds ? `${Math.round(stats.avg_resolution_seconds)}s` : '-'}
                    </Descriptions.Item>
                  </Descriptions>
                </Card>
              </Col>
              <Col span={12}>
                <Card title="Learned Pattern → SOP Mappings" size="small">
                  {Object.keys(learnedMappings).length === 0 ? (
                    <Empty description="No learned mappings yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  ) : (
                    Object.entries(learnedMappings).map(([pattern, sops]) => (
                      <div key={pattern} style={{ marginBottom: 12 }}>
                        <Tag color="purple">{pattern}</Tag>
                        <span style={{ margin: '0 8px' }}>→</span>
                        {Object.entries(sops).map(([sopId, count]) => (
                          <Tooltip key={sopId} title={`${count} successful executions`}>
                            <Tag color="green">{sopId} ({count}×)</Tag>
                          </Tooltip>
                        ))}
                      </div>
                    ))
                  )}
                </Card>
              </Col>
              <Col span={24}>
                <Card title="Bridge History (RCA → SOP)" size="small">
                  <Table
                    dataSource={Array.isArray(bridgeHistory) ? bridgeHistory : []}
                    rowKey="execution_id"
                    pagination={{ pageSize: 5 }}
                    size="small"
                    locale={{ emptyText: "No bridge history" }}
                    columns={[
                      { title: 'Pattern', dataIndex: 'pattern_id', render: (v) => <Tag>{v || '-'}</Tag> },
                      { title: 'Root Cause', dataIndex: 'root_cause', ellipsis: true },
                      { 
                        title: 'Confidence', 
                        dataIndex: 'confidence', 
                        width: 120,
                        render: (v) => v ? <Progress percent={Math.round(v * 100)} size="small" /> : '-',
                      },
                      { title: 'SOPs Matched', dataIndex: 'matched_sops_count', width: 100 },
                      { title: 'Time', dataIndex: 'timestamp', width: 160, render: (t) => t ? new Date(t).toLocaleString() : '-' },
                    ]}
                  />
                </Card>
              </Col>
            </Row>
          </TabPane>
        </Tabs>
      </Card>

      {/* Refresh button */}
      <div style={{ textAlign: 'center', marginTop: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
          Refresh
        </Button>
      </div>
    </div>
  )
}

export default Automation
