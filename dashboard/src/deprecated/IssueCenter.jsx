import { useState, useEffect, useCallback } from 'react'
import { 
  Table, Tag, Button, Space, Modal, Descriptions, 
  message, Tooltip, Badge, Progress, Input, Select
} from 'antd'
import { ProCard, ProTable, StatisticCard } from '@ant-design/pro-components'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  SearchOutlined,
  ReloadOutlined,
  EyeOutlined,
  ToolOutlined,
} from '@ant-design/icons'

const { Statistic } = StatisticCard

const severityConfig = {
  low: { color: 'blue', label: '低' },
  medium: { color: 'orange', label: '中' },
  high: { color: 'red', label: '高' },
  critical: { color: 'magenta', label: '严重' },
}

const statusConfig = {
  open: { color: 'error', icon: <CloseCircleOutlined />, label: '待处理' },
  in_progress: { color: 'processing', icon: <SyncOutlined spin />, label: '处理中' },
  resolved: { color: 'success', icon: <CheckCircleOutlined />, label: '已解决' },
  closed: { color: 'default', icon: <CheckCircleOutlined />, label: '已关闭' },
}

function IssueCenter({ apiUrl }) {
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(false)
  const [dashboardData, setDashboardData] = useState({})
  const [selectedIssue, setSelectedIssue] = useState(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [fixLoading, setFixLoading] = useState({})

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
      message.error('获取问题列表失败')
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
      const res = await fetch(`${apiUrl}/api/issues/${issue.id}/fix`, {
        method: 'POST',
      })
      const result = await res.json()
      if (result.status === 'initiated') {
        message.success(`自动修复已启动: ${result.runbook_id}`)
      } else {
        message.warning(result.message || '无可用的修复方案')
      }
      setTimeout(fetchIssues, 2000)
    } catch (err) {
      message.error('修复请求失败')
    } finally {
      setFixLoading(prev => ({ ...prev, [issue.id]: false }))
    }
  }

  const handleResolve = async (issueId) => {
    try {
      await fetch(`${apiUrl}/api/issues/${issueId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'resolved' }),
      })
      message.success('问题已标记为已解决')
      fetchIssues()
      setDetailVisible(false)
    } catch (err) {
      message.error('更新失败')
    }
  }

  const columns = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      filters: Object.keys(statusConfig).map(k => ({ text: statusConfig[k].label, value: k })),
      onFilter: (value, record) => record.status === value,
      render: (status) => {
        const config = statusConfig[status] || statusConfig.open
        return (
          <Badge status={config.color} text={config.label} />
        )
      },
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      width: 80,
      filters: Object.keys(severityConfig).map(k => ({ text: severityConfig[k].label, value: k })),
      onFilter: (value, record) => record.severity === value,
      sorter: (a, b) => {
        const order = { critical: 4, high: 3, medium: 2, low: 1 }
        return order[b.severity] - order[a.severity]
      },
      render: (severity) => {
        const config = severityConfig[severity] || severityConfig.low
        return <Tag color={config.color}>{config.label}</Tag>
      },
    },
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      render: (text, record) => (
        <a onClick={() => { setSelectedIssue(record); setDetailVisible(true); }}>
          {text}
        </a>
      ),
    },
    {
      title: '命名空间',
      dataIndex: 'namespace',
      width: 120,
      filters: [...new Set(issues.map(i => i.namespace))].map(ns => ({ text: ns, value: ns })),
      onFilter: (value, record) => record.namespace === value,
    },
    {
      title: '资源',
      dataIndex: 'resource_name',
      width: 150,
      ellipsis: true,
      render: (name, record) => (
        <Tooltip title={`${record.resource_type}/${name}`}>
          <Tag>{record.resource_type}/{name}</Tag>
        </Tooltip>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      sorter: (a, b) => new Date(a.created_at) - new Date(b.created_at),
      render: (time) => time ? new Date(time).toLocaleString() : '-',
    },
    {
      title: '操作',
      width: 150,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <Tooltip title="查看详情">
            <Button
              type="text"
              icon={<EyeOutlined />}
              onClick={() => { setSelectedIssue(record); setDetailVisible(true); }}
            />
          </Tooltip>
          {record.status === 'open' && record.auto_fixable && (
            <Tooltip title="自动修复">
              <Button
                type="text"
                icon={<ThunderboltOutlined />}
                loading={fixLoading[record.id]}
                onClick={() => handleAutoFix(record)}
                style={{ color: '#faad14' }}
              />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ]

  const statusCounts = dashboardData.status_counts || {}
  const severityCounts = dashboardData.severity_counts || {}

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* Stats Cards */}
      <StatisticCard.Group direction="row">
        <StatisticCard
          statistic={{
            title: '待处理',
            value: statusCounts.open || 0,
            icon: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
          }}
        />
        <StatisticCard.Divider />
        <StatisticCard
          statistic={{
            title: '处理中',
            value: statusCounts.in_progress || 0,
            icon: <SyncOutlined spin style={{ color: '#1677ff' }} />,
          }}
        />
        <StatisticCard.Divider />
        <StatisticCard
          statistic={{
            title: '已解决',
            value: statusCounts.resolved || 0,
            icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
          }}
        />
        <StatisticCard.Divider />
        <StatisticCard
          statistic={{
            title: '高危问题',
            value: severityCounts.high || 0,
            icon: <WarningOutlined style={{ color: '#ff4d4f' }} />,
          }}
        />
      </StatisticCard.Group>

      {/* Issues Table */}
      <ProCard
        title="问题列表"
        extra={
          <Button
            icon={<ReloadOutlined />}
            onClick={fetchIssues}
            loading={loading}
          >
            刷新
          </Button>
        }
        style={{ background: '#141414' }}
        headStyle={{ borderBottom: '1px solid #303030' }}
      >
        <Table
          columns={columns}
          dataSource={issues}
          rowKey="id"
          loading={loading}
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
          scroll={{ x: 1000 }}
          size="middle"
        />
      </ProCard>

      {/* Detail Modal */}
      <Modal
        title={selectedIssue?.title}
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        width={700}
        footer={[
          selectedIssue?.status === 'open' && selectedIssue?.auto_fixable && (
            <Button
              key="fix"
              icon={<ThunderboltOutlined />}
              onClick={() => handleAutoFix(selectedIssue)}
              loading={fixLoading[selectedIssue?.id]}
            >
              自动修复
            </Button>
          ),
          selectedIssue?.status !== 'resolved' && (
            <Button
              key="resolve"
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={() => handleResolve(selectedIssue?.id)}
            >
              标记已解决
            </Button>
          ),
          <Button key="close" onClick={() => setDetailVisible(false)}>
            关闭
          </Button>,
        ]}
      >
        {selectedIssue && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="ID">{selectedIssue.id}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Badge
                status={statusConfig[selectedIssue.status]?.color}
                text={statusConfig[selectedIssue.status]?.label}
              />
            </Descriptions.Item>
            <Descriptions.Item label="严重度">
              <Tag color={severityConfig[selectedIssue.severity]?.color}>
                {severityConfig[selectedIssue.severity]?.label}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="命名空间">{selectedIssue.namespace}</Descriptions.Item>
            <Descriptions.Item label="资源" span={2}>
              {selectedIssue.resource_type}/{selectedIssue.resource_name}
            </Descriptions.Item>
            <Descriptions.Item label="描述" span={2}>
              {selectedIssue.description || '-'}
            </Descriptions.Item>
            {selectedIssue.root_cause && (
              <Descriptions.Item label="根因分析" span={2}>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                  {selectedIssue.root_cause}
                </pre>
              </Descriptions.Item>
            )}
            {selectedIssue.remediation && (
              <Descriptions.Item label="修复建议" span={2}>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                  {selectedIssue.remediation}
                </pre>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="创建时间">
              {selectedIssue.created_at ? new Date(selectedIssue.created_at).toLocaleString() : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="更新时间">
              {selectedIssue.updated_at ? new Date(selectedIssue.updated_at).toLocaleString() : '-'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </Space>
  )
}

export default IssueCenter
