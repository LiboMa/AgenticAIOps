import { useState, useEffect, useCallback } from 'react'
import { 
  Table, Tag, Button, Space, Modal, Descriptions, Card, Typography, Input, Select,
  message, Badge, Tabs, Timeline, Avatar, Row, Col, Statistic, Divider, Steps, Checkbox,
  Alert, Progress, Spin
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  SearchOutlined,
  ReloadOutlined,
  EyeOutlined,
  UserOutlined,
  ClockCircleOutlined,
  ToolOutlined,
  FileSearchOutlined,
  SafetyOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'

const { Title, Text } = Typography
const { TabPane } = Tabs

const severityConfig = {
  low: { color: 'blue', label: 'Low', priority: 'P4' },
  medium: { color: 'orange', label: 'Medium', priority: 'P3' },
  high: { color: 'red', label: 'High', priority: 'P2' },
  critical: { color: 'magenta', label: 'Critical', priority: 'P1' },
}

const statusConfig = {
  detected: { color: '#CC2936', bg: '#fff2f0', label: 'Triggered' },
  open: { color: '#CC2936', bg: '#fff2f0', label: 'Triggered' },
  in_progress: { color: '#F2A900', bg: '#fffbe6', label: 'Acknowledged' },
  fixed: { color: '#06AC38', bg: '#f6ffed', label: 'Resolved' },
  resolved: { color: '#06AC38', bg: '#f6ffed', label: 'Resolved' },
  closed: { color: '#666', bg: '#fafafa', label: 'Closed' },
}

function IssueCenter({ apiUrl }) {
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(false)
  const [dashboardData, setDashboardData] = useState({})
  const [selectedIssue, setSelectedIssue] = useState(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [fixLoading, setFixLoading] = useState({})
  const [activeTab, setActiveTab] = useState('triggered')
  
  // RCA & Manual Fix state
  const [rcaLoading, setRcaLoading] = useState(false)
  const [rcaResult, setRcaResult] = useState(null)
  const [sopList, setSopList] = useState([])
  const [manualFixVisible, setManualFixVisible] = useState(false)
  const [currentExecution, setCurrentExecution] = useState(null)
  const [stepLoading, setStepLoading] = useState(false)
  const [detailTab, setDetailTab] = useState('info')

  const fetchIssues = useCallback(async () => {
    setLoading(true)
    try {
      const [issuesRes, dashboardRes] = await Promise.all([
        fetch(`${apiUrl}/api/issues?limit=100`).then(r => r.json()),
        fetch(`${apiUrl}/api/issues/dashboard`).then(r => r.json()),
      ])
      setIssues(issuesRes.issues || [])
      setDashboardData(dashboardRes)
    } catch (err) {
      message.error('Failed to fetch incidents')
    } finally {
      setLoading(false)
    }
  }, [apiUrl])

  useEffect(() => {
    fetchIssues()
    const interval = setInterval(fetchIssues, 30000)
    return () => clearInterval(interval)
  }, [fetchIssues])

  const handleAutoFix = async (issue) => {
    setFixLoading(prev => ({ ...prev, [issue.id]: true }))
    try {
      const res = await fetch(`${apiUrl}/api/issues/${issue.id}/fix`, { method: 'POST' })
      const result = await res.json()
      if (result.status === 'initiated') {
        message.success(`Auto-remediation started: ${result.runbook_id}`)
      } else {
        message.warning(result.message || 'No runbook available')
      }
      setTimeout(fetchIssues, 2000)
    } catch (err) {
      message.error('Remediation request failed')
    } finally {
      setFixLoading(prev => ({ ...prev, [issue.id]: false }))
    }
  }

  const handleAcknowledge = async (issueId) => {
    try {
      await fetch(`${apiUrl}/api/issues/${issueId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'in_progress' }),
      })
      message.success('Incident acknowledged')
      fetchIssues()
    } catch (err) {
      message.error('Update failed')
    }
  }

  const handleResolve = async (issueId) => {
    try {
      await fetch(`${apiUrl}/api/issues/${issueId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'resolved' }),
      })
      message.success('Incident resolved')
      fetchIssues()
      setDetailVisible(false)
    } catch (err) {
      message.error('Update failed')
    }
  }

  // ── RCA Analysis ──
  const handleRunRCA = async (issue) => {
    setRcaLoading(true)
    setRcaResult(null)
    try {
      const res = await fetch(`${apiUrl}/api/rca/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: `${issue.title}: ${issue.description || ''} Resource: ${issue.resource_type}/${issue.resource_name}`,
          severity: issue.severity,
        }),
      })
      const result = await res.json()
      if (result.success !== false) {
        setRcaResult(result)
        message.success('RCA analysis complete')
        // Fetch suggested SOPs
        fetchSopSuggestions(issue)
      } else {
        message.error(result.error || 'RCA analysis failed')
      }
    } catch (err) {
      message.error('RCA request failed')
    } finally {
      setRcaLoading(false)
    }
  }

  const fetchSopSuggestions = async (issue) => {
    try {
      const res = await fetch(`${apiUrl}/api/sop/suggest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword: issue.title || issue.type }),
      })
      const result = await res.json()
      setSopList(result.suggestions || result.sops || [])
    } catch (err) {
      console.warn('Failed to fetch SOP suggestions')
    }
  }

  // ── Manual Fix Flow ──
  const handleStartManualFix = async (sopId) => {
    setStepLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/sop/execute/${sopId}/manual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ incident_id: selectedIssue?.id }),
      })
      const result = await res.json()
      if (result.success) {
        setCurrentExecution(result)
        setManualFixVisible(true)
        message.success(`SOP execution started: ${result.sop_name}`)
      } else {
        message.error(result.error || 'Failed to start SOP execution')
      }
    } catch (err) {
      message.error('Failed to start manual fix')
    } finally {
      setStepLoading(false)
    }
  }

  const handleCompleteStep = async (stepIndex) => {
    if (!currentExecution) return
    setStepLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/sop/execute/${currentExecution.execution_id}/step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step_index: stepIndex, result: 'success' }),
      })
      const result = await res.json()
      if (result.success) {
        setCurrentExecution(prev => ({
          ...prev,
          steps: prev.steps.map((s, i) => i === stepIndex ? { ...s, status: 'completed' } : s),
        }))
        if (result.completed) {
          message.success('All steps completed!')
        }
      }
    } catch (err) {
      message.error('Failed to complete step')
    } finally {
      setStepLoading(false)
    }
  }

  const handleCompleteExecution = async (result = 'resolved') => {
    if (!currentExecution) return
    try {
      const res = await fetch(`${apiUrl}/api/sop/execute/${currentExecution.execution_id}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overall_result: result }),
      })
      const data = await res.json()
      if (data.success) {
        message.success(`Fix ${result}! ${data.feedback_recorded ? 'Feedback recorded.' : ''}`)
        setManualFixVisible(false)
        setCurrentExecution(null)
        if (selectedIssue) handleResolve(selectedIssue.id)
      }
    } catch (err) {
      message.error('Failed to complete execution')
    }
  }

  const columns = [
    {
      title: 'Status',
      dataIndex: 'status',
      width: 130,
      render: (status) => {
        const config = statusConfig[status] || statusConfig.open
        return (
          <Tag 
            style={{ 
              background: config.bg, 
              color: config.color, 
              border: `1px solid ${config.color}`,
              borderRadius: 12,
              padding: '2px 12px',
            }}
          >
            {config.label}
          </Tag>
        )
      },
    },
    {
      title: 'Priority',
      dataIndex: 'severity',
      width: 80,
      render: (severity) => {
        const config = severityConfig[severity] || severityConfig.low
        return (
          <Tag color={config.color} style={{ fontWeight: 600 }}>
            {config.priority}
          </Tag>
        )
      },
    },
    {
      title: 'Incident',
      dataIndex: 'title',
      render: (title, record) => (
        <div>
          <a 
            onClick={() => { 
              setSelectedIssue(record)
              setDetailVisible(true)
              setDetailTab('info')
              setRcaResult(null)
              setSopList([])
            }}
            style={{ fontWeight: 500 }}
          >
            {title}
          </a>
          <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
            {record.resource_type}/{record.resource_name} • {record.namespace}
          </div>
        </div>
      ),
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      width: 140,
      render: (time) => (
        <Space>
          <ClockCircleOutlined style={{ color: '#999' }} />
          <Text type="secondary" style={{ fontSize: 13 }}>
            {time ? new Date(time).toLocaleString() : '-'}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Actions',
      width: 280,
      render: (_, record) => (
        <Space>
          {record.status === 'detected' && (
            <Button size="small" onClick={() => handleAcknowledge(record.id)}>
              Acknowledge
            </Button>
          )}
          {(record.status === 'detected' || record.status === 'in_progress') && (
            <Button 
              size="small" 
              type="primary"
              icon={<ToolOutlined />}
              onClick={() => {
                setSelectedIssue(record)
                setDetailVisible(true)
                setDetailTab('rca')
                setRcaResult(null)
                setSopList([])
                handleRunRCA(record)
              }}
            >
              Diagnose & Fix
            </Button>
          )}
          {record.status === 'detected' && record.auto_fixable && (
            <Button 
              size="small" 
              icon={<ThunderboltOutlined />}
              loading={fixLoading[record.id]}
              onClick={() => handleAutoFix(record)}
              style={{ background: '#06AC38', borderColor: '#06AC38', color: '#fff' }}
            >
              Auto Fix
            </Button>
          )}
        </Space>
      ),
    },
  ]

  // Filter issues by tab
  const filteredIssues = issues.filter(i => {
    if (activeTab === 'triggered') return i.status === 'detected' || i.status === 'open'
    if (activeTab === 'acknowledged') return i.status === 'in_progress'
    if (activeTab === 'resolved') return i.status === 'resolved' || i.status === 'fixed' || i.status === 'closed'
    return true
  })

  const stats = dashboardData.stats || {}
  const statusCounts = stats.by_status || {}

  // ── RCA Report Panel ──
  const RCAPanel = () => (
    <div>
      {rcaLoading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" />
          <div style={{ marginTop: 16 }}>
            <Text type="secondary">Running RCA analysis with AI...</Text>
          </div>
        </div>
      ) : rcaResult ? (
        <div>
          <Alert
            message="Root Cause Analysis Complete"
            description={
              <div>
                <p><strong>Root Cause:</strong> {rcaResult.root_cause || rcaResult.analysis || 'Analysis complete'}</p>
                {rcaResult.confidence && (
                  <p><strong>Confidence:</strong> <Progress percent={Math.round(rcaResult.confidence * 100)} size="small" style={{ width: 200 }} /></p>
                )}
                {rcaResult.severity && <p><strong>Severity:</strong> <Tag color={severityConfig[rcaResult.severity]?.color}>{rcaResult.severity}</Tag></p>}
              </div>
            }
            type="info"
            showIcon
            icon={<FileSearchOutlined />}
            style={{ marginBottom: 16 }}
          />

          {rcaResult.recommendations && (
            <Card title="Recommendations" size="small" style={{ marginBottom: 16 }}>
              {(Array.isArray(rcaResult.recommendations) ? rcaResult.recommendations : [rcaResult.recommendations]).map((rec, i) => (
                <p key={i}>• {rec}</p>
              ))}
            </Card>
          )}

          {/* SOP Suggestions */}
          <Card title="Recommended SOPs — Manual Fix" size="small" style={{ marginBottom: 16 }}>
            {sopList.length > 0 ? (
              sopList.map((sop) => (
                <Card.Grid key={sop.sop_id || sop.id} style={{ width: '100%', padding: 12 }}>
                  <Row justify="space-between" align="middle">
                    <Col>
                      <Text strong>{sop.name || sop.sop_id}</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {sop.description || `Confidence: ${sop.confidence || '-'}`}
                      </Text>
                    </Col>
                    <Col>
                      <Button 
                        type="primary"
                        icon={<ToolOutlined />}
                        loading={stepLoading}
                        onClick={() => handleStartManualFix(sop.sop_id || sop.id)}
                      >
                        Apply Fix
                      </Button>
                    </Col>
                  </Row>
                </Card.Grid>
              ))
            ) : (
              <Text type="secondary">No SOP suggestions available. Use Chat to run: <code>sop suggest {selectedIssue?.title}</code></Text>
            )}
          </Card>

          <Button 
            icon={<ExperimentOutlined />}
            onClick={() => handleRunRCA(selectedIssue)}
            loading={rcaLoading}
          >
            Re-analyze
          </Button>
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <FileSearchOutlined style={{ fontSize: 48, color: '#999' }} />
          <div style={{ marginTop: 16 }}>
            <Button 
              type="primary" 
              icon={<SearchOutlined />}
              onClick={() => handleRunRCA(selectedIssue)}
              loading={rcaLoading}
              size="large"
            >
              Run RCA Analysis
            </Button>
          </div>
          <div style={{ marginTop: 8 }}>
            <Text type="secondary">Analyze root cause and get fix recommendations</Text>
          </div>
        </div>
      )}
    </div>
  )

  return (
    <div>
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>Incidents</Title>
        <Text type="secondary">Manage and respond to operational incidents — Diagnose & Fix</Text>
      </div>

      {/* Stats Bar */}
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Row gutter={32}>
          <Col>
            <Statistic 
              title="Triggered" 
              value={statusCounts.detected || 0}
              valueStyle={{ color: '#CC2936' }}
            />
          </Col>
          <Col><Divider type="vertical" style={{ height: 50 }} /></Col>
          <Col>
            <Statistic 
              title="Acknowledged" 
              value={statusCounts.in_progress || 0}
              valueStyle={{ color: '#F2A900' }}
            />
          </Col>
          <Col><Divider type="vertical" style={{ height: 50 }} /></Col>
          <Col>
            <Statistic 
              title="Resolved" 
              value={statusCounts.fixed || 0}
              valueStyle={{ color: '#06AC38' }}
            />
          </Col>
          <Col><Divider type="vertical" style={{ height: 50 }} /></Col>
          <Col>
            <Statistic 
              title="Total" 
              value={stats.total || issues.length}
              valueStyle={{ color: '#666' }}
            />
          </Col>
        </Row>
      </Card>

      {/* Incidents Table with Tabs */}
      <Card 
        bordered={false}
        bodyStyle={{ padding: 0 }}
        extra={
          <Button 
            icon={<ReloadOutlined />} 
            onClick={fetchIssues}
            loading={loading}
          >
            Refresh
          </Button>
        }
      >
        <Tabs 
          activeKey={activeTab} 
          onChange={setActiveTab}
          style={{ marginBottom: 0 }}
          tabBarStyle={{ padding: '0 16px', marginBottom: 0 }}
        >
          <TabPane 
            tab={<Badge count={statusCounts.detected || 0} offset={[10, 0]}>Triggered</Badge>} 
            key="triggered" 
          />
          <TabPane 
            tab={<Badge count={statusCounts.in_progress || 0} offset={[10, 0]}>Acknowledged</Badge>} 
            key="acknowledged" 
          />
          <TabPane tab={`Resolved (${statusCounts.fixed || 0})`} key="resolved" />
          <TabPane tab="All" key="all" />
        </Tabs>
        
        <Table
          columns={columns}
          dataSource={filteredIssues}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          style={{ borderTop: '1px solid #f0f0f0' }}
        />
      </Card>

      {/* Detail Modal with RCA Tab */}
      <Modal
        title={
          <Space>
            <Tag color={statusConfig[selectedIssue?.status]?.color}>
              {statusConfig[selectedIssue?.status]?.label}
            </Tag>
            <span>{selectedIssue?.title}</span>
          </Space>
        }
        open={detailVisible}
        onCancel={() => { setDetailVisible(false); setRcaResult(null); setSopList([]); }}
        width={800}
        footer={[
          selectedIssue?.status === 'open' && (
            <Button key="ack" onClick={() => handleAcknowledge(selectedIssue?.id)}>
              Acknowledge
            </Button>
          ),
          selectedIssue?.status !== 'resolved' && selectedIssue?.status !== 'fixed' && (
            <Button 
              key="resolve" 
              type="primary"
              onClick={() => handleResolve(selectedIssue?.id)}
              style={{ background: '#06AC38', borderColor: '#06AC38' }}
            >
              Mark Resolved
            </Button>
          ),
          <Button key="close" onClick={() => setDetailVisible(false)}>Close</Button>,
        ]}
      >
        {selectedIssue && (
          <Tabs activeKey={detailTab} onChange={setDetailTab}>
            <TabPane tab={<span><EyeOutlined /> Info</span>} key="info">
              <Descriptions column={2} bordered size="small">
                <Descriptions.Item label="ID">{selectedIssue.id}</Descriptions.Item>
                <Descriptions.Item label="Priority">
                  <Tag color={severityConfig[selectedIssue.severity]?.color}>
                    {severityConfig[selectedIssue.severity]?.priority} — {selectedIssue.severity}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="Namespace">{selectedIssue.namespace}</Descriptions.Item>
                <Descriptions.Item label="Resource">
                  {selectedIssue.resource_type}/{selectedIssue.resource_name}
                </Descriptions.Item>
                <Descriptions.Item label="Description" span={2}>
                  {selectedIssue.description || 'No description'}
                </Descriptions.Item>
                {selectedIssue.root_cause && (
                  <Descriptions.Item label="Root Cause" span={2}>
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                      {selectedIssue.root_cause}
                    </pre>
                  </Descriptions.Item>
                )}
                <Descriptions.Item label="Created">
                  {selectedIssue.created_at ? new Date(selectedIssue.created_at).toLocaleString() : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="Updated">
                  {selectedIssue.updated_at ? new Date(selectedIssue.updated_at).toLocaleString() : '-'}
                </Descriptions.Item>
              </Descriptions>
            </TabPane>
            
            <TabPane tab={<span><FileSearchOutlined /> RCA & Fix</span>} key="rca">
              <RCAPanel />
            </TabPane>
          </Tabs>
        )}
      </Modal>

      {/* Manual Fix Execution Modal */}
      <Modal
        title={
          <Space>
            <ToolOutlined />
            <span>Manual Fix — {currentExecution?.sop_name}</span>
          </Space>
        }
        open={manualFixVisible}
        onCancel={() => { setManualFixVisible(false); setCurrentExecution(null); }}
        width={600}
        footer={[
          <Button 
            key="fail" 
            danger
            onClick={() => handleCompleteExecution('failed')}
          >
            Mark Failed
          </Button>,
          <Button 
            key="complete" 
            type="primary"
            onClick={() => handleCompleteExecution('resolved')}
            style={{ background: '#06AC38', borderColor: '#06AC38' }}
            disabled={currentExecution?.steps?.some(s => s.status === 'pending')}
          >
            Complete Fix ✓
          </Button>,
        ]}
      >
        {currentExecution && (
          <div>
            {currentExecution.safety && (
              <Alert
                message={`Safety: ${currentExecution.safety.risk_level || 'Unknown'} — ${currentExecution.safety.execution_mode || 'dry_run'}`}
                type={currentExecution.safety.risk_level === 'L1' ? 'success' : 'warning'}
                icon={<SafetyOutlined />}
                showIcon
                style={{ marginBottom: 16 }}
              />
            )}
            
            <Steps 
              direction="vertical" 
              current={currentExecution.steps?.filter(s => s.status === 'completed').length || 0}
              size="small"
            >
              {currentExecution.steps?.map((step, i) => (
                <Steps.Step
                  key={i}
                  title={
                    <Row justify="space-between" align="middle">
                      <Col flex="auto">
                        <Text>{step.description}</Text>
                      </Col>
                      <Col>
                        {step.status === 'pending' ? (
                          <Button 
                            size="small" 
                            type="primary"
                            onClick={() => handleCompleteStep(i)}
                            loading={stepLoading}
                          >
                            Done ✓
                          </Button>
                        ) : (
                          <Tag color="green">Completed</Tag>
                        )}
                      </Col>
                    </Row>
                  }
                  status={step.status === 'completed' ? 'finish' : step.status === 'pending' ? 'wait' : 'process'}
                />
              ))}
            </Steps>

            <div style={{ marginTop: 16, textAlign: 'center' }}>
              <Progress 
                percent={Math.round((currentExecution.steps?.filter(s => s.status === 'completed').length || 0) / (currentExecution.total_steps || 1) * 100)}
                status="active"
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

export default IssueCenter
