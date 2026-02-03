import { useState } from 'react'
import { Card, Button, Input, Select, Space, message, Spin, Descriptions, Tag, Steps, Timeline } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import {
  SearchOutlined,
  BugOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'

const { TextArea } = Input

function Diagnosis({ apiUrl }) {
  const [namespace, setNamespace] = useState('stress-test')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleDiagnosis = async () => {
    setLoading(true)
    setResult(null)
    
    try {
      const res = await fetch(`${apiUrl}/api/aci/diagnosis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ namespace }),
      })
      const data = await res.json()
      
      if (data.error) {
        message.error(data.error)
      } else {
        setResult(data.report || data)
        message.success('诊断完成')
      }
    } catch (err) {
      message.error('诊断请求失败')
    } finally {
      setLoading(false)
    }
  }

  const renderDiagnosisResult = () => {
    if (!result) return null

    return (
      <Space direction="vertical" size="large" style={{ width: '100%', marginTop: 24 }}>
        {/* Summary */}
        <ProCard
          title="诊断摘要"
          style={{ background: '#141414' }}
          headStyle={{ borderBottom: '1px solid #303030' }}
        >
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="命名空间">{result.namespace || namespace}</Descriptions.Item>
            <Descriptions.Item label="诊断时间">
              {result.timestamp ? new Date(result.timestamp).toLocaleString() : new Date().toLocaleString()}
            </Descriptions.Item>
            <Descriptions.Item label="问题数量">
              <Tag color={result.issues_count > 0 ? 'red' : 'green'}>
                {result.issues_count || 0} 个问题
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={result.status === 'healthy' ? 'green' : 'orange'}>
                {result.status || 'completed'}
              </Tag>
            </Descriptions.Item>
          </Descriptions>
        </ProCard>

        {/* Root Cause */}
        {result.root_cause && (
          <ProCard
            title="根因分析"
            style={{ background: '#141414' }}
            headStyle={{ borderBottom: '1px solid #303030' }}
          >
            <div style={{ 
              background: '#1a1a2e', 
              padding: 16, 
              borderRadius: 8,
              border: '1px solid #303030',
            }}>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#fff' }}>
                {typeof result.root_cause === 'string' 
                  ? result.root_cause 
                  : JSON.stringify(result.root_cause, null, 2)}
              </pre>
            </div>
          </ProCard>
        )}

        {/* Recommendations */}
        {result.recommendations && (
          <ProCard
            title="修复建议"
            style={{ background: '#141414' }}
            headStyle={{ borderBottom: '1px solid #303030' }}
          >
            <Timeline
              items={
                (Array.isArray(result.recommendations) 
                  ? result.recommendations 
                  : [result.recommendations]
                ).map((rec, idx) => ({
                  color: idx === 0 ? 'blue' : 'gray',
                  children: (
                    <div>
                      <strong>步骤 {idx + 1}</strong>
                      <p style={{ margin: '8px 0 0' }}>{rec}</p>
                    </div>
                  ),
                }))
              }
            />
          </ProCard>
        )}

        {/* Raw Data */}
        <ProCard
          title="原始数据"
          collapsible
          defaultCollapsed
          style={{ background: '#141414' }}
          headStyle={{ borderBottom: '1px solid #303030' }}
        >
          <pre style={{ 
            background: '#0d1117', 
            padding: 16, 
            borderRadius: 8,
            overflow: 'auto',
            maxHeight: 400,
            color: '#e6e6e6',
            fontSize: 12,
          }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        </ProCard>
      </Space>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* Diagnosis Input */}
      <ProCard
        title={
          <Space>
            <ExperimentOutlined />
            智能诊断
          </Space>
        }
        style={{ background: '#141414' }}
        headStyle={{ borderBottom: '1px solid #303030' }}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <label style={{ color: '#aaa', marginBottom: 8, display: 'block' }}>
              目标命名空间
            </label>
            <Input
              placeholder="输入要诊断的命名空间"
              value={namespace}
              onChange={(e) => setNamespace(e.target.value)}
              style={{ width: 300 }}
              prefix={<SearchOutlined style={{ color: '#666' }} />}
            />
          </div>

          <Button
            type="primary"
            icon={loading ? <LoadingOutlined /> : <BugOutlined />}
            onClick={handleDiagnosis}
            loading={loading}
            size="large"
          >
            {loading ? '正在诊断...' : '开始诊断'}
          </Button>

          {loading && (
            <Steps
              current={1}
              size="small"
              items={[
                { title: '收集数据', status: 'finish' },
                { title: '分析问题', status: 'process' },
                { title: '生成报告', status: 'wait' },
              ]}
            />
          )}
        </Space>
      </ProCard>

      {/* Results */}
      {renderDiagnosisResult()}
    </Space>
  )
}

export default Diagnosis
